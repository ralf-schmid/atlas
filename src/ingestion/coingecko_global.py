"""BTC-dominance ingestion from CoinGecko's free, no-auth `/global` endpoint —
see docs/features/F040-btc-dominance-ingestion.md.

No upsert/idempotency key like the other ingestion sources — every scheduled
fetch is a legitimate new time-series point, not a re-delivery of an existing
fact (see `BtcDominanceSnapshot`'s docstring in src/db/models.py).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from sqlalchemy.orm import Session

from src.db.models import BtcDominanceSnapshot

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


@dataclass(frozen=True, slots=True)
class GlobalMarketReading:
    btc_dominance_pct: float
    total_market_cap_usd: float


class GlobalMarketProvider(Protocol):
    def fetch_global_market(self) -> GlobalMarketReading: ...


class HttpCoinGeckoProvider:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def fetch_global_market(self) -> GlobalMarketReading:
        response = httpx.get(self._base_url, timeout=10.0)
        response.raise_for_status()
        return parse_global_response(response.json())


def parse_global_response(payload: dict[str, Any]) -> GlobalMarketReading:
    data = payload["data"]
    market_cap_percentage = data["market_cap_percentage"]
    total_market_cap = data["total_market_cap"]
    return GlobalMarketReading(
        btc_dominance_pct=float(market_cap_percentage["btc"]),
        total_market_cap_usd=float(total_market_cap["usd"]),
    )


def sync_btc_dominance_snapshot(
    session: Session, snapshot_at: datetime.datetime, reading: GlobalMarketReading
) -> None:
    session.add(
        BtcDominanceSnapshot(
            snapshot_at=snapshot_at,
            btc_dominance_pct=Decimal(str(reading.btc_dominance_pct)),
            total_market_cap_usd=Decimal(str(reading.total_market_cap_usd)),
        )
    )
    session.flush()


def run_coingecko_sync(session: Session, config_path: Path = _DEFAULT_CONFIG_PATH) -> int:
    """Config-driven entry point, mirrors the other F008-F014 `run_*` functions.
    Wired into the ingestion scheduler (F035/F040, `src/ingestion/scheduler.py`)."""
    config = yaml.safe_load(config_path.read_text())
    base_url = config["coingecko"]["base_url"]
    provider = HttpCoinGeckoProvider(base_url=base_url)

    reading = provider.fetch_global_market()
    snapshot_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    sync_btc_dominance_snapshot(session, snapshot_at, reading)
    return 1
