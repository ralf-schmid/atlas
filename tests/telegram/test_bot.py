import asyncio
import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

from src.telegram.bot import (
    _handle_hitl,
    _handle_hitl_callback,
    _handle_pause,
    _handle_resume,
    _make_handler,
    build_application,
    hitl_approval_keyboard,
)
from src.telegram.config import TelegramConfig
from src.telegram.hitl import HitlDecision, HitlOutcome, HitlRequest

_CONFIG = TelegramConfig(bot_token="123:dummy-token", allowed_chat_id=42)
_DECISION_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
_CREATED_AT = datetime.datetime(2026, 7, 5, 12, 0, tzinfo=datetime.UTC)


def test_build_application_succeeds_with_dummy_token():
    app = build_application(_CONFIG)

    assert app is not None


def test_hitl_approval_keyboard_binds_buttons_to_decision_id():
    keyboard = hitl_approval_keyboard(_DECISION_ID)

    callback_data = {button.callback_data for row in keyboard.inline_keyboard for button in row}
    assert callback_data == {
        f"hitl:approve:{_DECISION_ID}",
        f"hitl:reject:{_DECISION_ID}",
    }


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


def _mock_callback_update(chat_id: int, callback_data: str):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def test_handle_hitl_callback_without_session_factory():
    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {}

    asyncio.run(_handle_hitl_callback(update, context))

    update.callback_query.answer.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once_with(
        "HITL: Datenbank nicht konfiguriert."
    )


def test_handle_hitl_callback_approves_pending_decision(monkeypatch):
    request = HitlRequest(
        decision_id=_DECISION_ID,
        instrument="MSFT",
        thesis_text="Momentum",
        amount_usd=1200.0,
        stop_loss_price=100.0,
        created_at=_CREATED_AT,
    )
    outcome = HitlOutcome(decision=HitlDecision.APPROVED, decided_by="user")
    fake_decision = MagicMock(instrument="MSFT")
    fake_session = MagicMock()

    monkeypatch.setattr(
        "src.telegram.bot.load_pending_decision",
        lambda _session, _decision_id: (fake_decision, MagicMock()),
    )
    monkeypatch.setattr("src.telegram.bot.decision_to_hitl_request", lambda _d, _c: request)
    monkeypatch.setattr("src.telegram.bot.process_callback", lambda _r, _d, _n: outcome)
    monkeypatch.setattr("src.telegram.bot.apply_hitl_outcome", lambda *_args: None)

    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=fake_session)}

    asyncio.run(_handle_hitl_callback(update, context))

    fake_session.commit.assert_called_once()
    fake_session.close.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once_with("✅ Freigabe erteilt: MSFT.")
