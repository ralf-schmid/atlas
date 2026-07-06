"""One-off alert sends, outside the HITL/command `Application` — see F013.

`bot.py`'s `Application` is for long-running polling (commands, HITL callbacks); a
webhook handler firing a single alert (e.g. "new publication issue detected") doesn't
need a running bot, just one `sendMessage` call.
"""

from __future__ import annotations

from src.telegram.config import TelegramConfig
from telegram import Bot


async def send_alert(config: TelegramConfig, text: str) -> None:
    bot = Bot(token=config.bot_token)
    await bot.send_message(chat_id=config.allowed_chat_id, text=text)
