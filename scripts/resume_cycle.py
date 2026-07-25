"""Resumes a crashed cycle run from its Postgres checkpoint.

Crash-recovery entry point for the P4 DoD test (docs/dod/phase-4.md): after the
scheduler process dies mid-cycle, the LangGraph run for that cycle sits at its
last Postgres checkpoint — nothing resumes it automatically (`run_scheduler.py`
only registers cron jobs, and the next cron fire uses a new thread_id).
Invoking the graph with input `None` and the crashed run's thread_id continues
from the checkpoint: completed nodes are not re-run, pending ones are.

The thread_id format is `{trading_day}-{seq}-{market_session}` (see
`run_one_cycle` in src/orchestrator/scheduler.py), e.g. `2026-07-25-0-crypto`.

Runs against the real stack — resuming executes the remaining nodes for real
(LLM cost, potential paper orders), exactly as the crashed cycle would have.

Usage (no image rebuild needed — feed via stdin):
  ssh atlas-ugreen 'sudo -n docker exec -i atlas-scheduler-1 python - <thread_id>' \
      < scripts/resume_cycle.py
"""

from __future__ import annotations

import os
import sys

from langgraph.checkpoint.postgres import PostgresSaver

from src.db.base import get_session_factory
from src.llm.client import LiteLLMClient
from src.llm.config import load_llm_config
from src.logging_config import configure_logging
from src.orchestrator.graph import build_and_compile_graph


def main() -> None:
    configure_logging()
    thread_id = sys.argv[1]
    database_url = os.environ["DATABASE_URL"]
    session_factory = get_session_factory()

    llm_config = load_llm_config()
    llm_client = LiteLLMClient(
        base_url=llm_config.base_url, api_key=os.environ["LITELLM_MASTER_KEY"]
    )

    # psycopg's raw Connection (used by PostgresSaver) doesn't understand the
    # SQLAlchemy "+psycopg" dialect marker in DATABASE_URL (same as run_cycle.py).
    checkpointer_conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(checkpointer_conninfo) as checkpointer:
        graph = build_and_compile_graph(
            session_factory, llm_client, llm_config, checkpointer=checkpointer
        )
        config = {"configurable": {"thread_id": thread_id}}

        state = graph.get_state(config)
        if state.created_at is None:
            print(f"no checkpoint found for thread_id={thread_id!r} — nothing to resume")
            raise SystemExit(1)
        pending = [task.name for task in state.tasks]
        print(f"checkpoint found (created {state.created_at}); pending tasks: {pending}")
        if not pending:
            print("run already complete — nothing to resume")
            raise SystemExit(0)

        # input=None: continue the existing checkpointed run instead of starting over.
        final_state: dict[str, object] = graph.invoke(None, config=config)

        interrupts = final_state.get("__interrupt__")
        if isinstance(interrupts, list):
            print(f"{len(interrupts)} decision(s) awaiting Telegram approval")
        print(f"resume finished; cycle_id={final_state.get('cycle_id')}")


if __name__ == "__main__":
    main()
