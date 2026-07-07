"""Webhooks for n8n's publications mail-triggers. See F013/F014.

n8n (a separate, existing instance — not part of this docker-compose stack) watches
Ralf's mailbox for Boersenmedien mail notifications and POSTs the relevant fields
here. Two notification types share the mailbox but differ in sender/subject/payload:

- "Neuer Inhalt - ..." (F013): identifies the magazine, sends a Telegram fallback
  prompt to manually download and place the PDF (ARCHITECTURE.md §3.5.1).
- "Neue Transaktion" (F014): DER AKTIONÄR's own Musterdepot buy/sell postings —
  parsed, persisted, and alerted purely as external research information. Never
  triggers an ATLAS order (Invariant #2/#3).
"""

from __future__ import annotations

import datetime
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.routes import get_session
from src.ingestion.musterdepot_transactions import (
    format_transaction_alert,
    parse_transactions,
    sync_musterdepot_transactions,
)
from src.ingestion.publications_notify import (
    format_fallback_alert,
    identify_magazine,
    load_magazines,
)
from src.telegram.alerts import send_alert
from src.telegram.config import load_config as load_telegram_config

router = APIRouter(prefix="/api/ingestion")


class PublicationNotification(BaseModel):
    subject: str


class MusterdepotNotification(BaseModel):
    subject: str
    message_id: str
    body_text: str
    received_at: datetime.datetime | None = None


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value


def _check_webhook_secret(x_webhook_secret: str | None) -> None:
    expected_secret = _require_env("N8N_PUBLICATIONS_WEBHOOK_SECRET")
    # compare_digest: constant-time comparison, no timing side channel on the secret.
    if x_webhook_secret is None or not secrets.compare_digest(x_webhook_secret, expected_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")


@router.post("/publications/notify", status_code=202)
async def notify_publication(
    body: PublicationNotification,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, str]:
    _check_webhook_secret(x_webhook_secret)

    magazines = load_magazines()
    magazine = identify_magazine(body.subject, magazines)
    if magazine is None:
        raise HTTPException(
            status_code=422,
            detail=f"Subject doesn't match any configured magazine: {body.subject!r}",
        )

    base_dir = Path(_require_env("PUBLICATIONS_INGEST_DIR"))
    message = format_fallback_alert(magazine, body.subject, base_dir)
    await send_alert(load_telegram_config(), message)

    return {"publication": magazine.slug, "status": "alert_sent"}


@router.post("/publications/musterdepot-notify", status_code=202)
async def notify_musterdepot_transaction(
    body: MusterdepotNotification,
    x_webhook_secret: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _check_webhook_secret(x_webhook_secret)

    transactions = parse_transactions(body.body_text)
    if not transactions:
        raise HTTPException(
            status_code=422,
            detail="No 'Transaktion ...' line found in body_text",
        )

    received_at = body.received_at or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    sync_musterdepot_transactions(session, body.message_id, received_at, transactions)
    session.commit()

    telegram_config = load_telegram_config()
    for transaction in transactions:
        await send_alert(telegram_config, format_transaction_alert(transaction))

    return {"transactions": len(transactions), "status": "alert_sent"}
