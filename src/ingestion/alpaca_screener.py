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

# F109: US ticker convention — a fifth character of W/R/U marks a warrant, right or
# unit rather than common stock. Alpaca's screener carries no instrument class, and
# an asset-directory lookup per run would be a second call over ~11k assets for a
# handful of symbols. A warrant's percent move is leverage mechanics, not a company
# event, and ATLAS doesn't trade them — see F109 §2 for why the heuristic's downside
# is acceptable.
_DERIVATIVE_CLASS_SUFFIXES = ("W", "R", "U")
_COMMON_STOCK_MAX_LEN = 4


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


def _is_derivative_class(symbol: str) -> bool:
    """True for warrants/rights/units by US ticker convention. Crypto pairs carry a
    slash and are never judged by this rule — `SHIB/USD` has five characters before
    the slash but is an ordinary asset."""
    if "/" in symbol:
        return False
    return len(symbol) > _COMMON_STOCK_MAX_LEN and symbol.endswith(_DERIVATIVE_CLASS_SUFFIXES)


def _base_asset(symbol: str) -> str:
    return symbol.split("/", 1)[0]


def _filter_movers(
    movers: list[Mover], exclude_derivatives: bool, crypto_quote: str | None
) -> list[Mover]:
    """Drops warrant-class stock symbols and collapses a crypto asset quoted in
    several currencies to one row — see F109 §1.

    An asset is only collapsed when the preferred quote is actually present in the
    batch: otherwise a genuine mover that happens to trade only against USDT would
    vanish instead of being deduplicated.
    """
    kept: list[Mover] = []
    quoted_in_preferred = {
        _base_asset(m.symbol)
        for m in movers
        if crypto_quote and m.symbol.endswith(f"/{crypto_quote}")
    }
    for mover in movers:
        if exclude_derivatives and _is_derivative_class(mover.symbol):
            continue
        if crypto_quote and "/" in mover.symbol:
            base = _base_asset(mover.symbol)
            if base in quoted_in_preferred and not mover.symbol.endswith(f"/{crypto_quote}"):
                continue
        kept.append(mover)
    return kept


def _take_top_per_group(movers: list[Mover], top: int) -> list[Mover]:
    """Cuts back to `top` per (market, category) *after* filtering — that's what the
    oversampling is for. Ranks stay Alpaca's original ones: renumbering would claim a
    ranking we didn't measure."""
    counts: dict[tuple[str, str], int] = {}
    kept: list[Mover] = []
    for mover in movers:
        key = (mover.market, mover.category)
        if counts.get(key, 0) >= top:
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(mover)
    return kept


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
    # F109: fetch more than `top` so the filter below still yields `top` real
    # impulses. Same single API call per endpoint, so no extra cost.
    exclude_derivatives = bool(config.get("exclude_derivative_classes", False))
    crypto_quote: str | None = config.get("crypto_quote")
    oversample = int(config.get("oversample", 1)) if (exclude_derivatives or crypto_quote) else 1
    fetch_top = top * oversample

    movers = list(provider.fetch_most_actives(fetch_top))
    for market in markets:
        movers.extend(provider.fetch_movers(market, fetch_top))

    movers = _filter_movers(movers, exclude_derivatives, crypto_quote)
    return sync_market_movers(session, _take_top_per_group(movers, top))


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
