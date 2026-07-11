"""Daily crypto OHLCV bar sync into `market_bar` — CRYPTOR's momentum/trend
signal gap (charter promises "Momentum/Trend (code-berechnet)", see
docs/features/F064-crypto-market-data-sync.md).

Mirrors `market_data_sync.py`'s stock provider but against Alpaca's crypto
market-data endpoint (`CryptoHistoricalDataClient`), which is not IEX-gated
(no `DataFeed` needed, confirmed via live verification, see feature doc) and
reuses the exact same `Bar` dataclass / `sync_market_bars` upsert — `market_bar`
has no asset-class column, a symbol is just a string ("BTC/USD" vs. "AAPL"),
and `src/orchestrator/indicators.py` is already symbol-agnostic (F036).
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal
from pathlib import Path

import yaml
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.models.bars import BarSet
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from sqlalchemy.orm import Session

from src.ingestion.market_data_sync import Bar, sync_market_bars

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


class AlpacaCryptoBarsProvider:
    """Wraps Alpaca's crypto bars endpoint — shared market data, identical for
    every persona (Invariant #10), same paper market-data key as the stock
    provider (crypto data needs no separate entitlement, live-verified)."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = CryptoHistoricalDataClient(api_key, secret_key)

    def get_daily_bars(
        self, symbols: list[str], start: datetime.date, end: datetime.date
    ) -> list[Bar]:
        request = CryptoBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=datetime.datetime.combine(start, datetime.time.min),
            # Same start-inclusive/end-exclusive caution as the stock provider
            # (market_data_sync.py) — a same-day request needs an inclusive
            # end-of-day bound. Live-verified harmless (crypto's day-bar
            # already matched a zero-width window too), kept for consistency
            # and to not silently rely on that undocumented behaviour.
            end=datetime.datetime.combine(end, datetime.time.max),
        )
        bar_set = self._client.get_crypto_bars(request)
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


def run_daily_crypto_sync(
    session: Session,
    trading_day: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
    lookback_days: int = 90,
) -> int:
    """Config-driven entry point, mirrors `market_data_sync.run_daily_sync`.

    Rolling `lookback_days` window (default 90, same as the stock sync since
    F048) so `src/orchestrator/indicators.py`'s minimum bar counts (up to 51
    for a SMA20/50 crossover) are met from the first run — no separate
    backfill step needed, idempotent upsert makes daily re-runs safe.
    """
    config = yaml.safe_load(config_path.read_text())
    crypto_config = config["crypto_market_data"]
    watchlist: list[str] = crypto_config["watchlist"]

    key_id = _require_env(crypto_config["key_id_env"])
    secret_key = _require_env(crypto_config["secret_key_env"])
    provider = AlpacaCryptoBarsProvider(api_key=key_id, secret_key=secret_key)

    start = trading_day - datetime.timedelta(days=lookback_days - 1)
    return sync_market_bars(session, provider, watchlist, start, trading_day)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
