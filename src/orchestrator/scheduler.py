"""Turns config/cycles.yaml into APScheduler triggers that call `run_one_cycle` —
see docs/features/F025-cycle-scheduling.md.

Building a scheduler here does not start it running automatically anywhere in this
repo — see F025 §1/§6 ("Aktivierung"). `scripts/run_cycle.py` remains the manual,
single-cycle live-verification entry point (F016/F021/F022/F023).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
import zoneinfo
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter
from src.broker.registry import get_adapter, get_adapter_type
from src.db.models import (
    Cycle,
    Decision,
    DecisionStatus,
    MarketSession,
    OrderRecord,
    Persona,
    Portfolio,
)
from src.orchestrator.cycles_config import CyclesConfig
from src.orchestrator.graph import CycleState
from src.orchestrator.reporting import generate_portfolio_snapshot
from src.orchestrator.trading import execute_decision
from src.telegram.config import load_config as load_telegram_config
from src.telegram.digest import build_digest_data, render_daily_digest
from src.telegram.hitl import HitlDecision, HitlOutcome
from src.telegram.hitl_store import apply_hitl_outcome, decision_to_hitl_request

_HITL_SWEEP_INTERVAL_MINUTES = 5
_STUCK_DECISION_SWEEP_INTERVAL_MINUTES = 15

logger = logging.getLogger(__name__)

# In-memory, per (market_session, seq) job — resets on process restart, which is
# an acceptable trade-off (see docs/features/F029-scheduler-logging-alert.md §2):
# this scheduler process is a long-lived singleton, restarts are rare, and losing
# a streak on restart only delays the next alert by up to one extra failure.
_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 2
_consecutive_failures: dict[str, int] = {}


def run_one_cycle(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
    trading_day: datetime.date,
    seq: int,
    market_session: MarketSession,
) -> dict[str, object]:
    initial_state = CycleState(
        trading_day=trading_day.isoformat(),
        seq=seq,
        market_session=market_session.value,
        cycle_id=None,
        research_item_ids=[],
    )
    thread_id = f"{trading_day.isoformat()}-{seq}-{market_session.value}"
    final_state: dict[str, object] = graph.invoke(
        initial_state, config={"configurable": {"thread_id": thread_id}}
    )

    interrupts = final_state.get("__interrupt__")
    if isinstance(interrupts, list):
        notify_pending_hitl_decisions(session_factory, thread_id, interrupts)

    return final_state


def notify_pending_hitl_decisions(
    session_factory: Callable[[], Session], thread_id: str, interrupts: list[Interrupt]
) -> None:
    """Stores thread_id + the real interrupt id on each HITL_PENDING decision (so a
    later Telegram callback, possibly in a different process, knows exactly what to
    resume — see F022 §2), then sends the approval message."""
    from src.telegram.alerts import send_hitl_approval_request
    from src.telegram.hitl import HitlRequest

    telegram_config = load_telegram_config()

    with session_factory() as session:
        for pending in interrupts:
            payload = pending.value
            decision_id = uuid.UUID(payload["decision_id"])
            decision = session.get_one(Decision, decision_id)
            hitl = dict(decision.hitl or {})
            hitl["thread_id"] = thread_id
            hitl["interrupt_id"] = pending.id
            decision.hitl = hitl
            session.add(decision)
            session.commit()

            request = HitlRequest(
                decision_id=decision_id,
                persona_name=payload["persona_name"],
                instrument=payload["instrument"],
                thesis_text=payload["thesis_text"],
                amount_usd=float(payload.get("amount_usd") or 0.0),
                stop_loss_price=float(payload.get("stop_loss_price") or 0.0),
                created_at=datetime.datetime.now(datetime.UTC),
            )
            asyncio.run(send_hitl_approval_request(telegram_config, request))


def build_scheduler(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
    cycles_config: CyclesConfig,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()

    for cycle in cycles_config.stock_cycles:
        if not cycle.active:
            continue
        hour, minute = _parse_time(cycle.time)
        scheduler.add_job(
            _run_cycle_job,
            trigger="cron",
            # F061: unlike the crypto jobs below, this had no day_of_week filter —
            # US equity cycles would fire every day including weekends, when the
            # market is closed (real LLM cost against stale Friday data, no new
            # signal possible).
            day_of_week="mon-fri",
            hour=hour,
            minute=minute,
            timezone=cycles_config.stock_timezone,
            args=[
                graph,
                session_factory,
                cycle.seq,
                MarketSession.US_EQUITY,
                cycles_config.stock_timezone,
            ],
            id=f"stock-c{cycle.seq}",
            replace_existing=True,
        )

    for time_str in cycles_config.crypto_weekday_times:
        hour, minute = _parse_time(time_str)
        scheduler.add_job(
            _run_cycle_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=hour,
            minute=minute,
            timezone=cycles_config.crypto_timezone,
            args=[graph, session_factory, 0, MarketSession.CRYPTO, cycles_config.crypto_timezone],
            id=f"crypto-weekday-{time_str}",
            replace_existing=True,
        )

    for time_str in cycles_config.crypto_weekend_times:
        hour, minute = _parse_time(time_str)
        scheduler.add_job(
            _run_cycle_job,
            trigger="cron",
            day_of_week="sat,sun",
            hour=hour,
            minute=minute,
            timezone=cycles_config.crypto_timezone,
            args=[graph, session_factory, 0, MarketSession.CRYPTO, cycles_config.crypto_timezone],
            id=f"crypto-weekend-{time_str}",
            replace_existing=True,
        )

    # Security-audit P5 / F022 §1 non-scope: a HITL_PENDING decision nobody ever
    # answers stays pending forever without this — the 30-minute timeout logic
    # (src/telegram/hitl.py) only fires on an actual button press.
    scheduler.add_job(
        _sweep_expired_hitl_job,
        trigger="interval",
        minutes=_HITL_SWEEP_INTERVAL_MINUTES,
        args=[graph, session_factory],
        id="hitl-timeout-sweep",
        replace_existing=True,
    )

    # F050 §1: an APPROVED decision whose broker call fails (network blip, a bad
    # stop price, a transient 5xx) has no code path back to `execute_decision` once
    # its cycle's Send-branch has finished — `_find_hitl_decision`'s idempotency
    # replay in persona_analysis.py is scoped to that one cycle_id, so the next
    # cycle never revisits it. Live-confirmed: two real Telegram-approved buy
    # decisions (AAPL, ALDX) got stuck exactly this way. This sweep is the retry
    # F023's own docstring already promised ("wird beim nächsten Lauf erneut
    # versucht") but that never actually existed.
    scheduler.add_job(
        _retry_stuck_decisions_job,
        trigger="interval",
        minutes=_STUCK_DECISION_SWEEP_INTERVAL_MINUTES,
        args=[session_factory],
        id="stuck-decision-retry-sweep",
        replace_existing=True,
    )

    # F070: ARCHITECTURE.md §6.4 Punkt 3 — daily push digest (Trades/Depotwert/
    # Cash/offene Positionen/LLM-Kosten je Persona), not just the on-demand
    # `/digest` command (src/telegram/bot.py). Fires every day, not just
    # weekdays — CRYPTOR trades weekends too, config/cycles.yaml crypto section.
    # Timed after the last stock cycle C4 (15:15 ET) with a reporting buffer.
    hour, minute = _parse_time(cycles_config.digest_time)
    scheduler.add_job(
        _daily_digest_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=cycles_config.stock_timezone,
        args=[session_factory],
        id="daily-digest",
        replace_existing=True,
    )

    return scheduler


def _run_cycle_job(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
    seq: int,
    market_session: MarketSession,
    timezone: str,
) -> None:
    """A single failed cycle (e.g. a broker network error) must not take down the
    scheduler thread and silently cancel every future cycle — see F025 §2."""
    # trading_day in the market's timezone, not the host's: the UGREEN runs on
    # Europe/Berlin, where a 00:00-UTC crypto cycle would otherwise get tomorrow's
    # date and a US C4 cycle could get the wrong day around midnight.
    trading_day = datetime.datetime.now(zoneinfo.ZoneInfo(timezone)).date()
    job_key = f"{market_session.value}-{seq}"
    try:
        run_one_cycle(graph, session_factory, trading_day, seq, market_session)
        _consecutive_failures[job_key] = 0
    except Exception:
        logger.error(
            "cycle failed",
            exc_info=True,
            extra={
                "seq": seq,
                "market_session": market_session.value,
                "trading_day": trading_day.isoformat(),
            },
        )
        failure_count = _consecutive_failures.get(job_key, 0) + 1
        _consecutive_failures[job_key] = failure_count
        if failure_count >= _CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
            _consecutive_failures[job_key] = 0  # re-arm: alert again after 2 more fails
            _send_cycle_failure_alert(job_key, failure_count)


def _send_cycle_failure_alert(job_key: str, failure_count: int) -> None:
    """Best-effort — a Telegram outage must not take down the scheduler thread
    either (same non-fatal contract as the cycle failure itself)."""
    from src.telegram.alerts import send_alert

    try:
        telegram_config = load_telegram_config()
        text = f"⚠️ ATLAS-Zyklus {job_key} ist {failure_count}x in Folge fehlgeschlagen."
        asyncio.run(send_alert(telegram_config, text))
    except Exception:
        logger.error("failed to send cycle-failure Telegram alert", exc_info=True)


def _daily_digest_job(session_factory: Callable[[], Session]) -> None:
    """F070: builds today's `DigestData` (portfolio_snapshot/order_record/
    position_snapshot/cost_ledger, only active personas) and pushes it as an
    unsolicited Telegram message — same primitive (`send_alert`) as every other
    alert here, no running bot `Application` needed. Non-fatal: a failed send
    (Telegram outage, DB hiccup) must not take down the scheduler thread; unlike
    the cycle/ingestion jobs there's no consecutive-failure counter — a once-daily
    job's next attempt is tomorrow regardless, and re-alerting "digest failed
    again" would just be one more Telegram message about the exact same outage
    the missing digest already signals by its absence."""
    from src.telegram.alerts import send_alert

    try:
        with session_factory() as session:
            data = build_digest_data(session, datetime.date.today())
        text = render_daily_digest(data)
        telegram_config = load_telegram_config()
        asyncio.run(send_alert(telegram_config, text))
    except Exception:
        logger.error("failed to send daily Telegram digest", exc_info=True)


def _sweep_expired_hitl_job(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
) -> None:
    """A failed sweep must not take down the scheduler thread either — same
    non-fatal contract as `_run_cycle_job`."""
    try:
        count = sweep_expired_hitl_decisions(graph, session_factory)
        if count:
            logger.info("hitl timeout sweep rejected %d expired decision(s)", count)
    except Exception:
        logger.error("hitl timeout sweep failed", exc_info=True)


def sweep_expired_hitl_decisions(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
    now: datetime.datetime | None = None,
) -> int:
    """Rejects HITL_PENDING decisions nobody answered within the 30-minute window
    (F022 §1 non-scope, security-audit P5) and resumes their paused graph run with
    "rejected" — the same `Command(resume=...)` mechanism a real Telegram button
    press uses (see `src/telegram/bot.py::_handle_hitl_callback`).

    One decision's resume failing must not block the rest of the sweep — each is
    applied and resumed independently, same non-fatal contract as elsewhere in
    this module.
    """
    now = now or datetime.datetime.now(datetime.UTC)
    expired: list[tuple[uuid.UUID, str | None, str | None]] = []

    with session_factory() as session:
        rows = session.execute(
            select(Decision, Cycle, Persona.name)
            .join(Cycle, Decision.cycle_id == Cycle.id)
            .join(Portfolio, Decision.portfolio_id == Portfolio.id)
            .join(Persona, Portfolio.persona_id == Persona.id)
            .where(Decision.status == DecisionStatus.HITL_PENDING)
        ).all()

        for decision, cycle, persona_name in rows:
            request = decision_to_hitl_request(decision, cycle, persona_name)
            if not request.is_expired(now):
                continue
            outcome = HitlOutcome(decision=HitlDecision.REJECTED, decided_by="timeout")
            apply_hitl_outcome(session, decision, outcome, now)
            hitl = decision.hitl or {}
            expired.append((decision.id, hitl.get("thread_id"), hitl.get("interrupt_id")))
        session.commit()

    for decision_id, thread_id, interrupt_id in expired:
        if not (thread_id and interrupt_id):
            continue
        try:
            graph.invoke(
                Command(resume={interrupt_id: HitlDecision.REJECTED.value}),
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception:
            logger.error(
                "failed to resume graph for timed-out HITL decision",
                exc_info=True,
                extra={"decision_id": str(decision_id)},
            )

    return len(expired)


def _retry_stuck_decisions_job(session_factory: Callable[[], Session]) -> None:
    """A failed sweep must not take down the scheduler thread either — same
    non-fatal contract as `_run_cycle_job`/`_sweep_expired_hitl_job`."""
    try:
        count = retry_stuck_decisions(session_factory)
        if count:
            logger.info("stuck-decision retry sweep executed %d decision(s)", count)
    except Exception:
        logger.error("stuck-decision retry sweep failed", exc_info=True)


def retry_stuck_decisions(
    session_factory: Callable[[], Session],
    adapter_factory: Callable[[str], BrokerAdapter] = get_adapter,
) -> int:
    """Re-attempts `execute_decision` for every APPROVED decision that has no
    `order_record` yet (see F050 §1: `execute_decision` failing at the broker
    leaves the decision on APPROVED with a FAILED `agent_run`, but nothing else
    ever revisits it). Each decision is retried independently, same non-fatal
    contract as `sweep_expired_hitl_decisions` — one persistently-failing decision
    (e.g. a delisted symbol) must not block the rest of the sweep. `place_order`'s
    `client_order_id=decision_id` (F027) makes repeated attempts broker-side safe.
    """
    executed = 0
    with session_factory() as session:
        stmt = (
            select(Decision, Persona.name)
            .join(Portfolio, Decision.portfolio_id == Portfolio.id)
            .join(Persona, Portfolio.persona_id == Persona.id)
            .outerjoin(OrderRecord, OrderRecord.decision_id == Decision.id)
            .where(Decision.status == DecisionStatus.APPROVED, OrderRecord.id.is_(None))
        )
        for decision, persona_name in session.execute(stmt).all():
            broker_adapter = adapter_factory(persona_name)
            try:
                execute_decision(session, decision, broker_adapter, get_adapter_type(persona_name))
                session.commit()
                executed += 1
            except Exception:
                session.rollback()
                logger.error(
                    "failed to retry stuck decision",
                    exc_info=True,
                    extra={"decision_id": str(decision.id)},
                )
                continue

            # F059: without this, a position bought here is invisible in the
            # dashboard/Grafana (both read `position_snapshot`, F050's own retry
            # sweep was the only decision-execution path that didn't call this)
            # until whatever cycle next runs for this portfolio — potentially
            # hours away. F063: committed as its own separate transaction, after
            # the execute_decision commit above — a snapshot failure here must
            # not roll back the order execution that already succeeded.
            try:
                generate_portfolio_snapshot(
                    session,
                    decision.portfolio_id,
                    broker_adapter,
                    datetime.datetime.now(datetime.UTC),
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.error(
                    "failed to generate portfolio snapshot after retrying stuck decision",
                    exc_info=True,
                    extra={"decision_id": str(decision.id)},
                )
    return executed


def _parse_time(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":")
    return int(hour_str), int(minute_str)
