"""Thin python-telegram-bot wiring. Most real logic lives in security.py/hitl.py/
commands.py/digest.py, which are pure and unit-tested without a live bot — see
docs/features/F005-telegram-bot.md.

Run as the `telegram-bot` service (F049, `scripts/run_telegram_bot.py`,
`docker-compose.yml`) — a long-lived `run_polling()` process, not started from
anywhere in the orchestrator itself.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.db.models import Persona
from src.telegram.commands import parse_hitl_command, parse_persona_command
from src.telegram.config import TelegramConfig
from src.telegram.digest import build_digest_data, render_daily_digest
from src.telegram.hitl import (
    format_outcome_message,
    make_callback_data,
    parse_callback_data,
    process_callback,
)
from src.telegram.hitl_store import (
    apply_hitl_outcome,
    decision_to_hitl_request,
    load_pending_decision,
)
from src.telegram.security import is_authorized_chat
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

_Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


def build_application(
    config: TelegramConfig,
    session_factory: sessionmaker[Session] | None = None,
    graph: CompiledStateGraph[Any, Any, Any, Any] | None = None,
) -> Application[Any, Any, Any, Any, Any, Any]:
    """`graph` is the compiled orchestrator graph (F016+), needed to resume a
    LangGraph interrupt() when a HITL approval/rejection button is pressed — see
    docs/features/F022-hitl-flow.md. Optional so bot.py stays importable/testable
    without an orchestrator (e.g. before the graph is wired up)."""
    app = Application.builder().token(config.bot_token).build()
    if session_factory is not None:
        app.bot_data["session_factory"] = session_factory
    if graph is not None:
        app.bot_data["graph"] = graph

    app.add_handler(CommandHandler("status", _make_handler(config, _handle_status)))
    app.add_handler(CommandHandler("pause", _make_handler(config, _handle_pause)))
    app.add_handler(CommandHandler("resume", _make_handler(config, _handle_resume)))
    app.add_handler(CommandHandler("hitl", _make_handler(config, _handle_hitl)))
    app.add_handler(CommandHandler("digest", _make_handler(config, _handle_digest)))
    app.add_handler(CallbackQueryHandler(_make_callback_handler(config, _handle_hitl_callback)))
    return app


def hitl_approval_keyboard(decision_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Freigeben", callback_data=make_callback_data("approve", decision_id)
                ),
                InlineKeyboardButton(
                    "❌ Ablehnen", callback_data=make_callback_data("reject", decision_id)
                ),
            ]
        ]
    )


def _make_handler(config: TelegramConfig, handler: _Handler) -> _Handler:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not is_authorized_chat(update.effective_chat.id, config):
            return
        await handler(update, context)

    return wrapped


def _make_callback_handler(config: TelegramConfig, handler: _Handler) -> _Handler:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not is_authorized_chat(update.effective_chat.id, config):
            return
        await handler(update, context)

    return wrapped


async def _handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TODO(Folgearbeit): Portfolio-Status aus der DB laden, sobald die
    # Persona/Portfolio-Zustandsmaschine existiert. commands.format_status_message()
    # ist bereits fertig und getestet.
    if update.message:
        await update.message.reply_text("Status: noch keine Portfolios konfiguriert.")


def _set_persona_active(
    session_factory: sessionmaker[Session], persona_name: str, active: bool
) -> bool:
    """Toggles `Persona.active` — the same flag `list_active_portfolios`
    (`src/orchestrator/graph.py`) filters on for the cycle fan-out, so this is a
    real pause/resume, not just cosmetic. Returns False if the persona name is
    unknown (shouldn't happen — `parse_persona_command` already validates against
    `KNOWN_PERSONAS` — but a DB/seed mismatch must not crash the handler)."""
    session = session_factory()
    try:
        persona = session.scalar(select(Persona).filter_by(name=persona_name))
        if persona is None:
            return False
        persona.active = active
        session.add(persona)
        session.commit()
        return True
    finally:
        session.close()


async def _handle_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    try:
        persona = parse_persona_command(update.message.text, "pause")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    session_factory = context.application.bot_data.get("session_factory")
    if session_factory is None or not _set_persona_active(session_factory, persona, False):
        await update.message.reply_text(f"{persona}: Pausieren fehlgeschlagen (nicht in der DB).")
        return
    await update.message.reply_text(f"{persona} pausiert.")


async def _handle_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    try:
        persona = parse_persona_command(update.message.text, "resume")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    session_factory = context.application.bot_data.get("session_factory")
    if session_factory is None or not _set_persona_active(session_factory, persona, True):
        await update.message.reply_text(f"{persona}: Fortsetzen fehlgeschlagen (nicht in der DB).")
        return
    await update.message.reply_text(f"{persona} fortgesetzt.")


async def _handle_hitl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    try:
        enabled = parse_hitl_command(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    # TODO(Folgearbeit): hitl.yaml / Config-Flag setzen.
    await update.message.reply_text(f"HITL {'aktiviert' if enabled else 'deaktiviert'}.")


async def _handle_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    session_factory = context.application.bot_data.get("session_factory")
    if session_factory is None:
        await update.message.reply_text("Digest: Datenbank nicht konfiguriert.")
        return
    session = session_factory()
    try:
        data = build_digest_data(session, datetime.date.today())
    finally:
        session.close()
    await update.message.reply_text(render_daily_digest(data))


async def _handle_hitl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return

    await query.answer()

    session_factory = context.application.bot_data.get("session_factory")
    if session_factory is None:
        await query.edit_message_text("HITL: Datenbank nicht konfiguriert.")
        return

    try:
        _, decision_id = parse_callback_data(query.data)
    except ValueError:
        await query.edit_message_text("Ungültige Anfrage.")
        return

    now = datetime.datetime.now(datetime.UTC)
    db_session: Session = session_factory()
    try:
        loaded = load_pending_decision(db_session, decision_id)
        if loaded is None:
            await query.edit_message_text("Unbekannte oder bereits bearbeitete Anfrage.")
            return

        decision, cycle, persona_name = loaded
        request = decision_to_hitl_request(decision, cycle, persona_name)
        try:
            outcome = process_callback(request, query.data, now)
        except ValueError:
            await query.edit_message_text("Ungültige Anfrage.")
            return

        apply_hitl_outcome(db_session, decision, outcome, now)
        db_session.commit()
        instrument = decision.instrument
        hitl = decision.hitl or {}
        thread_id = hitl.get("thread_id")
        interrupt_id = hitl.get("interrupt_id")
    finally:
        db_session.close()

    graph = context.application.bot_data.get("graph")
    if graph is not None and thread_id and interrupt_id:
        # F063: apply_hitl_outcome above already committed the DB decision — that
        # part must not be undone by a resume failure. If the resume itself blows
        # up (broker hiccup, DB blip, anything other than the already-guarded
        # execute_decision path in _maybe_execute_decision), the decision is still
        # correctly APPROVED/REJECTED in the DB; F050's retry_stuck_decisions sweep
        # picks up any APPROVED decision that never got an order_record. What must
        # not happen is this handler silently dying here — the user would see no
        # confirmation and no error, unable to tell whether the click worked at
        # all. Same non-fatal contract as sweep_expired_hitl_decisions's own
        # graph.invoke call.
        try:
            await asyncio.to_thread(
                graph.invoke,
                Command(resume={interrupt_id: outcome.decision.value}),
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception:
            logger.error(
                "failed to resume graph after HITL callback",
                exc_info=True,
                extra={"decision_id": str(decision_id)},
            )

    await query.edit_message_text(format_outcome_message(persona_name, instrument, outcome))
