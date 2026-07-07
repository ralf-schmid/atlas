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

from src.db.models import Cycle, Decision, DecisionStatus, MarketSession
from src.orchestrator.cycles_config import CyclesConfig
from src.orchestrator.graph import CycleState
from src.telegram.config import load_config as load_telegram_config
from src.telegram.hitl import HitlDecision, HitlOutcome
from src.telegram.hitl_store import apply_hitl_outcome, decision_to_hitl_request

_HITL_SWEEP_INTERVAL_MINUTES = 5

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
            select(Decision, Cycle)
            .join(Cycle, Decision.cycle_id == Cycle.id)
            .where(Decision.status == DecisionStatus.HITL_PENDING)
        ).all()

        for decision, cycle in rows:
            request = decision_to_hitl_request(decision, cycle)
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


def _parse_time(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":")
    return int(hour_str), int(minute_str)
