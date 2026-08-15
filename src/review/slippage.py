"""Slippage malus computation — deterministic code, no LLM.

Formula (ARCHITECTURE.md §7.8, F083):
  malus = 0.5 × estimated_spread + volume_penalty

The malus is in USD and simulates costs that are absent in Alpaca's
paper mode (spread, market impact).  Parameter values in
config/review.yaml are defaults proposed at F083 implementation time
(2026-07-25) and may be fine-tuned before the 2026-08-03 competition
start — each change is a reviewed, documented decision.

See docs/features/F083-slippage-malus-berechnung.md.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Decision, MarketBar, MarketBarTimeframe, OrderRecord

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "review.yaml"

#: F113: per-call memo for `_get_daily_dollar_volume`, keyed by (symbol, day).
#: A `ContextVar` rather than a module global because the scheduler runs jobs on
#: APScheduler threads — a shared dict would leak lookups between concurrent runs.
#: `None` means "no cache active", which is the normal single-order path.
_volume_cache: ContextVar[dict[tuple[str, datetime.date], float | None] | None] = ContextVar(
    "slippage_volume_cache", default=None
)


def _load_config(path: Path = _DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text()) or {}
    result: dict[str, Any] = raw.get("slippage", {})
    return result


def load_slippage_config(path: Path = _DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Public read of the slippage section, so a caller scoring many orders reads
    `config/review.yaml` once instead of once per order (F113)."""
    return _load_config(path)


@contextmanager
def volume_lookup_cache() -> Iterator[None]:
    """Memoises the daily-volume lookup for the duration of the block.

    A portfolio's orders cluster on a handful of symbols and days, so scoring a
    whole season goes from one query per order to one per (symbol, day). Scoped
    rather than permanent: `market_bar` gets a fresh row every day, and a
    long-lived cache would keep serving yesterday's volume.
    """
    token = _volume_cache.set({})
    try:
        yield
    finally:
        _volume_cache.reset(token)


def compute_slippage_malus(
    session: Session,
    order: OrderRecord,
    config: dict[str, Any] | None = None,
) -> Decimal | None:
    """Return the slippage malus in USD for a filled order.

    Returns None if the malus is disabled in config.  Never raises for
    missing data — instead logs a warning and computes with defaults.
    """
    if config is None:
        config = _load_config()
    if not config.get("enabled", True):
        return None

    # Resolve instrument and quantity from the linked Decision.
    decision: Decision | None = session.get(Decision, order.decision_id)
    if decision is None or decision.quantity is None:
        logger.warning("slippage: no Decision or quantity for order %s", order.id)
        return Decimal("0")

    qty = float(decision.quantity)
    fill_price = float(order.fill_price) if order.fill_price else 0.0
    order_value = fill_price * qty

    if order_value <= 0:
        return Decimal("0")

    # --- Spread cost ---
    spread_bps = _get_spread_bps(order, decision.instrument, config)
    spread_cost = 0.5 * spread_bps / 10_000 * order_value

    # --- Volume penalty ---
    daily_dollar_volume = _get_daily_dollar_volume(session, decision.instrument, order.submitted_at)
    penalty = (
        _compute_penalty(order_value, daily_dollar_volume, config)
        if daily_dollar_volume
        else Decimal("0")
    )

    total = Decimal(str(round(spread_cost, 4))) + penalty
    return Decimal(str(round(total, 4)))


def _get_spread_bps(order: OrderRecord, symbol: str, config: dict[str, Any]) -> float:
    """Return the spread in basis points — measured at order time when available
    (F104), otherwise the flat per-asset-class rate (F083).

    The flat rate treats an illiquid penny stock like SPY; the measured quote is what
    the order actually faced. Implausible measurements (<= 0 or beyond
    `max_measured_bps`, e.g. a crossed book or a halt) fall back rather than dragging
    an outlier straight into the leaderboard's adjusted performance.
    """
    measured = order.spread_bps
    if measured is not None and config.get("use_measured_spread", True):
        max_bps = float(config.get("max_measured_bps", 500))
        if 0 < float(measured) <= max_bps:
            return float(measured)
        logger.warning(
            "slippage: implausible measured spread %s bps for order %s — using flat rate",
            measured,
            order.id,
        )

    return _flat_spread_bps(symbol, config)


def _flat_spread_bps(symbol: str, config: dict[str, Any]) -> float:
    """Return the spread in basis points for *symbol* based on asset class."""
    crypto_symbols = config.get(
        "crypto_symbols",
        ["BTC", "ETH", "USDT", "USDC", "XRP", "DOGE", "SOL"],
    )
    is_crypto = any(sym in symbol.upper() for sym in crypto_symbols)
    key = "crypto" if is_crypto else "equities"
    return float(config.get("spread_bps", {}).get(key, 5))


def _get_daily_dollar_volume(
    session: Session,
    symbol: str,
    at_time: datetime.datetime | None = None,
) -> float | None:
    """Return the daily *dollar* volume (shares × close) from the most
    recent marketbar <= *at_time*, or None if no bar is found."""
    if at_time is None:
        at_time = datetime.datetime.now(datetime.UTC)

    cache = _volume_cache.get()
    key = (symbol, at_time.date())
    if cache is not None and key in cache:
        return cache[key]

    stmt = (
        select(MarketBar.volume, MarketBar.close)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.timeframe == MarketBarTimeframe.DAY,
            MarketBar.ts <= at_time,
        )
        .order_by(MarketBar.ts.desc())
        .limit(1)
    )
    row = session.execute(stmt).one_or_none()
    result = None if row is None else float(row[0]) * float(row[1])
    if cache is not None:
        cache[key] = result
    return result


def _compute_penalty(
    order_value: float,
    daily_dollar_volume: float,
    config: dict[str, Any],
) -> Decimal:
    """Compute the volume penalty component of the malus.

    Both *order_value* and *daily_dollar_volume* are in USD.

    Formula: if order_value / daily_dollar_volume > threshold:
      penalty_bps = min(bps_per_x × (order_vol_ratio/threshold - 1), cap_bps)
      penalty_usd = penalty_bps / 10000 × order_value
    else:
      penalty_usd = 0
    """
    if daily_dollar_volume <= 0:
        logger.warning("slippage: zero dollar volume for symbol — skipping penalty")
        return Decimal("0")

    volume_threshold = float(config.get("penalty", {}).get("volume_threshold_pct", 1.0)) / 100.0
    order_vol_pct = order_value / daily_dollar_volume

    if order_vol_pct <= volume_threshold:
        return Decimal("0")

    bps_per_x = float(config.get("penalty", {}).get("bps_per_x", 10))
    cap_bps = float(config.get("penalty", {}).get("cap_bps", 50))

    # Penalty bps = bps_per_x × how many times over threshold (minus 1)
    penalty_bps = bps_per_x * (order_vol_pct / volume_threshold - 1)
    penalty_bps = min(penalty_bps, cap_bps)

    return Decimal(str(round(penalty_bps / 10_000 * order_value, 4)))
