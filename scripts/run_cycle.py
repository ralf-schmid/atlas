"""Runs one orchestrator cycle for real (real Postgres, real PostgresSaver
checkpointer). No scheduler yet — manual/live-verification entry point only, see
docs/features/F016-orchestrator-graph-skeleton.md.

Usage: DATABASE_URL=... uv run python scripts/run_cycle.py
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import Callable

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Interrupt
from sqlalchemy.orm import Session

from src.db.base import get_session_factory
from src.db.models import Decision, MarketSession
from src.llm.client import LiteLLMClient
from src.llm.config import load_llm_config
from src.orchestrator.graph import CycleState, build_and_compile_graph
from src.telegram.config import load_config as load_telegram_config


def _notify_pending_hitl_decisions(
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


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    session_factory = get_session_factory()
    trading_day = datetime.date.today()

    llm_config = load_llm_config()
    llm_client = LiteLLMClient(
        base_url=llm_config.base_url, api_key=os.environ["LITELLM_MASTER_KEY"]
    )

    # psycopg's raw Connection (used by PostgresSaver) doesn't understand the
    # SQLAlchemy "+psycopg" dialect marker in DATABASE_URL.
    checkpointer_conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(checkpointer_conninfo) as checkpointer:
        checkpointer.setup()
        graph = build_and_compile_graph(
            session_factory, llm_client, llm_config, checkpointer=checkpointer
        )

        initial_state = CycleState(
            trading_day=trading_day.isoformat(),
            seq=1,
            market_session=MarketSession.US_EQUITY.value,
            cycle_id=None,
            research_item_ids=[],
        )
        thread_id = f"{trading_day.isoformat()}-1-us_equity"
        final_state = graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
        print(final_state)

        interrupts = final_state.get("__interrupt__")
        if interrupts:
            _notify_pending_hitl_decisions(session_factory, thread_id, list(interrupts))
            print(f"{len(interrupts)} decision(s) awaiting Telegram approval")


if __name__ == "__main__":
    main()
