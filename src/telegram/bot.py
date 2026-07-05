"""Thin python-telegram-bot wiring. All real logic lives in security.py/hitl.py/
commands.py/digest.py, which are pure and unit-tested without a live bot — see
docs/features/F005-telegram-bot.md.

Not started anywhere automatically yet (no orchestrator calls this). Building
the `Application` here only requires a syntactically-shaped token string, not
a real one — connecting to Telegram (`run_polling()`) is what would need
Ralf's real TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.telegram.commands import parse_hitl_command, parse_persona_command
from src.telegram.config import TelegramConfig
from src.telegram.hitl import make_callback_data
from src.telegram.security import is_authorized_chat
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

_Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


def build_application(config: TelegramConfig) -> Application[Any, Any, Any, Any, Any, Any]:
    app = Application.builder().token(config.bot_token).build()

    app.add_handler(CommandHandler("status", _make_handler(config, _handle_status)))
    app.add_handler(CommandHandler("pause", _make_handler(config, _handle_pause)))
    app.add_handler(CommandHandler("resume", _make_handler(config, _handle_resume)))
    app.add_handler(CommandHandler("hitl", _make_handler(config, _handle_hitl)))
    app.add_handler(CommandHandler("digest", _make_handler(config, _handle_digest)))
    app.add_handler(CallbackQueryHandler(_make_callback_handler(config, _handle_hitl_callback)))
    return app


def hitl_approval_keyboard(decision_id: int) -> InlineKeyboardMarkup:
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


async def _handle_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    try:
        persona = parse_persona_command(update.message.text, "pause")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    # TODO(Folgearbeit): persona.active = False in der DB setzen.
    await update.message.reply_text(f"{persona} pausiert.")


async def _handle_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    try:
        persona = parse_persona_command(update.message.text, "resume")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    # TODO(Folgearbeit): persona.active = True in der DB setzen.
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
    # TODO(Folgearbeit): DigestData aus portfolio_snapshot/order_record/cost_ledger
    # zusammenstellen, sobald diese Snapshot-Jobs existieren. digest.render_daily_digest()
    # ist bereits fertig und getestet.
    if update.message:
        await update.message.reply_text("Digest: noch keine Snapshot-Daten verfügbar.")


async def _handle_hitl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # TODO(Folgearbeit): HitlRequest aus Persistenz laden (decision.hitl), hitl.process_callback()
    # aufrufen, Ergebnis zurückschreiben. Braucht den Handels-Agenten/eine HITL-Tabelle.
    if update.callback_query:
        await update.callback_query.answer()
