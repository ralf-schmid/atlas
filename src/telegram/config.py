"""Telegram bot config — token + the single allowed chat id, from environment.

See docs/features/F005-telegram-bot.md. Built against dummy env values until
Ralf provides a real token/chat-id (CLAUDE.md Entscheidungsstand Punkt 6).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str
    allowed_chat_id: int


def load_config() -> TelegramConfig:
    token = _require_env("TELEGRAM_BOT_TOKEN")
    chat_id_raw = _require_env("TELEGRAM_CHAT_ID")
    try:
        chat_id = int(chat_id_raw)
    except ValueError as exc:
        raise ValueError(f"TELEGRAM_CHAT_ID must be an integer, got {chat_id_raw!r}") from exc
    return TelegramConfig(bot_token=token, allowed_chat_id=chat_id)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
