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

from src.db.models import PositionSnapshot, ScreenerResult


def resolve_symbol_universe(session: Session, seed_watchlist: list[str]) -> list[str]:
    symbols = set(seed_watchlist)
    symbols |= _open_position_instruments(session)
    symbols |= _latest_screener_symbols(session)
    return sorted(symbols)


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
