"""Webhooks for n8n's mail-triggered ingestion. See F013/F014/F078/F102.

n8n (a separate, existing instance — not part of this docker-compose stack) watches
Ralf's mailbox and POSTs the relevant fields here. Three notification types share the
mailbox but differ in sender/subject/payload:

- "Neuer Inhalt - ..." (F013, extended by F078): identifies the magazine, then
  downloads the new issue and ingests it — the Telegram prompt to place the PDF by
  hand is now only the failure path (ARCHITECTURE.md §3.5.1).
- "Neue Transaktion" (F014): DER AKTIONÄR's own Musterdepot buy/sell postings —
  parsed, persisted, and alerted purely as external research information. Never
  triggers an ATLAS order (Invariant #2/#3).
- Crypto-Boersenbrief (F102): a subscribed daily newsletter, split into individual
  impulses. Matched on sender, not subject — its subject changes every issue.

All three share one webhook secret (`N8N_PUBLICATIONS_WEBHOOK_SECRET`).
"""

from __future__ import annotations

import datetime
import functools
import logging
import os
import secrets
from pathlib import Path

import anyio
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.routes import get_session
from src.db.base import get_session_factory
from src.ingestion.crypto_newsletter import (
    extract_issue_url,
    identify_newsletter,
    load_newsletters,
    parse_newsletter,
    sync_newsletter_items,
)
from src.ingestion.musterdepot_transactions import (
    format_transaction_alert,
    parse_transactions,
    sync_musterdepot_transactions,
)
from src.ingestion.publications_download import (
    format_download_success,
    run_auto_download_live,
)
from src.ingestion.publications_notify import (
    Magazine,
    format_fallback_alert,
    identify_magazine,
    load_magazines,
)
from src.ingestion.publications_pipeline import process_pdf_fallback_file
from src.telegram.alerts import send_alert
from src.telegram.config import load_config as load_telegram_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingestion")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


class PublicationNotification(BaseModel):
    subject: str


class MusterdepotNotification(BaseModel):
    subject: str
    message_id: str
    body_text: str
    received_at: datetime.datetime | None = None


class NewsletterNotification(BaseModel):
    """F102. `sender` instead of a subject keyword: every issue has a different
    subject (the day's top story), the From address is the stable identifier.
    `body_text` must be the mail's **text/plain** part — see crypto_newsletter."""

    sender: str
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


def _auto_download_enabled(config_path: Path = _CONFIG_PATH) -> bool:
    """F078 §6 rollback switch: off means the webhook behaves exactly like F013."""
    config = yaml.safe_load(config_path.read_text())
    return bool(config["publications"].get("auto_download", False))


async def _download_and_ingest(magazine: Magazine, subject: str) -> None:
    """F078: pull the new issue, run it through the F011/F038 article pipeline, and
    report. Every failure funnels into F013's manual prompt, carrying the reason —
    the worst case of this feature is exactly the old normal case.

    Playwright's sync API can't run on the event loop, hence `to_thread`."""
    base_dir = Path(_require_env("PUBLICATIONS_INGEST_DIR"))
    telegram_config = load_telegram_config()
    try:
        session_state = Path(_require_env("BOERSENMEDIEN_SESSION_STATE"))
        result = await anyio.to_thread.run_sync(
            functools.partial(run_auto_download_live, magazine, base_dir, session_state)
        )
        session_factory = get_session_factory()
        with session_factory() as session:
            article_count = process_pdf_fallback_file(session, base_dir, result.pdf_path)
            session.commit()
    except Exception as exc:
        logger.exception("Auto-download failed for %s", magazine.slug)
        await send_alert(
            telegram_config,
            format_fallback_alert(magazine, subject, base_dir, reason=str(exc)),
        )
        return

    logger.info(
        "Auto-downloaded %s (%s), %d article(s) synced",
        magazine.slug,
        result.issue_label,
        article_count,
    )
    await send_alert(telegram_config, format_download_success(result, article_count))


@router.post("/publications/notify", status_code=202)
async def notify_publication(
    body: PublicationNotification,
    background_tasks: BackgroundTasks,
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

    if not _auto_download_enabled():
        base_dir = Path(_require_env("PUBLICATIONS_INGEST_DIR"))
        await send_alert(
            load_telegram_config(), format_fallback_alert(magazine, body.subject, base_dir)
        )
        return {"publication": magazine.slug, "status": "alert_sent"}

    # Answer n8n immediately — a browser download runs far longer than a webhook
    # caller should be kept waiting, and a timeout there would trigger a retry.
    background_tasks.add_task(_download_and_ingest, magazine, body.subject)
    return {"publication": magazine.slug, "status": "download_started"}


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


@router.post("/newsletter/notify", status_code=202)
async def notify_newsletter(
    body: NewsletterNotification,
    x_webhook_secret: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """F102: a subscribed crypto newsletter issue -> `newsletter_item` rows.

    No Telegram alert, unlike the Musterdepot branch: this arrives daily and is
    ordinary research, not a counterparty trading signal Ralf needs to see at once.

    Returns 200-with-zero rather than an error when an issue parses to nothing —
    a pure-ad issue or a layout change is a monitoring concern (the row count is
    visible in Grafana), not a reason to make n8n retry a mail that will parse the
    same way every time.
    """
    _check_webhook_secret(x_webhook_secret)

    newsletter = identify_newsletter(body.sender, load_newsletters())
    if newsletter is None:
        raise HTTPException(
            status_code=422,
            detail=f"Sender doesn't match any configured newsletter: {body.sender!r}",
        )

    impulses = parse_newsletter(body.body_text, newsletter)
    received_at = body.received_at or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if received_at.tzinfo is not None:
        received_at = received_at.astimezone(datetime.UTC).replace(tzinfo=None)

    written = sync_newsletter_items(
        session,
        newsletter.slug,
        body.message_id,
        body.subject,
        extract_issue_url(body.body_text),
        received_at,
        impulses,
    )
    session.commit()

    if written == 0:
        logger.warning(
            "Newsletter %s (%s) parsed to zero impulses — layout change or ad-only issue",
            newsletter.slug,
            body.subject,
        )

    return {"newsletter": newsletter.slug, "items": written, "status": "ingested"}
