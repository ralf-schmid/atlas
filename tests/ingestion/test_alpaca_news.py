"""See docs/features/F105-alpaca-news-und-screener.md §3, tests 1-4."""

from __future__ import annotations

import datetime
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import MarketNewsHeadline
from src.ingestion.alpaca_news import (
    AlpacaNewsProvider,
    NewsHeadline,
    run_alpaca_news_sync,
    sync_news_headlines,
)


def _news(news_id: int, headline: str, symbols: list[str]):
    from alpaca.data.models.news import News

    return News.model_construct(
        id=news_id,
        headline=headline,
        source="benzinga",
        url=f"https://example.test/{news_id}",
        symbols=symbols,
        created_at=datetime.datetime(2026, 8, 11, 12, 0, tzinfo=datetime.UTC),
    )


def _news_set(items: list[object]):
    from alpaca.data.models.news import NewsSet

    return NewsSet.model_construct(data={"news": items})


def test_provider_maps_news_to_headline() -> None:
    with patch("src.ingestion.alpaca_news.NewsClient") as mock_cls:
        mock_cls.return_value.get_news.return_value = _news_set(
            [_news(42, "Apple beats estimates", ["AAPL", "MSFT"])]
        )

        provider = AlpacaNewsProvider(api_key="key", secret_key="secret")
        headlines = provider.fetch_news(limit=50)

        assert headlines == [
            NewsHeadline(
                guid="alpaca:42",
                title="Apple beats estimates",
                url="https://example.test/42",
                source="benzinga",
                instruments=["AAPL", "MSFT"],
                published_at=datetime.datetime(2026, 8, 11, 12, 0),
            )
        ]


def test_provider_requests_headlines_without_content() -> None:
    """Invariant #9 / CLAUDE.md: no third-party full text enters the system — the
    article body is never even fetched."""
    with patch("src.ingestion.alpaca_news.NewsClient") as mock_cls:
        mock_cls.return_value.get_news.return_value = _news_set([])

        AlpacaNewsProvider(api_key="key", secret_key="secret").fetch_news(limit=25)

        request = mock_cls.return_value.get_news.call_args[0][0]
        assert request.include_content is False
        assert request.exclude_contentless is True
        assert request.limit == 25


def test_sync_is_idempotent(session: Session) -> None:
    headline = NewsHeadline(
        guid="alpaca:42",
        title="Apple beats estimates",
        url="https://example.test/42",
        source="benzinga",
        instruments=["AAPL"],
        published_at=datetime.datetime(2026, 8, 11, 12, 0),
    )

    sync_news_headlines(session, [headline])
    sync_news_headlines(session, [headline])

    rows = session.scalars(select(MarketNewsHeadline)).all()
    assert len(rows) == 1
    assert rows[0].instruments == ["AAPL"]


def test_sync_respects_configured_limit(session: Session, tmp_path, monkeypatch) -> None:
    """F105 §2: the row count is this source's cost guard — the configured limit
    must reach the API call, not just the docs."""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "alpaca_news:\n"
        "  key_id_env: TEST_MD_KEY_ID\n"
        "  secret_key_env: TEST_MD_SECRET_KEY\n"
        "  limit: 7\n"
    )
    monkeypatch.setenv("TEST_MD_KEY_ID", "key")
    monkeypatch.setenv("TEST_MD_SECRET_KEY", "secret")

    with patch("src.ingestion.alpaca_news.NewsClient") as mock_cls:
        mock_cls.return_value.get_news.return_value = _news_set([])

        run_alpaca_news_sync(session, config_path=config_path)

        assert mock_cls.return_value.get_news.call_args[0][0].limit == 7
