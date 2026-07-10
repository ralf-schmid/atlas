import datetime
from unittest.mock import patch

import httpx
import pytest

from src.ingestion.yahoo_finance_news import (
    Headline,
    HttpYahooFinanceFeedProvider,
    parse_rss_feed,
    run_market_news_sync,
    sync_market_news_headlines,
)

_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:media="http://search.yahoo.com/mrss/" version="2.0"><channel>
<title>Yahoo Finance</title>
<item>
<title>Fed minutes expose deep divide over interest-rate outlook</title>
<link>https://finance.yahoo.com/economy/policy/articles/fed-minutes-141700465.html</link>
<pubDate>2026-07-09T14:17:00Z</pubDate>
<source url="https://www.thestreet.com/">TheStreet</source>
<guid isPermaLink="false">fed-minutes-expose-deep-divide-141700465.html</guid>
</item>
<item>
<title>Evercore ISI Raises its Price Target on Twist Bioscience (TWST)</title>
<link>https://finance.yahoo.com/markets/stocks/articles/evercore-isi-103815950.html</link>
<pubDate>2026-07-09T10:38:15Z</pubDate>
<source url="http://www.insidermonkey.com">Insider Monkey</source>
<guid isPermaLink="false">evercore-isi-raises-price-target-103815950.html</guid>
</item>
</channel></rss>
"""

_MALFORMED_ITEM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
<title>No guid or pubDate here</title>
</item>
</channel></rss>
"""


def test_parse_rss_feed_extracts_headlines():
    headlines = parse_rss_feed(_SAMPLE_FEED)

    assert headlines == [
        Headline(
            guid="fed-minutes-expose-deep-divide-141700465.html",
            title="Fed minutes expose deep divide over interest-rate outlook",
            url="https://finance.yahoo.com/economy/policy/articles/fed-minutes-141700465.html",
            source="TheStreet",
            published_at=datetime.datetime(2026, 7, 9, 14, 17, 0),
        ),
        Headline(
            guid="evercore-isi-raises-price-target-103815950.html",
            title="Evercore ISI Raises its Price Target on Twist Bioscience (TWST)",
            url="https://finance.yahoo.com/markets/stocks/articles/evercore-isi-103815950.html",
            source="Insider Monkey",
            published_at=datetime.datetime(2026, 7, 9, 10, 38, 15),
        ),
    ]


def test_parse_rss_feed_skips_items_without_guid_or_pub_date():
    headlines = parse_rss_feed(_MALFORMED_ITEM_FEED)
    assert headlines == []


def test_http_yahoo_finance_feed_provider_sends_user_agent():
    with patch("src.ingestion.yahoo_finance_news.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=_SAMPLE_FEED, request=httpx.Request("GET", "https://finance.yahoo.com/feed")
        )

        provider = HttpYahooFinanceFeedProvider(feed_url="https://finance.yahoo.com/feed")
        headlines = provider.fetch_headlines()

        mock_get.assert_called_once_with(
            "https://finance.yahoo.com/feed",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10.0,
        )
        assert len(headlines) == 2


def test_http_yahoo_finance_feed_provider_raises_on_http_error():
    with patch("src.ingestion.yahoo_finance_news.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            503, request=httpx.Request("GET", "https://finance.yahoo.com/feed")
        )

        provider = HttpYahooFinanceFeedProvider(feed_url="https://finance.yahoo.com/feed")
        with pytest.raises(httpx.HTTPStatusError):
            provider.fetch_headlines()


def test_sync_market_news_headlines_returns_zero_for_empty_list(session):
    assert sync_market_news_headlines(session, []) == 0


def test_sync_market_news_headlines_inserts_new_headlines(session):
    headlines = parse_rss_feed(_SAMPLE_FEED)
    count = sync_market_news_headlines(session, headlines)
    assert count == 2

    from sqlalchemy import select

    from src.db.models import MarketNewsHeadline

    rows = session.scalars(select(MarketNewsHeadline)).all()
    assert {row.guid for row in rows} == {
        "fed-minutes-expose-deep-divide-141700465.html",
        "evercore-isi-raises-price-target-103815950.html",
    }


def test_sync_market_news_headlines_is_idempotent_on_rerun(session):
    headlines = parse_rss_feed(_SAMPLE_FEED)
    first_count = sync_market_news_headlines(session, headlines)
    second_count = sync_market_news_headlines(session, headlines)

    assert first_count == 2
    assert second_count == 0

    from sqlalchemy import select

    from src.db.models import MarketNewsHeadline

    rows = session.scalars(select(MarketNewsHeadline)).all()
    assert len(rows) == 2


def test_run_market_news_sync_reads_config(session, tmp_path):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text("market_news:\n  feed_url: https://finance.yahoo.com/feed\n")

    with patch("src.ingestion.yahoo_finance_news.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=_SAMPLE_FEED, request=httpx.Request("GET", "https://finance.yahoo.com/feed")
        )
        count = run_market_news_sync(session, config_path=config_path)

    assert count == 2
