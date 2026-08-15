"""Shared builders for the backtest suite — see docs/features/F111-backtest-modul.md §8.

Most of this suite is pure: the engine takes a `BarUniverse` and a `StrategySpec`,
neither of which needs a database. Only the anti-drift checks against the live
indicator functions and the persistence tests touch Postgres, and those opt in via
`db_session`.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.orm import Session

from src.backtest.data import BarUniverse, SymbolSeries, fingerprint
from src.backtest.engine import EngineConfig
from src.backtest.signals import Bar
from src.backtest.spec import StrategySpec, load_strategy

DAY_ZERO = datetime.date(2026, 1, 5)  # a Monday

# Flat 5 bps equities spread, penalty above 1 % of daily volume — the shipped
# config/review.yaml values, restated so a config tweak cannot silently rewrite
# the hand-computed expectations in these tests.
SLIPPAGE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "spread_bps": {"equities": 5, "crypto": 15},
    "penalty": {"volume_threshold_pct": 1.0, "bps_per_x": 10, "cap_bps": 50},
}


@pytest.fixture
def db_session(_migrated_schema: None, session: Session) -> Session:
    """Opts a single test into the real-Postgres schema (see tests/conftest.py)."""
    return session


def day(offset: int) -> datetime.date:
    return DAY_ZERO + datetime.timedelta(days=offset)


def bar(
    offset: int,
    close: float,
    *,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1_000_000.0,
) -> Bar:
    price = close if open_ is None else open_
    return Bar(
        day=day(offset),
        open=price,
        high=high if high is not None else max(price, close),
        low=low if low is not None else min(price, close),
        close=close,
        volume=volume,
    )


def make_universe(
    bars_by_symbol: dict[str, list[Bar]],
    *,
    first_day: datetime.date | None = None,
    excluded: dict[str, str] | None = None,
) -> BarUniverse:
    series = {
        symbol: SymbolSeries(
            symbol=symbol,
            bars=bars,
            index_by_day={item.day: index for index, item in enumerate(bars)},
        )
        for symbol, bars in bars_by_symbol.items()
    }
    calendar = sorted({item.day for bars in bars_by_symbol.values() for item in bars})
    trading_days = [d for d in calendar if first_day is None or d >= first_day]
    return BarUniverse(
        series=series,
        trading_days=trading_days,
        excluded=excluded or {},
        fingerprint=fingerprint(series),
    )


def write_spec(tmp_path: Path, mapping: dict[str, Any], name: str = "test-spec") -> StrategySpec:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(mapping, allow_unicode=True))
    return load_strategy(path)


def simple_spec(
    tmp_path: Path,
    *,
    entry: list[dict[str, Any]],
    exit_: list[dict[str, Any]] | None = None,
    max_position_pct: float = 0.10,
    max_trades_per_day: int = 8,
    max_open_positions: int | None = 15,
    min_cash_pct: float = 0.0,
    max_loss_pct: float = 0.15,
    filters: list[dict[str, Any]] | None = None,
    symbols: list[str] | None = None,
    max_hold_days: int | None = None,
    name: str = "test-spec",
) -> StrategySpec:
    mapping: dict[str, Any] = {
        "name": name,
        "description": "test",
        "guardrails": {
            "name": "TEST",
            "max_position_pct": max_position_pct,
            "max_trades_per_day": max_trades_per_day,
            "max_open_positions": max_open_positions,
            "min_cash_pct": min_cash_pct,
            "stop_loss_policy": {"type": "fixed", "max_loss_pct": max_loss_pct},
        },
        "universe": {"filters": filters or []},
        "entry": entry,
        "exit": exit_ or [],
    }
    if symbols is not None:
        mapping["universe"]["symbols"] = symbols
    if max_hold_days is not None:
        mapping["max_hold_days"] = max_hold_days
    return write_spec(tmp_path, mapping, name)


def engine_config(start_capital_usd: float = 10_000.0, conviction: float = 1.0) -> EngineConfig:
    return EngineConfig(
        start_capital_usd=start_capital_usd,
        conviction=conviction,
        slippage=SLIPPAGE_CONFIG,
    )
