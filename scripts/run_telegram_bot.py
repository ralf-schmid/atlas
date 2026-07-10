"""Starts the Telegram bot's polling loop as a long-running process — see
docs/features/F049-telegram-bot-polling-service.md.

Without this process running, Telegram delivers button-press callback_querys
into the void: nothing is listening for them (see F049 §1). Builds the same
compiled orchestrator graph as scripts/run_scheduler.py (against the same
Postgres checkpointer) so an inline-button press can resume the exact paused
`interrupt()` a HITL-pending decision is waiting on, even though this is a
separate process from the one that reached the interrupt (F022 §2: thread_id +
interrupt_id travel through `decision.hitl` for exactly this reason).

Usage: DATABASE_URL=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \
    uv run python scripts/run_telegram_bot.py
"""

from __future__ import annotations

import os

from langgraph.checkpoint.postgres import PostgresSaver

from src.db.base import get_session_factory
from src.llm.client import LiteLLMClient
from src.llm.config import load_llm_config
from src.logging_config import configure_logging
from src.orchestrator.graph import build_and_compile_graph
from src.telegram.bot import build_application
from src.telegram.config import load_config as load_telegram_config


def main() -> None:
    configure_logging()
    database_url = os.environ["DATABASE_URL"]
    session_factory = get_session_factory()

    llm_config = load_llm_config()
    llm_client = LiteLLMClient(
        base_url=llm_config.base_url, api_key=os.environ["LITELLM_MASTER_KEY"]
    )
    telegram_config = load_telegram_config()

    checkpointer_conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(checkpointer_conninfo) as checkpointer:
        checkpointer.setup()
        graph = build_and_compile_graph(
            session_factory, llm_client, llm_config, checkpointer=checkpointer
        )

        app = build_application(telegram_config, session_factory, graph)
        app.run_polling()


if __name__ == "__main__":
    main()
