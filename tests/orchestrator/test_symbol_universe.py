"""See docs/features/F035-ingestion-scheduler-activation.md §3."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import ScreenerResult
from src.orchestrator.symbol_universe import resolve_symbol_universe
from tests.db.factories import make_persona, make_portfolio, make_position_snapshot


def _make_screener_result(
    session: Session, symbol: str, screened_at: datetime.date
) -> ScreenerResult:
    result = ScreenerResult(
        screened_at=screened_at,
        symbol=symbol,
        price=Decimal("3.20"),
        volume=Decimal("500000"),
    )
    session.add(result)
    session.flush()
    return result


def test_empty_db_returns_only_seed_watchlist(session: Session) -> None:
    universe = resolve_symbol_universe(session, ["AAPL", "MSFT"])

    assert universe == ["AAPL", "MSFT"]


def test_includes_currently_open_position_instruments(session: Session) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_position_snapshot(session, portfolio)  # AAPL, see factories default

    universe = resolve_symbol_universe(session, ["SPY"])

    assert universe == ["AAPL", "SPY"]


def test_excludes_stale_position_from_earlier_snapshot(session: Session) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_position_snapshot(
        session, portfolio, ts=datetime.datetime(2026, 7, 1, 16, 0), instrument="OLD"
    )
    make_position_snapshot(
        session, portfolio, ts=datetime.datetime(2026, 7, 4, 16, 0), instrument="AAPL"
    )

    universe = resolve_symbol_universe(session, [])

    assert universe == ["AAPL"]


def test_includes_latest_screener_symbols_only(session: Session) -> None:
    _make_screener_result(session, "XYZ", datetime.date(2026, 7, 7))
    _make_screener_result(session, "ABC", datetime.date(2026, 7, 8))

    universe = resolve_symbol_universe(session, [])

    assert universe == ["ABC"]


def test_deduplicates_across_sources(session: Session) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_position_snapshot(session, portfolio)  # AAPL
    _make_screener_result(session, "AAPL", datetime.date(2026, 7, 8))

    universe = resolve_symbol_universe(session, ["AAPL"])

    assert universe == ["AAPL"]
