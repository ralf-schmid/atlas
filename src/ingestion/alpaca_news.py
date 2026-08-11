"""Alpaca news ingestion into `market_news_headline` — see
docs/features/F105-alpaca-news-und-screener.md.

The point of this source next to Yahoo's RSS (F058) is the **symbol tagging**:
Alpaca returns the tickers a story is about, so the resulting `research_item` is
findable per instrument (`search_research_pool`, F045) instead of floating in the
pool untagged.

Headline metadata only — `include_content=False` keeps the article body out of the
system entirely (Invariant #9, and CLAUDE.md's "no third-party full text in repo or
UI"). Idempotent: upsert on the `guid` unique constraint (`alpaca:<news id>`).
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from alpaca.data.historical.news import NewsClient
from alpaca.data.models.news import NewsSet
from alpaca.data.requests import NewsRequest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import MarketNewsHeadline

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
_GUID_PREFIX = "alpaca:"


@dataclass(frozen=True, slots=True)
class NewsHeadline:
    guid: str
    title: str
    url: str
    source: str
    instruments: list[str]
    published_at: datetime.datetime


class NewsProvider(Protocol):
    def fetch_news(self, limit: int) -> list[NewsHeadline]: ...


class AlpacaNewsProvider:
    """Same shared market-data key as every other Alpaca source — one pool for all
    personas (Invariant #10)."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = NewsClient(api_key, secret_key)

    def fetch_news(self, limit: int) -> list[NewsHeadline]:
        news_set = self._client.get_news(
            NewsRequest(
                limit=limit,
                # No `symbols` filter: the universe runs to a few hundred tickers on
                # any given day and packing all of them into one query would be a
                # fragile, enormous URL. The unfiltered feed carries the same
                # stories including their `symbols` tagging (F105 §2).
                include_content=False,
                exclude_contentless=True,
            )
        )
        assert isinstance(news_set, NewsSet)
        headlines = []
        for item in news_set.data.get("news", []):
            url = getattr(item, "url", None)
            headlines.append(
                NewsHeadline(
                    guid=f"{_GUID_PREFIX}{item.id}",
                    title=item.headline,
                    url=url or "",
                    source=item.source or "alpaca",
                    instruments=list(item.symbols or []),
                    published_at=item.created_at.replace(tzinfo=None),
                )
            )
        return headlines


def sync_news_headlines(session: Session, headlines: list[NewsHeadline]) -> int:
    """Upserts `headlines` and returns the number of rows written."""
    if not headlines:
        return 0

    rows = [
        {
            "guid": headline.guid,
            "title": headline.title,
            "url": headline.url,
            "source": headline.source,
            "instruments": headline.instruments,
            "published_at": headline.published_at,
        }
        for headline in headlines
    ]
    stmt = insert(MarketNewsHeadline).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["guid"],
        set_={
            "title": stmt.excluded.title,
            "url": stmt.excluded.url,
            "source": stmt.excluded.source,
            "instruments": stmt.excluded.instruments,
            "published_at": stmt.excluded.published_at,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def run_alpaca_news_sync(
    session: Session,
    config_path: Path = _DEFAULT_CONFIG_PATH,
    provider: NewsProvider | None = None,
) -> int:
    config = yaml.safe_load(config_path.read_text())["alpaca_news"]
    if provider is None:
        provider = AlpacaNewsProvider(
            api_key=_require_env(config["key_id_env"]),
            secret_key=_require_env(config["secret_key_env"]),
        )
    # F105 §2: the cost guard for this source is the row count — every extra
    # research_item shows up in six persona prompts per cycle.
    limit = int(config.get("limit", 50))
    return sync_news_headlines(session, provider.fetch_news(limit))


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
