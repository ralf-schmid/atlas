"""Publications mail-notification -> Telegram fallback prompt.

See docs/features/F013-publications-mail-trigger.md. Pure logic only: identifying
which magazine a notification mail is about, and rendering the Telegram fallback
message. The actual "an IMAP mail arrived" detection happens in n8n (a separate,
existing instance, see ARCHITECTURE.md "n8n: bestehende Instanz") — n8n calls the
FastAPI webhook (src/api/routes_ingestion.py), which uses this module.

Fallback-first (ARCHITECTURE.md §3.5.1): this only ever produces a Telegram prompt
asking Ralf to drop the PDF manually — the Playwright auto-download is later work.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


@dataclass(frozen=True, slots=True)
class Magazine:
    slug: str
    subject_keyword: str
    overview_url: str


def load_magazines(config_path: Path = _DEFAULT_CONFIG_PATH) -> list[Magazine]:
    config = yaml.safe_load(config_path.read_text())
    return [
        Magazine(
            slug=m["slug"], subject_keyword=m["subject_keyword"], overview_url=m["overview_url"]
        )
        for m in config["publications"]["magazines"]
    ]


def identify_magazine(subject: str, magazines: list[Magazine]) -> Magazine | None:
    """Matches a mail subject (e.g. "Neuer Inhalt - Euro am Sonntag 23/26") against
    the configured magazines by case-insensitive substring — subjects for the two
    "E-Paper" magazines are constant, Euro am Sonntag's carries a changing issue
    number, so exact/prefix matching would miss it."""
    subject_lower = subject.lower()
    for magazine in magazines:
        if magazine.subject_keyword.lower() in subject_lower:
            return magazine
    return None


def format_fallback_alert(
    magazine: Magazine,
    subject: str,
    base_dir: Path,
    today: datetime.date | None = None,
) -> str:
    """Renders the Telegram message asking Ralf to manually download and drop the
    PDF — matches F011's `<base_dir>/<slug>/<YYYY-MM-DD>.pdf` convention exactly, so
    the file lands where the fallback pipeline picks it up."""
    issue_date = today or datetime.date.today()
    target_path = base_dir / magazine.slug / f"{issue_date.isoformat()}.pdf"
    return (
        f"📰 Neue Ausgabe erkannt: {subject}\n\n"
        f"Bitte PDF laden und ablegen unter:\n"
        f"{target_path}\n\n"
        f"Übersicht der Ausgaben: {magazine.overview_url}"
    )
