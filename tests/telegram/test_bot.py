import asyncio
import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

from src.telegram.bot import (
    _handle_digest,
    _handle_hitl,
    _handle_hitl_callback,
    _handle_pause,
    _handle_resume,
    _handle_status,
    _make_callback_handler,
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


def test_build_application_wires_session_factory_and_graph_into_bot_data():
    session_factory = MagicMock()
    graph = MagicMock()

    app = build_application(_CONFIG, session_factory, graph)

    assert app.bot_data["session_factory"] is session_factory
    assert app.bot_data["graph"] is graph


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


def test_make_callback_handler_skips_unauthorized_chat():
    # Same authorization gate as _make_handler, but for CallbackQueryHandler
    # (button presses) — a HITL approve/reject button is exactly the kind of
    # action that must never run for an unauthorized chat.
    inner = AsyncMock()
    wrapped = _make_callback_handler(_CONFIG, inner)
    update = _mock_update(chat_id=999)

    asyncio.run(wrapped(update, MagicMock()))

    inner.assert_not_called()


def test_make_callback_handler_calls_inner_for_authorized_chat():
    inner = AsyncMock()
    wrapped = _make_callback_handler(_CONFIG, inner)
    update = _mock_update(chat_id=42)

    asyncio.run(wrapped(update, MagicMock()))

    inner.assert_called_once()


def test_handle_status_replies_with_placeholder():
    update = _mock_update(chat_id=42, text="/status")

    asyncio.run(_handle_status(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("Status: noch keine Portfolios konfiguriert.")


def test_handle_digest_reports_failure_without_session_factory():
    update = _mock_update(chat_id=42, text="/digest")
    context = MagicMock()
    context.application.bot_data = {}

    asyncio.run(_handle_digest(update, context))

    update.message.reply_text.assert_called_once_with("Digest: Datenbank nicht konfiguriert.")


def test_handle_digest_sends_the_rendered_digest(monkeypatch):
    update = _mock_update(chat_id=42, text="/digest")
    fake_session = MagicMock()
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=fake_session)}

    sentinel_data = object()
    build_calls = []
    monkeypatch.setattr(
        "src.telegram.bot.build_digest_data",
        lambda session, trading_day: build_calls.append((session, trading_day)) or sentinel_data,
    )
    monkeypatch.setattr(
        "src.telegram.bot.render_daily_digest",
        lambda data: "rendered" if data is sentinel_data else "wrong data",
    )

    asyncio.run(_handle_digest(update, context))

    assert build_calls == [(fake_session, datetime.date.today())]
    fake_session.close.assert_called_once()
    update.message.reply_text.assert_called_once_with("rendered")


def test_handle_digest_does_nothing_without_message():
    update = _mock_update(chat_id=42, text="/digest")
    update.message = None

    asyncio.run(_handle_digest(update, MagicMock()))


def _mock_context_with_persona(persona: MagicMock | None):
    fake_session = MagicMock()
    fake_session.scalar.return_value = persona
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=fake_session)}
    return context, fake_session


def test_handle_pause_sets_persona_inactive_in_db():
    persona = MagicMock(active=True)
    context, fake_session = _mock_context_with_persona(persona)
    update = _mock_update(chat_id=42, text="/pause VULTURE")

    asyncio.run(_handle_pause(update, context))

    assert persona.active is False
    fake_session.commit.assert_called_once()
    update.message.reply_text.assert_called_once_with("VULTURE pausiert.")


def test_handle_pause_replies_with_usage_on_invalid_input():
    update = _mock_update(chat_id=42, text="/pause")

    asyncio.run(_handle_pause(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("Usage: /pause <PERSONA>")


def test_handle_pause_reports_failure_when_persona_missing_from_db():
    context, _fake_session = _mock_context_with_persona(None)
    update = _mock_update(chat_id=42, text="/pause VULTURE")

    asyncio.run(_handle_pause(update, context))

    update.message.reply_text.assert_called_once_with(
        "VULTURE: Pausieren fehlgeschlagen (nicht in der DB)."
    )


def test_handle_resume_sets_persona_active_in_db():
    persona = MagicMock(active=False)
    context, fake_session = _mock_context_with_persona(persona)
    update = _mock_update(chat_id=42, text="/resume GUARDIAN")

    asyncio.run(_handle_resume(update, context))

    assert persona.active is True
    fake_session.commit.assert_called_once()
    update.message.reply_text.assert_called_once_with("GUARDIAN fortgesetzt.")


def test_handle_resume_replies_with_usage_on_invalid_input():
    update = _mock_update(chat_id=42, text="/resume")

    asyncio.run(_handle_resume(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("Usage: /resume <PERSONA>")


def test_handle_resume_reports_failure_when_persona_missing_from_db():
    context, _fake_session = _mock_context_with_persona(None)
    update = _mock_update(chat_id=42, text="/resume GUARDIAN")

    asyncio.run(_handle_resume(update, context))

    update.message.reply_text.assert_called_once_with(
        "GUARDIAN: Fortsetzen fehlgeschlagen (nicht in der DB)."
    )


def test_handle_pause_does_nothing_without_message_text():
    update = _mock_update(chat_id=42, text=None)

    asyncio.run(_handle_pause(update, MagicMock()))

    update.message.reply_text.assert_not_called()


def test_handle_resume_does_nothing_without_message_text():
    update = _mock_update(chat_id=42, text=None)

    asyncio.run(_handle_resume(update, MagicMock()))

    update.message.reply_text.assert_not_called()


def test_handle_hitl_replies_with_activation_state():
    update = _mock_update(chat_id=42, text="/hitl on")

    asyncio.run(_handle_hitl(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("HITL aktiviert.")


def test_handle_hitl_replies_with_usage_on_invalid_input():
    update = _mock_update(chat_id=42, text="/hitl maybe")

    asyncio.run(_handle_hitl(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("Usage: /hitl on|off")


def test_handle_hitl_does_nothing_without_message_text():
    update = _mock_update(chat_id=42, text=None)

    asyncio.run(_handle_hitl(update, MagicMock()))

    update.message.reply_text.assert_not_called()


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
        persona_name="VULTURE",
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
        lambda _session, _decision_id: (fake_decision, MagicMock(), "VULTURE"),
    )
    monkeypatch.setattr("src.telegram.bot.decision_to_hitl_request", lambda _d, _c, _p: request)
    monkeypatch.setattr("src.telegram.bot.process_callback", lambda _r, _d, _n: outcome)
    monkeypatch.setattr("src.telegram.bot.apply_hitl_outcome", lambda *_args: None)

    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=fake_session)}

    asyncio.run(_handle_hitl_callback(update, context))

    fake_session.commit.assert_called_once()
    fake_session.close.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once_with(
        "✅ Freigabe erteilt: VULTURE — MSFT."
    )


def test_handle_hitl_callback_resumes_the_paused_graph_run(monkeypatch):
    # This is the actual mechanism that turns a Telegram button press into a
    # resumed LangGraph interrupt() — and therefore, eventually, a placed order
    # (F022 §2). A HITL callback that updates the DB but never resumes the graph
    # would leave the decision APPROVED with no order ever placed (exactly the
    # class of bug F050's retry_stuck_decisions sweep exists to recover from).
    request = HitlRequest(
        decision_id=_DECISION_ID,
        persona_name="VULTURE",
        instrument="MSFT",
        thesis_text="Momentum",
        amount_usd=1200.0,
        stop_loss_price=100.0,
        created_at=_CREATED_AT,
    )
    outcome = HitlOutcome(decision=HitlDecision.APPROVED, decided_by="user")
    fake_decision = MagicMock(instrument="MSFT", hitl={"thread_id": "t1", "interrupt_id": "i1"})
    fake_session = MagicMock()
    fake_graph = MagicMock()

    monkeypatch.setattr(
        "src.telegram.bot.load_pending_decision",
        lambda _session, _decision_id: (fake_decision, MagicMock(), "VULTURE"),
    )
    monkeypatch.setattr("src.telegram.bot.decision_to_hitl_request", lambda _d, _c, _p: request)
    monkeypatch.setattr("src.telegram.bot.process_callback", lambda _r, _d, _n: outcome)
    monkeypatch.setattr("src.telegram.bot.apply_hitl_outcome", lambda *_args: None)

    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {
        "session_factory": MagicMock(return_value=fake_session),
        "graph": fake_graph,
    }

    asyncio.run(_handle_hitl_callback(update, context))

    fake_graph.invoke.assert_called_once()
    (command,), kwargs = fake_graph.invoke.call_args
    assert command.resume == {"i1": "approved"}
    assert kwargs["config"] == {"configurable": {"thread_id": "t1"}}


def test_handle_hitl_callback_still_confirms_when_graph_resume_fails(monkeypatch):
    # F063: apply_hitl_outcome already committed the decision by the time the
    # graph resume runs — a resume failure (broker hiccup, DB blip) must not
    # leave the user staring at the original "Freigabe erforderlich" message
    # with no idea whether their click had any effect. F050's retry sweep picks
    # up the DB-side approval either way.
    request = HitlRequest(
        decision_id=_DECISION_ID,
        persona_name="VULTURE",
        instrument="MSFT",
        thesis_text="Momentum",
        amount_usd=1200.0,
        stop_loss_price=100.0,
        created_at=_CREATED_AT,
    )
    outcome = HitlOutcome(decision=HitlDecision.APPROVED, decided_by="user")
    fake_decision = MagicMock(instrument="MSFT", hitl={"thread_id": "t1", "interrupt_id": "i1"})
    fake_session = MagicMock()
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = RuntimeError("checkpointer unavailable")

    monkeypatch.setattr(
        "src.telegram.bot.load_pending_decision",
        lambda _session, _decision_id: (fake_decision, MagicMock(), "VULTURE"),
    )
    monkeypatch.setattr("src.telegram.bot.decision_to_hitl_request", lambda _d, _c, _p: request)
    monkeypatch.setattr("src.telegram.bot.process_callback", lambda _r, _d, _n: outcome)
    monkeypatch.setattr("src.telegram.bot.apply_hitl_outcome", lambda *_args: None)

    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {
        "session_factory": MagicMock(return_value=fake_session),
        "graph": fake_graph,
    }

    asyncio.run(_handle_hitl_callback(update, context))

    fake_session.commit.assert_called_once()
    update.callback_query.edit_message_text.assert_called_once_with(
        "✅ Freigabe erteilt: VULTURE — MSFT."
    )


def test_handle_hitl_callback_ignores_update_without_callback_data():
    update = MagicMock()
    update.callback_query = None

    asyncio.run(_handle_hitl_callback(update, MagicMock()))
    # No exception, nothing to assert on a bare MagicMock beyond "didn't crash"
    # — parity with the "query is None" early return.


def test_handle_hitl_callback_rejects_malformed_callback_data():
    update = _mock_callback_update(chat_id=42, callback_data="not-a-valid-payload")
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=MagicMock())}

    asyncio.run(_handle_hitl_callback(update, context))

    update.callback_query.edit_message_text.assert_called_once_with("Ungültige Anfrage.")


def test_handle_hitl_callback_reports_unknown_or_already_handled_decision(monkeypatch):
    monkeypatch.setattr(
        "src.telegram.bot.load_pending_decision", lambda _session, _decision_id: None
    )

    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=MagicMock())}

    asyncio.run(_handle_hitl_callback(update, context))

    update.callback_query.edit_message_text.assert_called_once_with(
        "Unbekannte oder bereits bearbeitete Anfrage."
    )


def test_handle_hitl_callback_rejects_decision_id_mismatch(monkeypatch):
    # process_callback raises ValueError when the callback's decision id doesn't
    # match the loaded decision's — e.g. a stale button from a different message.
    request = HitlRequest(
        decision_id=uuid.uuid4(),
        persona_name="VULTURE",
        instrument="MSFT",
        thesis_text="x",
        amount_usd=1.0,
        stop_loss_price=1.0,
        created_at=_CREATED_AT,
    )
    fake_decision = MagicMock(instrument="MSFT")
    fake_session = MagicMock()

    monkeypatch.setattr(
        "src.telegram.bot.load_pending_decision",
        lambda _session, _decision_id: (fake_decision, MagicMock(), "VULTURE"),
    )
    monkeypatch.setattr("src.telegram.bot.decision_to_hitl_request", lambda _d, _c, _p: request)

    update = _mock_callback_update(chat_id=42, callback_data=f"hitl:approve:{_DECISION_ID}")
    context = MagicMock()
    context.application.bot_data = {"session_factory": MagicMock(return_value=fake_session)}

    asyncio.run(_handle_hitl_callback(update, context))

    update.callback_query.edit_message_text.assert_called_once_with("Ungültige Anfrage.")
    fake_session.close.assert_called_once()
