"""VULTURE-Screener: full Alpaca universe -> price/volume candidate list.

See docs/features/F010-vulture-screener.md. Idempotent: upsert on the
(symbol, screened_at) unique constraint, so re-running the daily screener never
creates duplicates.
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
from alpaca.data.requests import StockSnapshotRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Asset
from alpaca.trading.requests import GetAssetsRequest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import ScreenerResult

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
_SNAPSHOT_BATCH_SIZE = 500  # keeps request URLs well under typical server limits


@dataclass(frozen=True, slots=True)
class Snapshot:
    symbol: str
    price: Decimal
    volume: Decimal


class AssetUniverseProvider(Protocol):
    def get_tradable_symbols(self) -> list[str]: ...


class SnapshotProvider(Protocol):
    def get_snapshots(self, symbols: list[str]) -> list[Snapshot]: ...


class AlpacaAssetUniverseProvider:
    """The full tradable/active Alpaca asset directory — "kein Whitelisting"
    (ARCHITECTURE.md §3.5.3): every persona sees candidates from the same universe."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = TradingClient(api_key, secret_key)

    def get_tradable_symbols(self) -> list[str]:
        request = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
        assets = self._client.get_all_assets(request)
        return [asset.symbol for asset in assets if isinstance(asset, Asset) and asset.tradable]


class AlpacaSnapshotProvider:
    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = StockHistoricalDataClient(api_key, secret_key)

    def get_snapshots(self, symbols: list[str]) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for i in range(0, len(symbols), _SNAPSHOT_BATCH_SIZE):
            batch = symbols[i : i + _SNAPSHOT_BATCH_SIZE]
            request = StockSnapshotRequest(symbol_or_symbols=batch)
            raw_snapshots = self._client.get_stock_snapshot(request)
            for symbol, snapshot in raw_snapshots.items():
                if snapshot is None or snapshot.latest_trade is None or snapshot.daily_bar is None:
                    continue
                snapshots.append(
                    Snapshot(
                        symbol=symbol,
                        price=Decimal(str(snapshot.latest_trade.price)),
                        volume=Decimal(str(snapshot.daily_bar.volume)),
                    )
                )
        return snapshots


def run_screener(
    universe: AssetUniverseProvider,
    snapshots: SnapshotProvider,
    max_price: Decimal,
    min_volume: Decimal,
) -> list[Snapshot]:
    """Filters the tradable universe by price and (data-quality-only, not a trading
    restriction — see ARCHITECTURE.md §3.5.3) minimum volume. Returns candidates,
    doesn't persist — see `sync_screener_results` for that."""
    symbols = universe.get_tradable_symbols()
    if not symbols:
        return []

    all_snapshots = snapshots.get_snapshots(symbols)
    return [s for s in all_snapshots if s.price < max_price and s.volume >= min_volume]


def sync_screener_results(
    session: Session, screened_at: datetime.date, candidates: list[Snapshot]
) -> int:
    if not candidates:
        return 0

    rows = [
        {
            "screened_at": screened_at,
            "symbol": c.symbol,
            "price": c.price,
            "volume": c.volume,
        }
        for c in candidates
    ]

    stmt = insert(ScreenerResult).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_screener_result_symbol_screened_at",
        set_={
            "price": stmt.excluded.price,
            "volume": stmt.excluded.volume,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def run_daily_screener(
    session: Session,
    screened_at: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point, mirrors `market_data_sync.run_daily_sync`. Wired
    into the ingestion scheduler (F035, `src/ingestion/scheduler.py`)."""
    config = yaml.safe_load(config_path.read_text())
    screener_config = config["vulture_screener"]

    key_id = _require_env(screener_config["key_id_env"])
    secret_key = _require_env(screener_config["secret_key_env"])

    universe = AlpacaAssetUniverseProvider(api_key=key_id, secret_key=secret_key)
    snapshots = AlpacaSnapshotProvider(api_key=key_id, secret_key=secret_key)

    candidates = run_screener(
        universe,
        snapshots,
        max_price=Decimal(str(screener_config["max_price"])),
        min_volume=Decimal(str(screener_config["min_volume"])),
    )
    return sync_screener_results(session, screened_at, candidates)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
