"""Read a saved `.eml` and hand it to the existing newsletter pipeline — F117.

The normal path for a newsletter issue is n8n's IMAP trigger posting to
`/ingestion/newsletter/notify`. That path has one hole: an issue that arrives
*before* its n8n branch exists is marked read by the trigger and never comes
back (F106 §6, hit on 15.08.2026 for materialscrunch and marketscrunch). This
module is the catch-up: Ralf saves the mails as `.eml`, and they go through the
very same parser and the very same idempotent upsert.

Deliberately only an *adapter*: everything after "here is the plain-text body"
is `crypto_newsletter`, unchanged. A second parser would drift from the one the
webhook uses and quietly produce a different research pool.

Untrusted content (Invariante #9): the body is publisher-written. Nothing here
executes or follows it; it travels into `newsletter_item` as tagged data exactly
as the webhook path delivers it.
"""

from __future__ import annotations

import datetime
import email
import email.policy
import email.utils
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


class EmlError(ValueError):
    """The file is not a usable newsletter mail."""


@dataclass(frozen=True, slots=True)
class ParsedMail:
    sender: str
    subject: str
    message_id: str
    body_text: str
    received_at: datetime.datetime


def parse_eml(path: Path) -> ParsedMail:
    """Extract exactly the four fields the webhook contract needs, plus the date.

    Raises `EmlError` rather than returning something half-usable: a mail without
    a text/plain part would otherwise be "ingested" as zero impulses and look like
    an ad-only issue instead of a broken input.
    """
    message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    if not isinstance(message, EmailMessage):  # pragma: no cover - policy guarantees this
        raise EmlError(f"{path.name}: not a parseable mail")

    sender = _address(message.get("From"))
    if not sender:
        raise EmlError(f"{path.name}: no From header")

    body = _plain_text_body(message)
    if not body.strip():
        raise EmlError(
            f"{path.name}: no text/plain part — the parser needs the plain-text "
            "alternative, not the HTML one (see crypto_newsletter)"
        )

    return ParsedMail(
        sender=sender,
        subject=str(message.get("Subject") or "").strip(),
        # Falling back to the filename keeps the (message_id, seq) upsert key
        # stable and unique per file, so a re-run still updates in place.
        message_id=str(message.get("Message-ID") or f"file:{path.name}").strip(),
        body_text=body,
        received_at=_received_at(message),
    )


def _address(raw: str | None) -> str:
    """`"CryptoCrunch" <cryptocrunch@m6.morningcrunch.de>` -> the bare address,
    because that is what `identify_newsletter` matches on."""
    if not raw:
        return ""
    return email.utils.parseaddr(str(raw))[1].strip().lower()


def _plain_text_body(message: EmailMessage) -> str:
    """The text/plain alternative, decoded to str.

    `get_body` walks multipart/alternative correctly and applies the declared
    charset and transfer encoding (quoted-printable is the norm for these
    newsletters), which hand-rolled part-walking regularly gets wrong.
    """
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    content = part.get_content()
    return content if isinstance(content, str) else ""


def _received_at(message: EmailMessage) -> datetime.datetime:
    """The mail's own Date header as naive UTC — the DB column is naive, and the
    ingest time would misdate an issue that is being caught up days later."""
    raw = message.get("Date")
    parsed = email.utils.parsedate_to_datetime(str(raw)) if raw else None
    if parsed is None:
        return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(datetime.UTC).replace(tzinfo=None)


def scan_eml_directory(base_dir: Path) -> list[Path]:
    """`*.eml` directly under *base_dir*, sorted for a deterministic run order."""
    if not base_dir.is_dir():
        return []
    return sorted(path for path in base_dir.glob("*.eml") if path.is_file())
