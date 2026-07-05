import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.telegram.bot import (
    _handle_hitl,
    _handle_pause,
    _handle_resume,
    _make_handler,
    build_application,
    hitl_approval_keyboard,
)
from src.telegram.config import TelegramConfig

_CONFIG = TelegramConfig(bot_token="123:dummy-token", allowed_chat_id=42)


def test_build_application_succeeds_with_dummy_token():
    app = build_application(_CONFIG)

    assert app is not None


def test_hitl_approval_keyboard_binds_buttons_to_decision_id():
    keyboard = hitl_approval_keyboard(decision_id=42)

    callback_data = {button.callback_data for row in keyboard.inline_keyboard for button in row}
    assert callback_data == {"hitl:approve:42", "hitl:reject:42"}


def _mock_update(chat_id: int, text: str | None = None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def test_make_handler_skips_unauthorized_chat():
    inner = AsyncMock()
    wrapped = _make_handler(_CONFIG, inner)
    update = _mock_update(chat_id=999)

    asyncio.run(wrapped(update, MagicMock()))

    inner.assert_not_called()


def test_make_handler_calls_inner_for_authorized_chat():
    inner = AsyncMock()
    wrapped = _make_handler(_CONFIG, inner)
    update = _mock_update(chat_id=42)

    asyncio.run(wrapped(update, MagicMock()))

    inner.assert_called_once()


def test_handle_pause_replies_with_persona_name():
    update = _mock_update(chat_id=42, text="/pause VULTURE")

    asyncio.run(_handle_pause(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("VULTURE pausiert.")


def test_handle_pause_replies_with_usage_on_invalid_input():
    update = _mock_update(chat_id=42, text="/pause")

    asyncio.run(_handle_pause(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("Usage: /pause <PERSONA>")


def test_handle_resume_replies_with_persona_name():
    update = _mock_update(chat_id=42, text="/resume GUARDIAN")

    asyncio.run(_handle_resume(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("GUARDIAN fortgesetzt.")


def test_handle_hitl_replies_with_activation_state():
    update = _mock_update(chat_id=42, text="/hitl on")

    asyncio.run(_handle_hitl(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("HITL aktiviert.")
