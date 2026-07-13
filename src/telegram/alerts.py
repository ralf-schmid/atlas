"""One-off alert sends, outside the HITL/command `Application` — see F013.

`bot.py`'s `Application` is for long-running polling (commands, HITL callbacks); a
webhook handler firing a single alert (e.g. "new publication issue detected") doesn't
need a running bot, just one `sendMessage` call.
"""

from __future__ import annotations

from src.telegram.bot import hitl_approval_keyboard
from src.telegram.config import TelegramConfig
from src.telegram.hitl import HitlRequest, format_approval_message
from telegram import Bot


async def send_alert(config: TelegramConfig, text: str) -> None:
    bot = Bot(token=config.bot_token)
    await bot.send_message(chat_id=config.allowed_chat_id, text=text)


def format_trade_executed_message(
    persona_name: str, instrument: str, qty: float, stop_loss_price: float | None
) -> str:
    """F072: HITL is off in paper mode — this is Ralf's only remaining signal that
    a persona traded, so it goes out via `send_alert` right after the order commits."""
    text = f"✅ {persona_name} hat gehandelt: {qty:g} {instrument}"
    if stop_loss_price is not None:
        text += f"\nStop-Loss: ${stop_loss_price:,.2f}"
    return text


async def send_hitl_approval_request(config: TelegramConfig, request: HitlRequest) -> None:
    bot = Bot(token=config.bot_token)
    await bot.send_message(
        chat_id=config.allowed_chat_id,
        text=format_approval_message(request),
        reply_markup=hitl_approval_keyboard(request.decision_id),
    )
