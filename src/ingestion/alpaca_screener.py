"""Alpaca screener ingestion into `market_mover` — see
docs/features/F105-alpaca-news-und-screener.md.

Most actives plus the day's gainers/losers, per configured market. This is the
broad "what is moving at all today" impulse the shared pool had no channel for —
`screener_result` is VULTURE's penny-stock filter (F010), the aktienfinder
discovery delivers quality names (F043), and neither says anything about today's
outliers.

Idempotent: upsert on (market, category, symbol, screened_at), where `screened_at`
is the API's own `last_updated` — a repeated run within the same publication
window overwrites instead of duplicating.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import yaml
from alpaca.data.enums import MarketType
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.models.screener import MostActives, Movers
from alpaca.data.models.screener import Mover as AlpacaMover
from alpaca.data.requests import MarketMoversRequest, MostActivesRequest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import MarketMover

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"

CATEGORY_MOST_ACTIVE = "most_active"
CATEGORY_GAINER = "gainer"
CATEGORY_LOSER = "loser"


@dataclass(frozen=True, slots=True)
class Mover:
    market: str
    category: str
    symbol: str
    rank: int
    price: Decimal | None
    change_pct: Decimal | None
    volume: Decimal | None
    screened_at: datetime.datetime


class ScreenerProvider(Protocol):
    def fetch_most_actives(self, top: int) -> list[Mover]: ...

    def fetch_movers(self, market: str, top: int) -> list[Mover]: ...


class AlpacaScreenerProvider:
    """Same shared market-data key as every other Alpaca source (Invariant #10)."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = ScreenerClient(api_key, secret_key)

    def fetch_most_actives(self, top: int) -> list[Mover]:
        result = self._client.get_most_actives(MostActivesRequest(top=top))
        assert isinstance(result, MostActives)
        screened_at = _naive(result.last_updated)
        return [
            Mover(
                market="stocks",  # the most-actives endpoint is equities-only
                category=CATEGORY_MOST_ACTIVE,
                symbol=active.symbol,
                rank=rank,
                price=None,
                change_pct=None,
                volume=Decimal(str(active.volume)) if active.volume is not None else None,
                screened_at=screened_at,
            )
            for rank, active in enumerate(result.most_actives, start=1)
        ]

    def fetch_movers(self, market: str, top: int) -> list[Mover]:
        result = self._client.get_market_movers(
            MarketMoversRequest(top=top, market_type=MarketType(market))
        )
        assert isinstance(result, Movers)
        screened_at = _naive(result.last_updated)
        return [
            *_to_movers(result.gainers, market, CATEGORY_GAINER, screened_at),
            *_to_movers(result.losers, market, CATEGORY_LOSER, screened_at),
        ]


def _to_movers(
    raw_movers: Sequence[AlpacaMover],
    market: str,
    category: str,
    screened_at: datetime.datetime,
) -> list[Mover]:
    return [
        Mover(
            market=market,
            category=category,
            symbol=mover.symbol,
            rank=rank,
            price=_decimal(mover.price),
            change_pct=_decimal(mover.percent_change),
            volume=None,
            screened_at=screened_at,
        )
        for rank, mover in enumerate(raw_movers, start=1)
    ]


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _naive(value: datetime.datetime) -> datetime.datetime:
    return value.replace(tzinfo=None)


def sync_market_movers(session: Session, movers: list[Mover]) -> int:
    """Upserts `movers` and returns the number of rows written."""
    if not movers:
        return 0

    rows = [
        {
            "market": mover.market,
            "category": mover.category,
            "symbol": mover.symbol,
            "rank": mover.rank,
            "price": mover.price,
            "change_pct": mover.change_pct,
            "volume": mover.volume,
            "screened_at": mover.screened_at,
        }
        for mover in movers
    ]
    stmt = insert(MarketMover).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_mover_market_category_symbol_screened",
        set_={
            "rank": stmt.excluded.rank,
            "price": stmt.excluded.price,
            "change_pct": stmt.excluded.change_pct,
            "volume": stmt.excluded.volume,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def run_alpaca_screener_sync(
    session: Session,
    config_path: Path = _DEFAULT_CONFIG_PATH,
    provider: ScreenerProvider | None = None,
) -> int:
    config = yaml.safe_load(config_path.read_text())["alpaca_screener"]
    if provider is None:
        provider = AlpacaScreenerProvider(
            api_key=_require_env(config["key_id_env"]),
            secret_key=_require_env(config["secret_key_env"]),
        )
    # F105 §2: `top` is the cost guard — each row becomes a research_item that six
    # personas read every cycle.
    top = int(config.get("top", 10))
    markets: list[str] = config.get("market_types", ["stocks"])

    movers = list(provider.fetch_most_actives(top))
    for market in markets:
        movers.extend(provider.fetch_movers(market, top))
    return sync_market_movers(session, movers)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
