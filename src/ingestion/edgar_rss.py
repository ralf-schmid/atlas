"""EDGAR-RSS filings ingestion into `edgar_filing` — see docs/features/F009-edgar-rss.md.

Idempotent: upsert on the `accession_number` unique constraint (an accession number
never changes once assigned by EDGAR), so re-polling the same feed window never
creates duplicates.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

import httpx
import yaml
from defusedxml import ElementTree
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import EdgarFiling

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_ACCESSION_RE = re.compile(r"accession-number=([\d-]+)")
_TITLE_RE = re.compile(r"^(?P<form>\S+)\s+-\s+(?P<name>.+?)\s+\((?P<cik>\d+)\)")


@dataclass(frozen=True, slots=True)
class Filing:
    accession_number: str
    cik: str | None
    company_name: str
    form_type: str
    filed_at: datetime.datetime
    title: str
    link: str
    summary: str


class EdgarFeedProvider(Protocol):
    def fetch_current_filings(self, form_type: str | None = None) -> list[Filing]: ...


class HttpEdgarFeedProvider:
    """Fetches SEC EDGAR's "current filings" Atom feed.

    SEC requires a descriptive `User-Agent` (name + contact) on automated requests —
    see https://www.sec.gov/os/webmaster-faq#developers. `user_agent` must be Ralf's
    real contact string before this runs against the live feed.
    """

    def __init__(self, feed_url: str, user_agent: str) -> None:
        self._feed_url = feed_url
        self._user_agent = user_agent

    def fetch_current_filings(self, form_type: str | None = None) -> list[Filing]:
        """`form_type` filters the feed server-side (F044) — the unfiltered feed is
        the whole SEC's firehose (structured-note prospectuses, fund reports, ...),
        which drowned out the 8-K/insider-filing signal the personas actually use.
        SEC's `type=` param only exact-matches one form per request, so callers that
        want several types issue one call per type (see `run_current_filings_sync`)."""
        url = self._feed_url
        if form_type is not None:
            url = f"{url}&type={quote_plus(form_type)}"
        response = httpx.get(url, headers={"User-Agent": self._user_agent}, timeout=10.0)
        response.raise_for_status()
        return parse_atom_feed(response.text)


def parse_atom_feed(xml_text: str) -> list[Filing]:
    """Uses `defusedxml` rather than stdlib `xml.etree.ElementTree` — this feed is
    external, untrusted content (Invariant #9), and stdlib XML parsing is vulnerable
    to XXE/billion-laughs by default."""
    root = ElementTree.fromstring(xml_text)
    filings: list[Filing] = []

    for entry in root.findall("atom:entry", _ATOM_NS):
        id_text = entry.findtext("atom:id", default="", namespaces=_ATOM_NS)
        accession_match = _ACCESSION_RE.search(id_text)
        updated_text = entry.findtext("atom:updated", default="", namespaces=_ATOM_NS)
        if accession_match is None or not updated_text:
            continue

        title = entry.findtext("atom:title", default="", namespaces=_ATOM_NS)
        title_match = _TITLE_RE.match(title)
        form_type = title_match.group("form") if title_match else ""
        company_name = title_match.group("name") if title_match else title
        cik = title_match.group("cik") if title_match else None

        link_el = entry.find("atom:link", _ATOM_NS)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = entry.findtext("atom:summary", default="", namespaces=_ATOM_NS)

        filings.append(
            Filing(
                accession_number=accession_match.group(1),
                cik=cik,
                company_name=company_name,
                form_type=form_type,
                filed_at=datetime.datetime.fromisoformat(updated_text).replace(tzinfo=None),
                title=title,
                link=link,
                summary=summary,
            )
        )

    return filings


def sync_edgar_filings(session: Session, filings: list[Filing]) -> int:
    """Upserts `filings`. Returns the number of newly inserted rows (updates to an
    already-known accession number don't count — filings are immutable once filed,
    only feed-window overlap causes re-delivery)."""
    if not filings:
        return 0

    rows = [
        {
            "accession_number": f.accession_number,
            "cik": f.cik,
            "company_name": f.company_name,
            "form_type": f.form_type,
            "filed_at": f.filed_at,
            "title": f.title,
            "link": f.link,
            "summary": f.summary,
        }
        for f in filings
    ]

    insert_stmt = insert(EdgarFiling).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["accession_number"]).returning(
        EdgarFiling.id
    )
    result = session.execute(upsert_stmt)
    inserted = len(result.fetchall())
    session.flush()
    return inserted


def run_current_filings_sync(
    session: Session,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point, mirrors `market_data_sync.run_daily_sync`. Wired
    into the ingestion scheduler (F035, `src/ingestion/scheduler.py`)."""
    config = yaml.safe_load(config_path.read_text())
    edgar_config = config["edgar"]

    user_agent = _require_env(edgar_config["user_agent_env"])
    provider = HttpEdgarFeedProvider(feed_url=edgar_config["feed_url"], user_agent=user_agent)

    form_types: list[str] | None = edgar_config.get("form_types")
    if form_types:
        filings = _fetch_filtered_filings(provider, form_types)
    else:
        filings = provider.fetch_current_filings()
    return sync_edgar_filings(session, filings)


def _fetch_filtered_filings(provider: EdgarFeedProvider, form_types: list[str]) -> list[Filing]:
    """One feed request per configured type, then an exact form_type post-filter:
    SEC's `type=` param matches by *prefix* (live-observed: type=4 also returned
    424B2/485BXT/497K), so the server-side param only narrows the feed — the
    whitelist is enforced here. Deduped by `accession_number` against overlapping
    prefix results (e.g. type=4 and type=4/A both returning a 4/A filing)."""
    filings: list[Filing] = []
    seen: set[str] = set()
    for form_type in form_types:
        for filing in provider.fetch_current_filings(form_type=form_type):
            if filing.form_type == form_type and filing.accession_number not in seen:
                seen.add(filing.accession_number)
                filings.append(filing)
    return filings


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
