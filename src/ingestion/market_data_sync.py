"""Daily OHLCV bar sync into `market_bar` — see docs/features/F008-marktdaten-sync.md.

Idempotent: upsert on the (symbol, timeframe, ts) unique constraint, so re-running a
sync for a day already fetched (crash-recovery, backfill re-run) never creates
duplicate rows or fails, it just overwrites with the latest values from Alpaca.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import yaml
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.models.bars import BarSet
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    ts: datetime.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class BarsProvider(Protocol):
    def get_daily_bars(
        self, symbols: list[str], start: datetime.date, end: datetime.date
    ) -> list[Bar]: ...


class AlpacaBarsProvider:
    """Wraps Alpaca's stock bars endpoint — shared market data, identical for every
    persona (Invariant #10)."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = StockHistoricalDataClient(api_key, secret_key)

    def get_daily_bars(
        self, symbols: list[str], start: datetime.date, end: datetime.date
    ) -> list[Bar]:
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=datetime.datetime.combine(start, datetime.time.min),
            end=datetime.datetime.combine(end, datetime.time.min),
        )
        bar_set = self._client.get_stock_bars(request)
        assert isinstance(bar_set, BarSet)
        bars: list[Bar] = []
        for symbol in symbols:
            for raw_bar in bar_set.data.get(symbol, []):
                bars.append(
                    Bar(
                        symbol=symbol,
                        ts=raw_bar.timestamp.replace(tzinfo=None),
                        open=Decimal(str(raw_bar.open)),
                        high=Decimal(str(raw_bar.high)),
                        low=Decimal(str(raw_bar.low)),
                        close=Decimal(str(raw_bar.close)),
                        volume=Decimal(str(raw_bar.volume)),
                    )
                )
        return bars


def sync_market_bars(
    session: Session,
    provider: BarsProvider,
    symbols: list[str],
    start: datetime.date,
    end: datetime.date,
) -> int:
    """Fetches daily bars for `symbols` in [start, end] and upserts them.

    Returns the number of bars upserted. No-op (returns 0) for an empty symbol list —
    callers don't need to special-case an empty watchlist.
    """
    if not symbols:
        return 0

    bars = provider.get_daily_bars(symbols, start, end)
    if not bars:
        return 0

    rows = [
        {
            "symbol": bar.symbol,
            "timeframe": MarketBarTimeframe.DAY,
            "ts": bar.ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in bars
    ]

    stmt = insert(MarketBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_bar_symbol_timeframe_ts",
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def run_daily_sync(
    session: Session,
    trading_day: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point: reads `config/ingestion.yaml`'s watchlist + Alpaca
    market-data credentials from environment, syncs one day of bars.

    Not wired into a scheduler yet (orchestrator/cron wiring is P4/ops follow-up) —
    this is the callable a future scheduler invokes once a day per Cycle.
    """
    config = yaml.safe_load(config_path.read_text())
    market_data_config = config["market_data"]
    watchlist: list[str] = market_data_config["watchlist"]

    key_id = _require_env(market_data_config["key_id_env"])
    secret_key = _require_env(market_data_config["secret_key_env"])
    provider = AlpacaBarsProvider(api_key=key_id, secret_key=secret_key)

    return sync_market_bars(session, provider, watchlist, trading_day, trading_day)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
