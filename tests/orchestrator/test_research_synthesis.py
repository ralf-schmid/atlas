"""See docs/features/F017-shared-research-synthesis.md §3."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import (
    AktienfinderSnapshot,
    Cycle,
    EdgarFiling,
    MarketSession,
    MusterdepotTransaction,
    PublicationArticle,
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
