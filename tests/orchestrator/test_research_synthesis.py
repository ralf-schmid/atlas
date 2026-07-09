"""See docs/features/F017-shared-research-synthesis.md §3."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import (
    AktienfinderBlogPost,
    AktienfinderSnapshot,
    BtcDominanceSnapshot,
    Cycle,
    EdgarFiling,
    MarketBar,
    MarketBarTimeframe,
    MarketSession,
    MusterdepotTransaction,
    PublicationArticle,
    RedditPost,
    ScreenerResult,
)
from src.orchestrator.graph import create_cycle
from src.orchestrator.research_synthesis import synthesize_research_items

_WINDOW_START = datetime.datetime(2026, 7, 7, 8, 0, 0)
_WINDOW_END = datetime.datetime(2026, 7, 7, 9, 0, 0)
_INSIDE_WINDOW = datetime.datetime(2026, 7, 7, 8, 30, 0)
_BEFORE_WINDOW = datetime.datetime(2026, 7, 7, 7, 0, 0)
_AFTER_WINDOW = datetime.datetime(2026, 7, 7, 9, 30, 0)


def _make_cycle_at(session: Session, started_at: datetime.datetime, seq: int = 1) -> Cycle:
    cycle = create_cycle(session, started_at.date(), seq, MarketSession.US_EQUITY)
    cycle.started_at = started_at
    session.flush()
    return cycle


def _seed_all_sources(session: Session, synced_at: datetime.datetime) -> None:
    session.add(
        EdgarFiling(
            accession_number=f"ACC-{synced_at.timestamp()}",
            company_name="Test Corp",
            form_type="10-K",
            filed_at=datetime.datetime(2026, 7, 6),
            title="Annual report",
            link="https://example.invalid/filing",
            summary="raw feed summary",
            synced_at=synced_at,
        )
    )
    session.add(
        ScreenerResult(
            screened_at=datetime.date(2026, 7, 7),
            symbol="TEST",
            price=Decimal("4.20"),
            volume=Decimal("1000000"),
            synced_at=synced_at,
        )
    )
    session.add(
        PublicationArticle(
            publication="Der Aktionär",
            issue_date=datetime.date(2026, 7, 6),
            seq=1,
            page=12,
            title="Test-Artikel",
            text="Voller Artikeltext, der nicht dupliziert werden soll.",
            source_file="test.pdf",
            synced_at=synced_at,
        )
    )
    session.add(
        AktienfinderSnapshot(
            symbol="US0378331005",
            snapshot_date=datetime.date(2026, 7, 7),
            fields={"price": "200 USD", "dividend_yield": "0,5 %"},
            screenshot_path="/tmp/shot.png",
            synced_at=synced_at,
        )
    )
    session.add(
        MusterdepotTransaction(
            message_id="msg-1",
            seq=1,
            action="KAUF",
            instrument_name="Test AG",
            wkn="A1B2C3",
            quantity=Decimal("10"),
            price=Decimal("50"),
            currency="EUR",
            raw_text="Fremdtext, der nicht in research_item landen soll",
            received_at=datetime.datetime(2026, 7, 7, 8, 15),
            synced_at=synced_at,
        )
    )
    session.flush()


def test_synthesizes_one_item_per_source_inside_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    _seed_all_sources(session, _INSIDE_WINDOW)

    items = synthesize_research_items(session, cycle)

    assert len(items) == 5
    assert {item.source_type for item in items} == {
        "edgar_filing",
        "screener_result",
        "publication_article",
        "aktienfinder_snapshot",
        "musterdepot_transaction",
    }


def test_excludes_rows_synced_before_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    _seed_all_sources(session, _BEFORE_WINDOW)

    items = synthesize_research_items(session, cycle)

    assert items == []


def test_excludes_rows_synced_after_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    _seed_all_sources(session, _AFTER_WINDOW)

    items = synthesize_research_items(session, cycle)

    assert items == []


def test_edgar_filing_mapping(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    session.add(
        EdgarFiling(
            accession_number="ACC-1",
            company_name="Test Corp",
            form_type="8-K",
            filed_at=datetime.datetime(2026, 7, 6, 12, 0),
            title="Material event",
            link="https://example.invalid/8k",
            summary="raw",
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    item = items[0]
    assert item.published_at == datetime.datetime(2026, 7, 6, 12, 0)
    assert "8-K" in item.summary
    assert "Test Corp" in item.summary
    assert item.instruments == []


def test_screener_result_mapping_sets_instrument(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    session.add(
        ScreenerResult(
            screened_at=datetime.date(2026, 7, 7),
            symbol="ABCD",
            price=Decimal("3.10"),
            volume=Decimal("500000"),
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    assert items[0].instruments == ["ABCD"]


def test_publication_article_summary_excludes_full_text(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    full_text = "Dies ist der volle, sehr lange Artikeltext mit vielen Details."
    session.add(
        PublicationArticle(
            publication="Börse Online",
            issue_date=datetime.date(2026, 7, 6),
            seq=1,
            page=5,
            title="Kurzer Titel",
            text=full_text,
            source_file="test.pdf",
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    assert "Kurzer Titel" in items[0].summary
    assert full_text not in items[0].summary


def test_publication_article_raw_carries_text_excerpt_for_agents(session: Session) -> None:
    """`summary` stays metadata-only (UI/API-safe, see test above); the article body
    goes into `raw`, which only reaches the persona LLM context (F044) — the API
    (`src/api/routes.py` `ResearchRefOut`) never selects `raw`, so this doesn't
    surface Zeitschriften-Volltexte in the UI (CLAUDE.md)."""
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    full_text = "Dies ist der volle Artikeltext mit einer echten Anlage-These und Details dazu."
    session.add(
        PublicationArticle(
            publication="Börse Online",
            issue_date=datetime.date(2026, 7, 6),
            seq=1,
            page=5,
            title="Kurzer Titel",
            text=full_text,
            source_file="test.pdf",
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    assert items[0].raw["text_excerpt"] == full_text


def test_publication_article_raw_excerpt_is_truncated_for_long_articles(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    long_text = "x" * 2000
    session.add(
        PublicationArticle(
            publication="Börse Online",
            issue_date=datetime.date(2026, 7, 6),
            seq=1,
            page=5,
            title="Langer Artikel",
            text=long_text,
            source_file="test.pdf",
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    excerpt = items[0].raw["text_excerpt"]
    assert len(excerpt) < len(long_text)
    assert excerpt.endswith("…")


def test_musterdepot_transaction_mapping_excludes_raw_text(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    session.add(
        MusterdepotTransaction(
            message_id="msg-2",
            seq=1,
            action="TEILVERKAUF",
            instrument_name="Moderna",
            wkn="A2N9D9",
            quantity=Decimal("75"),
            price=Decimal("68.31"),
            currency="EUR",
            raw_text="<html>Fremdtext, potenziell feindlich</html>",
            received_at=datetime.datetime(2026, 7, 7, 8, 15),
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    item = items[0]
    assert "TEILVERKAUF" in item.summary
    assert "Moderna" in item.summary
    assert "A2N9D9" in item.summary
    assert "raw_text" not in item.raw
    assert "Fremdtext" not in item.summary


def test_bootstrap_window_used_when_no_previous_cycle(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    six_days_before = _WINDOW_END - datetime.timedelta(days=6)
    session.add(
        ScreenerResult(
            screened_at=datetime.date(2026, 7, 1),
            symbol="OLD",
            price=Decimal("1.00"),
            volume=Decimal("100"),
            synced_at=six_days_before,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    assert items[0].source_ref == "OLD"


def test_previous_cycle_of_other_market_session_is_ignored(session: Session) -> None:
    crypto_cycle = create_cycle(session, _WINDOW_START.date(), 1, MarketSession.CRYPTO)
    crypto_cycle.started_at = _WINDOW_START
    session.flush()

    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)
    six_days_before = _WINDOW_END - datetime.timedelta(days=6)
    session.add(
        ScreenerResult(
            screened_at=datetime.date(2026, 7, 1),
            symbol="IGNORE_CRYPTO_CYCLE",
            price=Decimal("1.00"),
            volume=Decimal("100"),
            synced_at=six_days_before,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert len(items) == 1
    assert items[0].source_ref == "IGNORE_CRYPTO_CYCLE"


def _seed_market_bars(session: Session, symbol: str, num_bars: int) -> None:
    start = datetime.datetime(2026, 1, 1)
    for i in range(num_bars):
        session.add(
            MarketBar(
                symbol=symbol,
                timeframe=MarketBarTimeframe.DAY,
                ts=start + datetime.timedelta(days=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(str(100 + i * 0.1)),
                volume=Decimal("1000000"),
            )
        )
    session.flush()


def test_technical_indicator_item_emitted_for_seed_watchlist_symbol_with_enough_bars(
    session: Session,
) -> None:
    # AAPL is part of config/ingestion.yaml's static market_data.watchlist. 50
    # bars so both SMA20 and SMA50 (and therefore the crossover check) resolve.
    _seed_market_bars(session, "AAPL", 50)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)

    items = synthesize_research_items(session, cycle)

    indicator_items = [item for item in items if item.source_type == "technical_indicator"]
    assert len(indicator_items) == 1
    assert indicator_items[0].source_ref == "AAPL"
    assert indicator_items[0].instruments == ["AAPL"]
    assert indicator_items[0].published_at == cycle.started_at
    assert "SMA20" in indicator_items[0].summary
    assert "RSI14" in indicator_items[0].summary


def test_no_technical_indicator_item_when_no_market_bars_exist(session: Session) -> None:
    cycle = _make_cycle_at(session, _WINDOW_END, seq=1)

    items = synthesize_research_items(session, cycle)

    assert [item for item in items if item.source_type == "technical_indicator"] == []


def test_technical_indicator_item_not_windowed_by_synced_at(session: Session) -> None:
    """Unlike the other 5 sources, a technical-indicator item is recomputed every
    cycle regardless of when the underlying market_bar rows were synced."""
    _seed_market_bars(session, "AAPL", 20)
    first_cycle = _make_cycle_at(session, _WINDOW_START, seq=1)
    second_cycle = _make_cycle_at(session, _WINDOW_END, seq=2)

    first_items = synthesize_research_items(session, first_cycle)
    second_items = synthesize_research_items(session, second_cycle)

    assert len([i for i in first_items if i.source_type == "technical_indicator"]) == 1
    assert len([i for i in second_items if i.source_type == "technical_indicator"]) == 1


def test_btc_dominance_item_mapping_inside_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    session.add(
        BtcDominanceSnapshot(
            snapshot_at=_INSIDE_WINDOW,
            btc_dominance_pct=Decimal("54.231"),
            total_market_cap_usd=Decimal("2100000000000.00"),
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    btc_items = [item for item in items if item.source_type == "btc_dominance"]
    assert len(btc_items) == 1
    assert btc_items[0].instruments == ["BTC/USD"]
    assert "54.231" in btc_items[0].summary
    assert btc_items[0].published_at == _INSIDE_WINDOW


def test_btc_dominance_item_excluded_outside_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    session.add(
        BtcDominanceSnapshot(
            snapshot_at=_BEFORE_WINDOW,
            btc_dominance_pct=Decimal("50.0"),
            total_market_cap_usd=Decimal("2000000000000.00"),
            synced_at=_BEFORE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert [item for item in items if item.source_type == "btc_dominance"] == []


def test_reddit_post_item_mapping_inside_window_has_no_sentiment_scoring(
    session: Session,
) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    session.add(
        RedditPost(
            post_id="abc123",
            subreddit="Bitcoin",
            title="BTC breaks above 60k",
            score=4200,
            num_comments=731,
            created_utc=_INSIDE_WINDOW,
            permalink="https://reddit.com/r/Bitcoin/comments/abc123/",
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    reddit_items = [item for item in items if item.source_type == "reddit_post"]
    assert len(reddit_items) == 1
    assert reddit_items[0].source_ref == "abc123"
    assert "BTC breaks above 60k" in reddit_items[0].summary
    assert reddit_items[0].raw == {"score": 4200, "num_comments": 731}
    assert "sentiment" not in reddit_items[0].raw


def test_reddit_post_item_excluded_outside_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    session.add(
        RedditPost(
            post_id="old456",
            subreddit="Bitcoin",
            title="Old post",
            score=1,
            num_comments=0,
            created_utc=_BEFORE_WINDOW,
            permalink="https://reddit.com/r/Bitcoin/comments/old456/",
            synced_at=_BEFORE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert [item for item in items if item.source_type == "reddit_post"] == []


def test_aktienfinder_blog_item_mapping_inside_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    session.add(
        AktienfinderBlogPost(
            post_id="32176",
            title="General Mills – 7,2 % Dividende! Wird die Dividende gekürzt?",
            url="https://aktienfinder.net/blog/general-mills-72-dividende/",
            categories=["aktienanalyse"],
            tags=["aktie", "dividende", "general-mills"],
            is_premium=True,
            published_at=datetime.date(2026, 6, 11),
            synced_at=_INSIDE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    blog_items = [item for item in items if item.source_type == "aktienfinder_blog"]
    assert len(blog_items) == 1
    assert blog_items[0].source_ref == "32176"
    assert "General Mills" in blog_items[0].summary
    assert "Premium" in blog_items[0].summary
    assert blog_items[0].raw["is_premium"] is True


def test_aktienfinder_blog_item_excluded_outside_window(session: Session) -> None:
    _make_cycle_at(session, _WINDOW_START, seq=1)
    cycle = _make_cycle_at(session, _WINDOW_END, seq=2)
    session.add(
        AktienfinderBlogPost(
            post_id="old789",
            title="Old analysis",
            url="https://aktienfinder.net/blog/old-analysis/",
            categories=["aktienanalyse"],
            tags=[],
            is_premium=False,
            published_at=datetime.date(2026, 5, 1),
            synced_at=_BEFORE_WINDOW,
        )
    )
    session.flush()

    items = synthesize_research_items(session, cycle)

    assert [item for item in items if item.source_type == "aktienfinder_blog"] == []
