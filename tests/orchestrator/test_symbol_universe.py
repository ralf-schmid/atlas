"""See docs/features/F035-ingestion-scheduler-activation.md §3."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import AktienfinderScreenerCandidate, ScreenerResult
from src.orchestrator.symbol_universe import resolve_stock_seed_watchlist, resolve_symbol_universe
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


def _make_aktienfinder_candidate(
    session: Session, ticker: str, discovered_at: datetime.date
) -> AktienfinderScreenerCandidate:
    candidate = AktienfinderScreenerCandidate(
        isin=f"US{ticker}",
        ticker=ticker,
        name=ticker,
        region="Nordamerika",
        discovered_at=discovered_at,
        fields={},
    )
    session.add(candidate)
    session.flush()
    return candidate


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


def test_includes_latest_aktienfinder_screener_tickers_only(session: Session) -> None:
    """F068: same "latest discovery batch only" contract as VULTURE's screener."""
    _make_aktienfinder_candidate(session, "OLD", datetime.date(2026, 7, 7))
    _make_aktienfinder_candidate(session, "NEW", datetime.date(2026, 7, 8))

    universe = resolve_symbol_universe(session, [])

    assert universe == ["NEW"]


def test_deduplicates_across_sources(session: Session) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_position_snapshot(session, portfolio)  # AAPL
    _make_screener_result(session, "AAPL", datetime.date(2026, 7, 8))

    universe = resolve_symbol_universe(session, ["AAPL"])

    assert universe == ["AAPL"]


def test_resolve_stock_seed_watchlist_merges_market_data_and_aktienfinder_tickers() -> None:
    config = {
        "market_data": {"watchlist": ["AAPL", "MSFT"]},
        "aktienfinder": {"ticker_by_isin": {"DE0007164600": "SAP", "US7427181091": "PG"}},
    }

    seed = resolve_stock_seed_watchlist(config)

    assert seed == ["AAPL", "MSFT", "PG", "SAP"]


def test_resolve_stock_seed_watchlist_deduplicates_overlap() -> None:
    """F067: an ISIN mapped to a ticker already in market_data.watchlist (e.g.
    Apple -> AAPL) must not produce a duplicate entry."""
    config = {
        "market_data": {"watchlist": ["AAPL"]},
        "aktienfinder": {"ticker_by_isin": {"US0378331005": "AAPL"}},
    }

    seed = resolve_stock_seed_watchlist(config)

    assert seed == ["AAPL"]


def test_resolve_stock_seed_watchlist_without_aktienfinder_section() -> None:
    """Backward-compatible: a config without an `aktienfinder` section (or
    without `ticker_by_isin`) falls back to just the stock watchlist."""
    config: dict[str, object] = {"market_data": {"watchlist": ["AAPL"]}}

    seed = resolve_stock_seed_watchlist(config)

    assert seed == ["AAPL"]
