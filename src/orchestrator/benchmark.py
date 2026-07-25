"""SPY buy-and-hold benchmark — pure code, no LLM, reads market_bar only.

See docs/features/F081-spy-benchmark-portfolio.md for the full specification:
shares = start_capital / SPY close on the first trading day >= competition
start_date; benchmark_value(t) = shares * last SPY close <= t.

Config lives in config/competition.yaml (loaded once per process, module-
level cache). Before the start date, or if the benchmark is disabled, or
if the first bar is not yet ingested, this module returns None — never
raises.
"""

from __future__ import annotations

import datetime
import functools
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe
from src.orchestrator.competition_config import (
    CompetitionConfig,
    load_competition_config,
)

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_config() -> CompetitionConfig:
    return load_competition_config()


def compute_benchmark_value(session: Session, now: datetime.datetime) -> float | None:
    """Return the benchmark portfolio value (start_capital + unrealised
    gain) for *now*, or None if the benchmark is not yet active.

    All 6 portfolios in a single snapshot run share the same return value —
    call once and pass the result through (see F081 §2 "Konsistenz je Zyklus").
    """
    config = _get_config()
    if not config.benchmark_enabled:
        return None

    start_date = config.start_date

    # Before the competition start date — no benchmark yet.
    if now.date() < start_date:
        logger.debug("benchmark: now=%s < start_date=%s, returning None", now.date(), start_date)
        return None

    # First close price on or after the start date (may be the start_date
    # itself if it's a trading day, or the next available day otherwise).
    entry_price = _get_first_close_at_or_after(session, config.benchmark_symbol, start_date)
    if entry_price is None:
        logger.warning(
            "benchmark: no %s bar on/after %s yet — returning None",
            config.benchmark_symbol,
            start_date,
        )
        return None

    shares = config.start_capital_usd / entry_price

    # Latest close on or before `now` (reuses the existing index on
    # (symbol, timeframe, ts) — ORDER BY ts DESC LIMIT 1).
    latest_close = _get_latest_close_at_or_before(session, config.benchmark_symbol, now)
    if latest_close is None:
        # Shouldn't happen if entry_price exists and now >= start_date, but
        # guard anyway (weekend edge, data gaps).
        logger.warning(
            "benchmark: no %s bar <= %s after having an entry price — returning None",
            config.benchmark_symbol,
            now,
        )
        return None

    value = round(shares * latest_close, 2)
    return value


def _get_first_close_at_or_after(
    session: Session, symbol: str, on_or_after: datetime.date
) -> float | None:
    """Close of the first trading-day bar with ts.date() >= *on_or_after*."""
    stmt = (
        select(MarketBar.close)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.timeframe == MarketBarTimeframe.DAY,
            MarketBar.ts >= datetime.datetime.combine(on_or_after, datetime.time.min),
        )
        .order_by(MarketBar.ts.asc())
        .limit(1)
    )
    close = session.scalar(stmt)
    return float(close) if close is not None else None


def _get_latest_close_at_or_before(
    session: Session, symbol: str, at_or_before: datetime.datetime
) -> float | None:
    """Close of the latest trading-day bar with ts <= *at_or_before*."""
    stmt = (
        select(MarketBar.close)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.timeframe == MarketBarTimeframe.DAY,
            MarketBar.ts <= at_or_before,
        )
        .order_by(MarketBar.ts.desc())
        .limit(1)
    )
    close = session.scalar(stmt)
    return float(close) if close is not None else None
