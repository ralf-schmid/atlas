"""No coverage existed for this module at all before F062 — this is the actual
code that sends every outgoing Telegram message (alerts + HITL approval
requests), exactly the class of failure Ralf flagged: "the Telegram message
must never simply fail to go out."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from unittest.mock import AsyncMock, patch

from src.telegram.alerts import (
    format_trade_executed_message,
    send_alert,
    send_hitl_approval_request,
)
from src.telegram.config import TelegramConfig
from src.telegram.hitl import HitlRequest

_CONFIG = TelegramConfig(bot_token="123:dummy-token", allowed_chat_id=42)


def test_send_alert_sends_to_the_configured_chat_id():
    with patch("src.telegram.alerts.Bot") as mock_bot_cls:
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        asyncio.run(send_alert(_CONFIG, "cycle failed"))

        mock_bot_cls.assert_called_once_with(token="123:dummy-token")
        mock_bot.send_message.assert_called_once_with(chat_id=42, text="cycle failed")


def test_send_hitl_approval_request_sends_message_with_inline_buttons():
    decision_id = uuid.uuid4()
    request = HitlRequest(
        decision_id=decision_id,
        persona_name="VULTURE",
        instrument="AAPL",
        thesis_text="Momentum",
        amount_usd=275.0,
        stop_loss_price=290.87,
        created_at=datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC),
    )

    with patch("src.telegram.alerts.Bot") as mock_bot_cls:
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        asyncio.run(send_hitl_approval_request(_CONFIG, request))

        mock_bot_cls.assert_called_once_with(token="123:dummy-token")
        (call,) = mock_bot.send_message.call_args_list
        assert call.kwargs["chat_id"] == 42
        assert "VULTURE" in call.kwargs["text"]
        assert "AAPL" in call.kwargs["text"]
        callback_data = {
            button.callback_data
            for row in call.kwargs["reply_markup"].inline_keyboard
            for button in row
        }
        assert callback_data == {
            f"hitl:approve:{decision_id}",
            f"hitl:reject:{decision_id}",
        }


def test_format_trade_executed_message_includes_persona_instrument_and_stop() -> None:
    text = format_trade_executed_message(
        persona_name="VULTURE", instrument="AAPL", qty=1.5, stop_loss_price=290.87
    )
    assert "VULTURE" in text
    assert "AAPL" in text
    assert "1.5" in text
    assert "290.87" in text


def test_format_trade_executed_message_omits_stop_line_when_absent() -> None:
    text = format_trade_executed_message(
        persona_name="VULTURE", instrument="AAPL", qty=1.5, stop_loss_price=None
    )
    assert "Stop-Loss" not in text
