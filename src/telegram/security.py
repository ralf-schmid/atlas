"""Chat-ID gate. Must be applied to every handler — commands *and* callback
queries — or the HITL approval buttons become an attack vector
(ARCHITECTURE.md line 489)."""

from __future__ import annotations

from src.telegram.config import TelegramConfig


def is_authorized_chat(chat_id: int, config: TelegramConfig) -> bool:
    return chat_id == config.allowed_chat_id
