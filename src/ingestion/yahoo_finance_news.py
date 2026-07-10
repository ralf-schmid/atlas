"""Yahoo Finance top-stories RSS ingestion into `market_news_headline` — see
docs/features/F058-market-news-analyst-source.md.

Idempotent: upsert on the `guid` unique constraint (Yahoo's feed `<guid>` is
stable per article), so re-polling the same feed window never creates
duplicates.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import yaml
from defusedxml import ElementTree
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import MarketNewsHeadline

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


@dataclass(frozen=True, slots=True)
class Headline:
    guid: str
    title: str
    url: str
    source: str
    published_at: datetime.datetime


class HeadlineFeedProvider(Protocol):
    def fetch_headlines(self) -> list[Headline]: ...


class HttpYahooFinanceFeedProvider:
    """Fetches Yahoo Finance's public top-stories RSS feed — no auth, no login,
    permitted by `robots.txt` (unlike reuters.com/markets/us/, see
    docs/features/F058)."""

    def __init__(self, feed_url: str) -> None:
        self._feed_url = feed_url

    def fetch_headlines(self) -> list[Headline]:
        response = httpx.get(self._feed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0)
        response.raise_for_status()
        return parse_rss_feed(response.text)


def parse_rss_feed(xml_text: str) -> list[Headline]:
    """Uses `defusedxml` rather than stdlib `xml.etree.ElementTree` — this feed is
    external, untrusted content (Invariant #9), and stdlib XML parsing is
    vulnerable to XXE/billion-laughs by default (same reasoning as
    `src.ingestion.edgar_rss.parse_atom_feed`)."""
    root = ElementTree.fromstring(xml_text)
    headlines: list[Headline] = []

    for item in root.findall("./channel/item"):
        guid = item.findtext("guid", default="")
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        source_el = item.find("source")
        source = source_el.text if source_el is not None and source_el.text else "Yahoo Finance"

        if not guid or not pub_date:
            continue

        headlines.append(
            Headline(
                guid=guid,
                title=title,
                url=link,
                source=source,
                published_at=_parse_pub_date(pub_date),
            )
        )

    return headlines


def _parse_pub_date(raw: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)


def sync_market_news_headlines(session: Session, headlines: list[Headline]) -> int:
    """Upserts `headlines`. Returns the number of newly inserted rows (a `guid`
    reappearing in a later poll — the feed's rolling window can overlap — doesn't
    count, same idempotency contract as `edgar_rss.sync_edgar_filings`)."""
    if not headlines:
        return 0

    rows = [
        {
            "guid": h.guid,
            "title": h.title,
            "url": h.url,
            "source": h.source,
            "published_at": h.published_at,
        }
        for h in headlines
    ]

    insert_stmt = insert(MarketNewsHeadline).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["guid"]).returning(
        MarketNewsHeadline.id
    )
    result = session.execute(upsert_stmt)
    inserted = len(result.fetchall())
    session.flush()
    return inserted


def run_market_news_sync(
    session: Session,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point, mirrors `edgar_rss.run_current_filings_sync`.
    Wired into the ingestion scheduler (`src/ingestion/scheduler.py`)."""
    config = yaml.safe_load(config_path.read_text())
    feed_url = config["market_news"]["feed_url"]

    provider = HttpYahooFinanceFeedProvider(feed_url=feed_url)
    headlines = provider.fetch_headlines()
    return sync_market_news_headlines(session, headlines)
