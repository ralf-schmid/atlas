"""Reads price/ATR14 from the already-ingested `market_bar` table (F008) — never a
live API call. See docs/features/F021-persona-analysis-agent.md §2 ("Agenten lesen
ausschliesslich aus der DB").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe

_ATR_PERIODS = 14
_MIN_BARS_FOR_ATR = _ATR_PERIODS + 1  # need one extra bar for the first true range's prev-close


def get_latest_price(session: Session, symbol: str) -> float | None:
    stmt = (
        select(MarketBar.close)
        .where(MarketBar.symbol == symbol, MarketBar.timeframe == MarketBarTimeframe.DAY)
        .order_by(MarketBar.ts.desc())
        .limit(1)
    )
    close = session.scalar(stmt)
    return float(close) if close is not None else None


def compute_atr14(session: Session, symbol: str) -> float | None:
    stmt = (
        select(MarketBar)
        .where(MarketBar.symbol == symbol, MarketBar.timeframe == MarketBarTimeframe.DAY)
        .order_by(MarketBar.ts.desc())
        .limit(_MIN_BARS_FOR_ATR)
    )
    bars = list(session.scalars(stmt).all())
    if len(bars) < _MIN_BARS_FOR_ATR:
        return None

    bars.reverse()  # oldest first
    true_ranges = []
    for prev_bar, bar in zip(bars, bars[1:], strict=False):  # deliberately unequal (n, n-1)
        high, low, prev_close = float(bar.high), float(bar.low), float(prev_bar.close)
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(true_range)

    return sum(true_ranges) / len(true_ranges)
