"""See docs/features/F045-persona-search-tool.md §3."""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from src.db.models import Cycle, MarketSession, ResearchItem
from src.orchestrator.graph import create_cycle
from src.orchestrator.research_search import search_research_pool


def _make_cycle_at(session: Session, started_at: datetime.datetime, seq: int = 1) -> Cycle:
    cycle = create_cycle(session, started_at.date(), seq, MarketSession.US_EQUITY)
    cycle.started_at = started_at
    session.flush()
    return cycle


def _add_item(
    session: Session,
    cycle_id,
    *,
    source_type: str = "aktienfinder_blog",
    summary: str = "some summary",
    instruments: list[str] | None = None,
    published_at: datetime.datetime | None = None,
    raw: dict[str, object] | None = None,
) -> ResearchItem:
    item = ResearchItem(
        cycle_id=cycle_id,
        agent="news_research",
        source_type=source_type,
        source_ref="ref",
        summary=summary,
        instruments=instruments or [],
        published_at=published_at,
        raw=raw or {},
    )
    session.add(item)
    session.flush()
    return item


def test_filters_by_symbol_overlap(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    match = _add_item(session, cycle.id, instruments=["AAPL"])
    _add_item(session, cycle.id, instruments=["MSFT"])
    session.flush()

    results = search_research_pool(
        session, as_of=cycle.started_at, symbols=["AAPL"], keyword=None, source_types=None
    )

    assert [r["id"] for r in results] == [str(match.id)]


def test_filters_by_keyword_in_summary(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    match = _add_item(session, cycle.id, summary="Kaufenswerte Aktie: SAP mit starkem Ausblick")
    _add_item(session, cycle.id, summary="unrelated content")
    session.flush()

    results = search_research_pool(
        session, as_of=cycle.started_at, symbols=None, keyword="Kaufenswerte", source_types=None
    )

    assert [r["id"] for r in results] == [str(match.id)]


def test_filters_by_source_types(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    match = _add_item(session, cycle.id, source_type="aktienfinder_snapshot", instruments=["AAPL"])
    _add_item(session, cycle.id, source_type="edgar_filing", instruments=["AAPL"])
    session.flush()

    results = search_research_pool(
        session,
        as_of=cycle.started_at,
        symbols=["AAPL"],
        keyword=None,
        source_types=["aktienfinder_snapshot"],
    )

    assert [r["id"] for r in results] == [str(match.id)]


def test_excludes_items_from_cycles_after_as_of(session: Session) -> None:
    """No look-ahead: a persona must never search up data from a cycle that
    (chronologically) hasn't happened yet."""
    earlier_cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 6, 10, 0), seq=1)
    later_cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 8, 10, 0), seq=2)
    past_item = _add_item(session, earlier_cycle.id, instruments=["AAPL"])
    _add_item(session, later_cycle.id, instruments=["AAPL"])
    session.flush()

    results = search_research_pool(
        session,
        as_of=earlier_cycle.started_at,
        symbols=["AAPL"],
        keyword=None,
        source_types=None,
    )

    assert [r["id"] for r in results] == [str(past_item.id)]


def test_includes_current_cycle_items(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    item = _add_item(session, cycle.id, instruments=["AAPL"])
    session.flush()

    results = search_research_pool(
        session, as_of=cycle.started_at, symbols=["AAPL"], keyword=None, source_types=None
    )

    assert [r["id"] for r in results] == [str(item.id)]


def test_caps_result_count(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    for _ in range(15):
        _add_item(session, cycle.id, instruments=["AAPL"])
    session.flush()

    results = search_research_pool(
        session, as_of=cycle.started_at, symbols=["AAPL"], keyword=None, source_types=None
    )

    assert len(results) == 10


def test_caps_text_excerpt_length_in_raw(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    long_excerpt = "x" * 1000
    _add_item(session, cycle.id, instruments=["AAPL"], raw={"text_excerpt": long_excerpt})
    session.flush()

    results = search_research_pool(
        session, as_of=cycle.started_at, symbols=["AAPL"], keyword=None, source_types=None
    )

    assert len(results[0]["raw"]["text_excerpt"]) < 1000
    assert results[0]["raw"]["text_excerpt"].endswith("…")


def test_serializes_expected_fields(session: Session) -> None:
    cycle = _make_cycle_at(session, datetime.datetime(2026, 7, 7, 10, 0))
    published = datetime.datetime(2026, 7, 6, 9, 0)
    item = _add_item(
        session,
        cycle.id,
        source_type="aktienfinder_blog",
        summary="a real summary",
        instruments=["AAPL"],
        published_at=published,
        raw={"categories": ["dividende"]},
    )
    session.flush()

    results = search_research_pool(
        session, as_of=cycle.started_at, symbols=["AAPL"], keyword=None, source_types=None
    )

    assert results == [
        {
            "id": str(item.id),
            "source_type": "aktienfinder_blog",
            "published_at": "2026-07-06T09:00:00",
            "summary": "a real summary",
            "instruments": ["AAPL"],
            "raw": {"categories": ["dividende"]},
        }
    ]
