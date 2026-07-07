"""Turns config/cycles.yaml into APScheduler triggers that call `run_one_cycle` —
see docs/features/F025-cycle-scheduling.md.

Building a scheduler here does not start it running automatically anywhere in this
repo — see F025 §1/§6 ("Aktivierung"). `scripts/run_cycle.py` remains the manual,
single-cycle live-verification entry point (F016/F021/F022/F023).
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Interrupt
from sqlalchemy.orm import Session

from src.db.models import Decision, MarketSession
from src.orchestrator.cycles_config import CyclesConfig
from src.orchestrator.graph import CycleState
from src.telegram.config import load_config as load_telegram_config


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
            args=[graph, session_factory, cycle.seq, MarketSession.US_EQUITY],
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
            args=[graph, session_factory, 0, MarketSession.CRYPTO],
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
            args=[graph, session_factory, 0, MarketSession.CRYPTO],
            id=f"crypto-weekend-{time_str}",
            replace_existing=True,
        )

    return scheduler


def _run_cycle_job(
    graph: CompiledStateGraph[CycleState, None, CycleState, CycleState],
    session_factory: Callable[[], Session],
    seq: int,
    market_session: MarketSession,
) -> None:
    """A single failed cycle (e.g. a broker network error) must not take down the
    scheduler thread and silently cancel every future cycle — see F025 §2."""
    try:
        run_one_cycle(graph, session_factory, datetime.date.today(), seq, market_session)
    except Exception as exc:
        print(f"[scheduler] cycle failed (seq={seq}, market_session={market_session}): {exc}")


def _parse_time(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":")
    return int(hour_str), int(minute_str)
