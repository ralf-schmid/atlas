"""Webhook for n8n's publications mail-trigger. See F013.

n8n (a separate, existing instance — not part of this docker-compose stack) watches
Ralf's mailbox for Boersenmedien "new issue" notifications and POSTs the subject here.
This endpoint identifies the magazine and sends the Telegram fallback prompt
(ARCHITECTURE.md §3.5.1: fallback-first, Playwright auto-download is later work).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

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


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value


@router.post("/publications/notify", status_code=202)
async def notify_publication(
    body: PublicationNotification,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, str]:
    expected_secret = _require_env("N8N_PUBLICATIONS_WEBHOOK_SECRET")
    if x_webhook_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")

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
