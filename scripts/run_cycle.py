"""Runs one orchestrator cycle for real (real Postgres, real PostgresSaver
checkpointer). Manual, single-cycle live-verification entry point — see
docs/features/F016-orchestrator-graph-skeleton.md and
docs/features/F025-cycle-scheduling.md (the scheduler is built there but not
started automatically anywhere; this script remains the manual trigger).

Usage: DATABASE_URL=... uv run python scripts/run_cycle.py
"""

from __future__ import annotations

import datetime
import os

from langgraph.checkpoint.postgres import PostgresSaver

from src.db.base import get_session_factory
from src.db.models import MarketSession
from src.llm.client import LiteLLMClient
from src.llm.config import load_llm_config
from src.orchestrator.graph import build_and_compile_graph
from src.orchestrator.scheduler import run_one_cycle


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    session_factory = get_session_factory()

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

        final_state = run_one_cycle(
            graph, session_factory, datetime.date.today(), 1, MarketSession.US_EQUITY
        )
        print(final_state)

        interrupts = final_state.get("__interrupt__")
        if isinstance(interrupts, list):
            print(f"{len(interrupts)} decision(s) awaiting Telegram approval")


if __name__ == "__main__":
    main()
