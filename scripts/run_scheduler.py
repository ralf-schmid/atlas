"""Starts the cycle scheduler as a long-running process — see
docs/features/F025-cycle-scheduling.md §6.

NOT started automatically anywhere. Running this begins automated, unattended
cycles (real LLM cost per F019/F021, potential real order placement per F023 once
HITL approves or is off) on the schedule in config/cycles.yaml. Only run this
deliberately, on Ralf's explicit go-ahead.

Usage: DATABASE_URL=... uv run python scripts/run_scheduler.py
"""

from __future__ import annotations

import os
import signal
import time
from types import FrameType

from langgraph.checkpoint.postgres import PostgresSaver

from src.db.base import get_session_factory
from src.llm.client import LiteLLMClient
from src.llm.config import load_llm_config
from src.orchestrator.cycles_config import load_cycles_config
from src.orchestrator.graph import build_and_compile_graph
from src.orchestrator.scheduler import build_scheduler

_shutdown = False


def _handle_signal(signum: int, frame: FrameType | None) -> None:
    global _shutdown
    _shutdown = True


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    session_factory = get_session_factory()

    llm_config = load_llm_config()
    llm_client = LiteLLMClient(
        base_url=llm_config.base_url, api_key=os.environ["LITELLM_MASTER_KEY"]
    )
    cycles_config = load_cycles_config()

    checkpointer_conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(checkpointer_conninfo) as checkpointer:
        checkpointer.setup()
        graph = build_and_compile_graph(
            session_factory, llm_client, llm_config, checkpointer=checkpointer
        )

        scheduler = build_scheduler(graph, session_factory, cycles_config)
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        scheduler.start()
        print(f"Scheduler started with {len(scheduler.get_jobs())} jobs. Ctrl-C to stop.")
        try:
            while not _shutdown:
                time.sleep(1)
        finally:
            scheduler.shutdown()


if __name__ == "__main__":
    main()
