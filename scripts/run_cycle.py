"""Runs one orchestrator cycle for real (real Postgres, real PostgresSaver
checkpointer). No scheduler yet — manual/live-verification entry point only, see
docs/features/F016-orchestrator-graph-skeleton.md.

Usage: DATABASE_URL=... uv run python scripts/run_cycle.py
"""

from __future__ import annotations

import datetime
import os

from langgraph.checkpoint.postgres import PostgresSaver

from src.db.base import get_session_factory
from src.db.models import MarketSession
from src.orchestrator.graph import CycleState, build_and_compile_graph


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    session_factory = get_session_factory()
    trading_day = datetime.date.today()

    # psycopg's raw Connection (used by PostgresSaver) doesn't understand the
    # SQLAlchemy "+psycopg" dialect marker in DATABASE_URL.
    checkpointer_conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(checkpointer_conninfo) as checkpointer:
        checkpointer.setup()
        graph = build_and_compile_graph(session_factory, checkpointer=checkpointer)

        initial_state = CycleState(
            trading_day=trading_day.isoformat(),
            seq=1,
            market_session=MarketSession.US_EQUITY.value,
            cycle_id=None,
            research_item_id=None,
        )
        thread_id = f"{trading_day.isoformat()}-1-us_equity"
        final_state = graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
        print(final_state)


if __name__ == "__main__":
    main()
