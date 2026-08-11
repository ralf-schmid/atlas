"""See docs/features/F105-alpaca-news-und-screener.md §3, tests 5-8."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import MarketMover
from src.ingestion.alpaca_screener import (
    CATEGORY_GAINER,
    CATEGORY_LOSER,
    CATEGORY_MOST_ACTIVE,
    Mover,
    run_alpaca_screener_sync,
    sync_market_movers,
)

_SCREENED_AT = datetime.datetime(2026, 8, 11, 20, 0)


class _FakeProvider:
    def __init__(self) -> None:
        self.markets: list[str] = []

    def fetch_most_actives(self, top: int) -> list[Mover]:
        return [
            Mover(
                market="stocks",
                category=CATEGORY_MOST_ACTIVE,
                symbol=symbol,
                rank=rank,
                price=None,
                change_pct=None,
                volume=Decimal("1000000"),
                screened_at=_SCREENED_AT,
            )
            for rank, symbol in enumerate(["AAPL", "TSLA"][:top], start=1)
        ]

    def fetch_movers(self, market: str, top: int) -> list[Mover]:
        self.markets.append(market)
        prefix = "BTC" if market == "crypto" else "GME"
        return [
            Mover(
                market=market,
                category=CATEGORY_GAINER,
                symbol=f"{prefix}UP",
                rank=1,
                price=Decimal("10.00"),
                change_pct=Decimal("12.5"),
                volume=None,
                screened_at=_SCREENED_AT,
            ),
            Mover(
                market=market,
                category=CATEGORY_LOSER,
                symbol=f"{prefix}DOWN",
                rank=1,
                price=Decimal("3.00"),
                change_pct=Decimal("-8.25"),
                volume=None,
                screened_at=_SCREENED_AT,
            ),
        ]


def _config(tmp_path, market_types: str) -> object:
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "alpaca_screener:\n"
        "  key_id_env: TEST_MD_KEY_ID\n"
        "  secret_key_env: TEST_MD_SECRET_KEY\n"
        "  top: 2\n"
        f"  market_types:\n{market_types}"
    )
    return config_path


def test_sync_writes_most_actives_with_rank(session: Session, tmp_path) -> None:
    run_alpaca_screener_sync(
        session, config_path=_config(tmp_path, "    - stocks\n"), provider=_FakeProvider()
    )

    rows = session.scalars(
        select(MarketMover)
        .where(MarketMover.category == CATEGORY_MOST_ACTIVE)
        .order_by(MarketMover.rank)
    ).all()
    assert [(row.symbol, row.rank) for row in rows] == [("AAPL", 1), ("TSLA", 2)]


def test_sync_writes_gainers_and_losers(session: Session, tmp_path) -> None:
    run_alpaca_screener_sync(
        session, config_path=_config(tmp_path, "    - stocks\n"), provider=_FakeProvider()
    )

    gainer = session.scalar(select(MarketMover).where(MarketMover.category == CATEGORY_GAINER))
    loser = session.scalar(select(MarketMover).where(MarketMover.category == CATEGORY_LOSER))
    assert gainer is not None and gainer.symbol == "GMEUP"
    assert gainer.change_pct == Decimal("12.5000")
    assert loser is not None and loser.symbol == "GMEDOWN"
    assert loser.change_pct == Decimal("-8.2500")


def test_sync_covers_configured_market_types(session: Session, tmp_path) -> None:
    """F105: crypto is in from the start so CRYPTOR gets the same impulse type as
    the equity personas (parity, Invariant #10)."""
    provider = _FakeProvider()

    run_alpaca_screener_sync(
        session,
        config_path=_config(tmp_path, "    - stocks\n    - crypto\n"),
        provider=provider,
    )

    assert provider.markets == ["stocks", "crypto"]
    markets = {row.market for row in session.scalars(select(MarketMover)).all()}
    assert markets == {"stocks", "crypto"}


def test_sync_is_idempotent(session: Session) -> None:
    movers = _FakeProvider().fetch_most_actives(top=2)

    sync_market_movers(session, movers)
    sync_market_movers(session, movers)

    assert len(session.scalars(select(MarketMover)).all()) == 2
