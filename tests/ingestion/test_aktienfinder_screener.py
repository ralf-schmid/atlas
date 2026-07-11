from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import AktienfinderScreenerCandidate
from src.ingestion.aktienfinder_screener import (
    ScreenerCandidate,
    _map_screener_grid_row,
    discover_candidates,
    sync_screener_candidates,
)


def test_map_screener_grid_row_extracts_fields_by_header_text() -> None:
    headers = ["Aktie", "Region", "Kurs", "Kursziel"]
    cells = ["ignored", "Nordamerika", "150.00", "180.00"]

    candidate = _map_screener_grid_row(
        headers, cells, isin="US1", ticker="AAA", name="A Corp", field_labels={"price": "Kurs"}
    )

    assert candidate.region == "Nordamerika"
    assert candidate.fields == {"price": "150.00"}
    assert candidate.isin == "US1"
    assert candidate.ticker == "AAA"
    assert candidate.name == "A Corp"


def test_map_screener_grid_row_unknown_field_label_returns_none() -> None:
    headers = ["Aktie", "Region", "Kurs"]
    cells = ["ignored", "Nordamerika", "150.00"]

    candidate = _map_screener_grid_row(
        headers, cells, isin="US1", ticker="AAA", name="A Corp", field_labels={"kgv": "KGV Ber."}
    )

    assert candidate.fields == {"kgv": None}


def test_map_screener_grid_row_missing_region_column_yields_empty_string() -> None:
    headers = ["Aktie", "Kurs"]
    cells = ["ignored", "150.00"]

    candidate = _map_screener_grid_row(
        headers, cells, isin="US1", ticker="AAA", name="A Corp", field_labels={}
    )

    assert candidate.region == ""


class _FakeGrid:
    """Fake `ScreenerGridPage` — each entry in `pages` is one page's rows."""

    def __init__(self, pages: list[list[ScreenerCandidate]]) -> None:
        self._pages = pages
        self._index = 0

    def read_rows(self, field_labels: dict[str, str]) -> list[ScreenerCandidate]:
        return self._pages[self._index]

    def go_to_next_page(self) -> bool:
        if self._index + 1 >= len(self._pages):
            return False
        self._index += 1
        return True


def _candidate(ticker: str, region: str = "Nordamerika") -> ScreenerCandidate:
    return ScreenerCandidate(
        isin=f"US{ticker}", ticker=ticker, name=ticker, region=region, fields={}
    )


def test_discover_candidates_stops_once_target_reached() -> None:
    grid = _FakeGrid(
        [
            [_candidate("AAA"), _candidate("BBB")],
            [_candidate("CCC"), _candidate("DDD")],
            [_candidate("EEE"), _candidate("FFF")],
        ]
    )

    result = discover_candidates(
        grid, field_labels={}, regions={"Nordamerika"}, target_candidates=3, max_pages=10
    )

    # stops after the page that first reaches >= 3 (page 1: 2, page 2: 4) — doesn't
    # truncate mid-page, so 4 candidates, not exactly 3.
    assert [c.ticker for c in result] == ["AAA", "BBB", "CCC", "DDD"]


def test_discover_candidates_respects_max_pages_even_below_target() -> None:
    grid = _FakeGrid([[_candidate("AAA")], [_candidate("BBB")], [_candidate("CCC")]])

    result = discover_candidates(
        grid, field_labels={}, regions={"Nordamerika"}, target_candidates=100, max_pages=2
    )

    assert [c.ticker for c in result] == ["AAA", "BBB"]


def test_discover_candidates_stops_at_last_page() -> None:
    grid = _FakeGrid([[_candidate("AAA")]])  # go_to_next_page returns False immediately

    result = discover_candidates(
        grid, field_labels={}, regions={"Nordamerika"}, target_candidates=100, max_pages=10
    )

    assert [c.ticker for c in result] == ["AAA"]


def test_discover_candidates_filters_out_non_matching_regions() -> None:
    grid = _FakeGrid([[_candidate("AAA", region="Nordamerika"), _candidate("BBB", region="Asien")]])

    result = discover_candidates(
        grid, field_labels={}, regions={"Nordamerika"}, target_candidates=100, max_pages=1
    )

    assert [c.ticker for c in result] == ["AAA"]


def test_sync_screener_candidates_returns_zero_for_empty_list(session: Session) -> None:
    count = sync_screener_candidates(session, datetime.date(2026, 7, 11), [])
    assert count == 0


def test_sync_screener_candidates_inserts_rows(session: Session) -> None:
    candidate = ScreenerCandidate(
        isin="US1", ticker="AAA", name="A Corp", region="Nordamerika", fields={"price": "10"}
    )

    count = sync_screener_candidates(session, datetime.date(2026, 7, 11), [candidate])

    assert count == 1
    row = session.scalars(select(AktienfinderScreenerCandidate)).one()
    assert row.ticker == "AAA"
    assert row.isin == "US1"
    assert row.fields == {"price": "10"}


def test_sync_screener_candidates_upserts_on_isin_and_date_without_duplicates(
    session: Session,
) -> None:
    day = datetime.date(2026, 7, 11)
    v1 = ScreenerCandidate(isin="US1", ticker="AAA", name="A Corp", region="Nordamerika", fields={})
    v2 = ScreenerCandidate(
        isin="US1", ticker="AAA", name="A Corp", region="Nordamerika", fields={"price": "99"}
    )

    sync_screener_candidates(session, day, [v1])
    sync_screener_candidates(session, day, [v2])

    rows = session.scalars(select(AktienfinderScreenerCandidate)).all()
    assert len(rows) == 1
    assert rows[0].fields == {"price": "99"}
