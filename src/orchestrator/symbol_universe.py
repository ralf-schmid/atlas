"""Dynamic symbol universe for market-data sync and technical-indicator
computation — see docs/features/F035-ingestion-scheduler-activation.md §2.

Union of a static seed watchlist, currently open positions (across all
portfolios), and the latest VULTURE-screener candidates. Pure DB read, no live
broker call — `position_snapshot` is already refreshed every cycle by
`src.orchestrator.reporting.generate_portfolio_snapshot`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import AktienfinderScreenerCandidate, PositionSnapshot, ScreenerResult


def resolve_symbol_universe(session: Session, seed_watchlist: list[str]) -> list[str]:
    symbols = set(seed_watchlist)
    symbols |= _open_position_instruments(session)
    symbols |= _latest_screener_symbols(session)
    symbols |= _latest_aktienfinder_screener_tickers(session)
    return sorted(symbols)


def resolve_stock_seed_watchlist(config: dict[str, object]) -> list[str]:
    """Merges `market_data.watchlist` with any Alpaca-tradable ticker mapped from
    an aktienfinder candidate ISIN (F067, `aktienfinder.ticker_by_isin`) — without
    this, aktienfinder's price-target/quality-score research items exist but have
    no `market_bar` rows behind them, so `get_latest_price` returns `None` and a
    buy on that symbol can never be sized. Used as the seed for both the daily
    stock market-data sync job (`src/ingestion/scheduler.py`) and technical-
    indicator computation (`research_synthesis.py`) — kept in one place so they
    can't drift apart. Deliberately does *not* include `crypto_market_data.watchlist`
    (F064) — that has its own sync job/provider (crypto, not stock)."""
    market_data_config = config["market_data"]
    assert isinstance(market_data_config, dict)
    aktienfinder_config = config.get("aktienfinder", {})
    assert isinstance(aktienfinder_config, dict)
    ticker_by_isin = aktienfinder_config.get("ticker_by_isin", {})
    assert isinstance(ticker_by_isin, dict)

    seed = set(market_data_config["watchlist"]) | set(ticker_by_isin.values())
    return sorted(seed)


def _open_position_instruments(session: Session) -> set[str]:
    """Only the *current* open positions — the latest snapshot per portfolio, not
    every instrument ever held (which would only ever grow)."""
    latest_ts_per_portfolio = (
        select(
            PositionSnapshot.portfolio_id,
            func.max(PositionSnapshot.ts).label("latest_ts"),
        )
        .group_by(PositionSnapshot.portfolio_id)
        .subquery()
    )
    stmt = select(PositionSnapshot.instrument).join(
        latest_ts_per_portfolio,
        (PositionSnapshot.portfolio_id == latest_ts_per_portfolio.c.portfolio_id)
        & (PositionSnapshot.ts == latest_ts_per_portfolio.c.latest_ts),
    )
    return set(session.scalars(stmt).all())


def _latest_screener_symbols(session: Session) -> set[str]:
    latest_screened_at = session.scalar(select(func.max(ScreenerResult.screened_at)))
    if latest_screened_at is None:
        return set()
    stmt = select(ScreenerResult.symbol).where(ScreenerResult.screened_at == latest_screened_at)
    return set(session.scalars(stmt).all())


def _latest_aktienfinder_screener_tickers(session: Session) -> set[str]:
    """F068: the aktienfinder Screener-Tool grid discovery job's most recent
    batch — same "latest run only" pattern as `_latest_screener_symbols`
    (VULTURE's screener), so a stale discovery run from days ago doesn't keep
    contributing symbols forever once a fresher run exists."""
    latest_discovered_at = session.scalar(
        select(func.max(AktienfinderScreenerCandidate.discovered_at))
    )
    if latest_discovered_at is None:
        return set()
    stmt = select(AktienfinderScreenerCandidate.ticker).where(
        AktienfinderScreenerCandidate.discovered_at == latest_discovered_at
    )
    return set(session.scalars(stmt).all())
