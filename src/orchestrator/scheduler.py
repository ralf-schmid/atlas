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
from decimal import Decimal

from apscheduler.schedulers.background import BackgroundScheduler
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Interrupt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.broker.alpaca_paper import AlpacaOrderState, AlpacaPaperAdapter
from src.broker.protocol import BrokerAdapter
from src.broker.registry import get_adapter, get_adapter_type
from src.db.models import (
    Cycle,
    Decision,
    DecisionStatus,
    MarketSession,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
)
from src.llm.client import LiteLLMClient
from src.llm.config import LlmConfig
from src.orchestrator.cycles_config import CyclesConfig
from src.orchestrator.graph import CycleState
from src.orchestrator.reporting import generate_portfolio_snapshot
from src.orchestrator.trading import execute_decision
from src.review.agent import run_review_sweep
from src.review.meta_agent import run_meta_review_sweep
from src.telegram.config import load_config as load_telegram_config
from src.telegram.digest import build_digest_data, render_daily_digest
from src.telegram.hitl import HitlDecision, HitlOutcome
from src.telegram.hitl_store import apply_hitl_outcome, decision_to_hitl_request
from src.telegram.weekly_report import build_weekly_report, render_weekly_report

_HITL_SWEEP_INTERVAL_MINUTES = 5
_STUCK_DECISION_SWEEP_INTERVAL_MINUTES = 15
# F075: reporting-only (chart markers, /holdings last_buy_at, digest trade
# count) — not risk/order-placement-critical, same interval as the stuck-
# decision sweep is a reasonable, unhurried default.
_ORDER_RECONCILE_INTERVAL_MINUTES = 15

logger = logging.getLogger(__name__)

# In-memory, per (market_session, seq) job — resets on process restart, which is
# an acceptable trade-off (see docs/features/F029-scheduler-logging-alert.md §2):
# this scheduler process is a long-lived singleton, restarts are rare, and losing
# a streak on restart only delays the next alert by up to one extra failure.
_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 2
_MAX_ALERT_CAUSE_CHARS = 400
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


# F084: daily, not the §5.2 Sunday-only run. The DoD is "every closed position has
# a review within 7 days"; a daily sweep meets that with margin, and a weekly one
# would need a 7-day-tight window to do the same. Timed after the last US cycle so
# the day's fills are already reconciled.
_REVIEW_SWEEP_HOUR = 17
_REVIEW_SWEEP_MINUTE = 30

# F099: this one *is* the §5.2 Sunday run — it is a sample by design (max. 5/week),
# not a completeness obligation like the review sweep above, so running it daily
# would only spend money faster without covering more ground. An hour after the
# review sweep, on a day with no cycles, so the two never contend for the daily cap.
_META_REVIEW_SWEEP_DAY = "sun"
_META_REVIEW_SWEEP_HOUR = 18
_META_REVIEW_SWEEP_MINUTE = 30

# F089: the §5.2 Sunday "Leaderboard-/Kriterien-Report". Half an hour after the
# meta-review sweep, so the week's reviews (which feed criterion 4, thesis
# quality) are already written when the report reads them.
_WEEKLY_REPORT_DAY = "sun"
_WEEKLY_REPORT_HOUR = 19
_WEEKLY_REPORT_MINUTE = 0


def build_scheduler(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
    cycles_config: CyclesConfig,
    llm_client: LiteLLMClient | None = None,
    llm_config: LlmConfig | None = None,
) -> BackgroundScheduler:
    """`llm_client`/`llm_config` are optional so the existing callers and the
    scheduler-registration tests keep working; the F084 review job is only
    registered when both are supplied."""
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

    # F075: native-Alpaca `order_record`s are created `status=NEW` and nothing
    # ever polled Alpaca for the real fill afterward (F023 §1 non-scope) — every
    # order in production sat on NEW forever, silently blanking the chart
    # markers, /holdings "Letzter Kauf", and the daily digest's trade count.
    # Virtual (internal_ledger) personas don't need this: their fill is known
    # synchronously at placement time (`OrderResult.filled_at`, execute_decision).
    scheduler.add_job(
        _reconcile_order_fills_job,
        trigger="interval",
        minutes=_ORDER_RECONCILE_INTERVAL_MINUTES,
        args=[session_factory],
        id="order-fill-reconciliation",
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

    # F089: ARCHITECTURE.md §5.2 "Sonntag: … Leaderboard-/Kriterien-Report".
    # Pure code over existing data (no LLM), so it needs no client guard — it runs
    # after the meta-review sweep so the week's reviews are already in.
    scheduler.add_job(
        _weekly_report_job,
        trigger="cron",
        day_of_week=_WEEKLY_REPORT_DAY,
        hour=_WEEKLY_REPORT_HOUR,
        minute=_WEEKLY_REPORT_MINUTE,
        timezone=cycles_config.stock_timezone,
        args=[session_factory],
        id="weekly-report",
        replace_existing=True,
    )

    if llm_client is not None and llm_config is not None:
        scheduler.add_job(
            _review_sweep_job,
            trigger="cron",
            hour=_REVIEW_SWEEP_HOUR,
            minute=_REVIEW_SWEEP_MINUTE,
            timezone=cycles_config.stock_timezone,
            args=[session_factory, llm_client, llm_config],
            id="review-sweep",
            replace_existing=True,
        )

        # F099: ARCHITECTURE.md §5.2 "Sonntag: Review-Wochenlauf". Same guard as the
        # review sweep — without an LLM client there is nothing to run.
        scheduler.add_job(
            _meta_review_sweep_job,
            trigger="cron",
            day_of_week=_META_REVIEW_SWEEP_DAY,
            hour=_META_REVIEW_SWEEP_HOUR,
            minute=_META_REVIEW_SWEEP_MINUTE,
            timezone=cycles_config.stock_timezone,
            args=[session_factory, llm_client, llm_config],
            id="meta-review-sweep",
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
        final_state = run_one_cycle(graph, session_factory, trading_day, seq, market_session)
        _consecutive_failures[job_key] = 0
        _alert_on_silent_cycle(session_factory, job_key, final_state)
    except Exception as exc:
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
            _send_cycle_failure_alert(job_key, failure_count, exc)


def _alert_on_silent_cycle(
    session_factory: Callable[[], Session], job_key: str, final_state: dict[str, object]
) -> None:
    """F101: a cycle that finishes without raising but persists no decision at all.

    Live 30.07.-31.07.2026: the LLM route ran out of credits, 13 consecutive cycles
    ingested research and produced zero decisions, and the only signal was a
    generic cycle-failure alert per job key. Every persona always writes at least
    one decision (`hold` counts), so zero is never a legitimate outcome — it means
    the analysis layer never ran. Best-effort like every other alert here.
    """
    cycle_id = final_state.get("cycle_id")
    if not isinstance(cycle_id, str):
        return

    try:
        session = session_factory()
        try:
            decisions = session.scalar(
                select(func.count()).select_from(Decision).where(Decision.cycle_id == cycle_id)
            )
        finally:
            session.close()
        if decisions:
            return

        logger.error("cycle produced no decisions", extra={"job_key": job_key})
        from src.telegram.alerts import send_alert

        asyncio.run(
            send_alert(
                load_telegram_config(),
                f"⚠️ ATLAS-Zyklus {job_key} ist durchgelaufen, hat aber "
                "*keine einzige Decision* erzeugt — Analyse-Layer prüfen "
                "(LLM-Route, Guthaben, Broker).",
            )
        )
    except Exception:
        logger.error("failed to run silent-cycle check", exc_info=True)


def format_cycle_failure_cause(exc: BaseException) -> str:
    """One-line root cause for the alert (F093).

    "Zyklus X ist 2x fehlgeschlagen" alone sent Ralf to the container logs every
    time — live, 34h of identical alerts hid a single cause (exhausted Anthropic
    credits). LangGraph wraps the real error, so walk to the innermost `__cause__`/
    `__context__`, which is where the provider's message actually sits.
    """
    root: BaseException = exc
    seen = {id(exc)}
    while True:
        nxt = root.__cause__ or root.__context__
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(nxt))
        root = nxt

    text = " ".join(str(root).split()) or root.__class__.__name__
    return f"{root.__class__.__name__}: {text}"[:_MAX_ALERT_CAUSE_CHARS]


def _send_cycle_failure_alert(job_key: str, failure_count: int, exc: BaseException) -> None:
    """Best-effort — a Telegram outage must not take down the scheduler thread
    either (same non-fatal contract as the cycle failure itself)."""
    from src.telegram.alerts import send_alert

    try:
        telegram_config = load_telegram_config()
        text = (
            f"⚠️ ATLAS-Zyklus {job_key} ist {failure_count}x in Folge fehlgeschlagen.\n"
            f"Ursache: {format_cycle_failure_cause(exc)}"
        )
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


def _weekly_report_job(session_factory: Callable[[], Session]) -> None:
    """F089: the §4.7 criteria report, pushed to Telegram every Sunday.

    Same non-fatal contract as the daily digest: a Telegram or DB failure must
    not take the scheduler thread down, and a missed weekly report signals itself
    by its absence.
    """
    from src.telegram.alerts import send_alert

    try:
        with session_factory() as session:
            data = build_weekly_report(session, datetime.date.today())
        text = render_weekly_report(data)
        asyncio.run(send_alert(load_telegram_config(), text))
    except Exception:
        logger.error("failed to send weekly Telegram report", exc_info=True)


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
                order_record = execute_decision(
                    session, decision, broker_adapter, get_adapter_type(persona_name)
                )
                session.commit()
                executed += 1
            except ValueError as exc:
                # F080: a ValueError from execute_decision means the decision is
                # structurally unexecutable (broken expected_outcome, qty=None, or —
                # pre-F079 Alt-Decisions — qty rounds to 0 whole shares). Retry would
                # fail identically every sweep. Mark terminal and alert once.
                session.rollback()
                try:
                    decision = session.get_one(Decision, decision.id)
                    decision.status = DecisionStatus.EXECUTION_FAILED
                    decision.rejection_reason = f"execution_failed_permanent: {exc}"
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.error(
                        "failed to mark stuck decision as EXECUTION_FAILED",
                        exc_info=True,
                        extra={"decision_id": str(decision.id)},
                    )
                    continue

                logger.error(
                    "stuck decision permanently failed — marked EXECUTION_FAILED",
                    extra={"decision_id": str(decision.id), "reason": str(exc)},
                )
                try:
                    from src.telegram.alerts import (
                        format_execution_failed_message,
                        send_alert,
                    )

                    text = format_execution_failed_message(
                        persona_name, decision.instrument, str(exc)
                    )
                    asyncio.run(send_alert(load_telegram_config(), text))
                except Exception:
                    logger.error(
                        "failed to send execution-failed telegram alert",
                        exc_info=True,
                        extra={"decision_id": str(decision.id)},
                    )
                continue

            # F080: transient (non-ValueError) failure — leave decision APPROVED
            # so the next sweep retries it.
            except Exception:
                session.rollback()
                logger.error(
                    "failed to retry stuck decision",
                    exc_info=True,
                    extra={"decision_id": str(decision.id)},
                )
                continue

            # F072: same best-effort trade notification as the primary execution
            # path (persona_analysis._notify_trade_executed) — a decision executed
            # here (after an earlier broker-side failure) is just as much "a
            # persona traded" as one executed inline during the cycle.
            try:
                from src.telegram.alerts import format_trade_executed_message, send_alert

                raw = order_record.raw or {}
                qty = raw.get("qty")
                if not isinstance(qty, int | float):
                    raise ValueError(f"order_record {order_record.id} has no numeric qty in raw")
                stop_loss_price = raw.get("stop_loss_price")

                text = format_trade_executed_message(
                    persona_name=persona_name,
                    instrument=decision.instrument,
                    qty=float(qty),
                    stop_loss_price=(
                        float(stop_loss_price) if isinstance(stop_loss_price, int | float) else None
                    ),
                )
                asyncio.run(send_alert(load_telegram_config(), text))
            except Exception:
                logger.error(
                    "failed to send trade-executed telegram alert",
                    exc_info=True,
                    extra={"decision_id": str(decision.id)},
                )

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


def _review_sweep_job(
    session_factory: Callable[[], Session],
    llm_client: LiteLLMClient,
    llm_config: LlmConfig,
) -> None:
    """F084: reviews due decisions. Non-fatal like every other sweep — a review is a
    learning artefact, not a trading action, and must never stop the scheduler."""
    try:
        with session_factory() as session:
            result = run_review_sweep(
                session,
                llm_client,
                llm_config,
                datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            )
            session.commit()
        # `deferred_budget`, not `deferred` — the attribute never existed on
        # SweepResult. With reviewed == 0 (the normal case once the backlog is
        # worked off) the `or` chain reached it and raised, so every quiet sweep
        # logged "review sweep failed" with an AttributeError traceback.
        if result.reviewed or result.deferred_budget or result.failed:
            logger.info(
                "review sweep: %d reviewed, %d deferred (budget), %d failed",
                result.reviewed,
                result.deferred_budget,
                result.failed,
            )
    except Exception:
        logger.error("review sweep failed", exc_info=True)


def _meta_review_sweep_job(
    session_factory: Callable[[], Session],
    llm_client: LiteLLMClient,
    llm_config: LlmConfig,
) -> None:
    """F099: samples `reject_idea` decisions and judges the research pool behind
    them. Non-fatal for the same reason as the review sweep — it is a diagnostic
    artefact, not a trading action."""
    try:
        with session_factory() as session:
            result = run_meta_review_sweep(
                session,
                llm_client,
                llm_config,
                datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            )
            session.commit()
        if result.reviewed or result.deferred_budget or result.failed:
            logger.info(
                "meta-review sweep: %d reviewed, %d deferred (budget), %d failed",
                result.reviewed,
                result.deferred_budget,
                result.failed,
            )
    except Exception:
        logger.error("meta-review sweep failed", exc_info=True)


def _reconcile_order_fills_job(session_factory: Callable[[], Session]) -> None:
    """A failed sweep must not take down the scheduler thread either — same
    non-fatal contract as `_retry_stuck_decisions_job`/`_sweep_expired_hitl_job`."""
    try:
        count = reconcile_order_fills(session_factory)
        if count:
            logger.info("order-fill reconciliation sweep updated %d order(s)", count)
    except Exception:
        logger.error("order-fill reconciliation sweep failed", exc_info=True)


_ALPACA_STATE_TO_ORDER_RECORD_STATUS = {
    AlpacaOrderState.FILLED: OrderRecordStatus.FILLED,
    AlpacaOrderState.PARTIALLY_FILLED: OrderRecordStatus.PARTIALLY_FILLED,
    AlpacaOrderState.CANCELED: OrderRecordStatus.CANCELED,
    AlpacaOrderState.REJECTED: OrderRecordStatus.REJECTED,
    AlpacaOrderState.EXPIRED: OrderRecordStatus.EXPIRED,
}


def reconcile_order_fills(
    session_factory: Callable[[], Session],
    adapter_factory: Callable[[str], BrokerAdapter] = get_adapter,
) -> int:
    """Polls Alpaca for the real status of every `order_record` still `NEW` for a
    native-Alpaca persona and writes back `status`/`filled_at`/`fill_price` (see
    F075). Virtual (`internal_ledger`) personas are skipped — their fill is
    already recorded synchronously at `execute_decision` time, so a `NEW` row for
    one of them means the order genuinely hasn't been placed successfully, not
    that it's pending confirmation. Same non-fatal, per-row contract as
    `retry_stuck_decisions`: one order that fails to poll (e.g. Alpaca hiccup)
    must not block reconciling the rest.
    """
    updated = 0
    with session_factory() as session:
        stmt = (
            select(OrderRecord, Persona.name)
            .join(Decision, OrderRecord.decision_id == Decision.id)
            .join(Portfolio, Decision.portfolio_id == Portfolio.id)
            .join(Persona, Portfolio.persona_id == Persona.id)
            .where(OrderRecord.status == OrderRecordStatus.NEW)
        )
        for order_record, persona_name in session.execute(stmt).all():
            if get_adapter_type(persona_name) != "alpaca_paper":
                continue
            broker_adapter = adapter_factory(persona_name)
            assert isinstance(broker_adapter, AlpacaPaperAdapter)
            try:
                fill_status = broker_adapter.get_order_status(order_record.broker_order_id)
            except Exception:
                logger.error(
                    "failed to poll order status for reconciliation",
                    exc_info=True,
                    extra={"order_record_id": str(order_record.id)},
                )
                continue

            new_status = _ALPACA_STATE_TO_ORDER_RECORD_STATUS.get(fill_status.state)
            if new_status is None:  # still open at Alpaca — nothing to update yet
                continue

            # F096: a FILLED status without a price is not a usable fill — leave the
            # row NEW so the next sweep polls it again rather than freezing a
            # half-recorded fill that review/slippage/charts cannot price.
            if new_status is OrderRecordStatus.FILLED and fill_status.fill_price is None:
                logger.warning(
                    "alpaca reported FILLED without a fill price, leaving order NEW",
                    extra={"order_record_id": str(order_record.id)},
                )
                continue

            order_record.status = new_status
            order_record.filled_at = fill_status.filled_at
            if fill_status.fill_price is not None:
                order_record.fill_price = Decimal(str(fill_status.fill_price))
            session.add(order_record)
            session.commit()
            updated += 1
    return updated


def _parse_time(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":")
    return int(hour_str), int(minute_str)
