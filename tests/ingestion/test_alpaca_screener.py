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
    _filter_movers,
    _take_top_per_group,
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


# --- F109 Rauschfilter, siehe docs/features/F109-screener-rauschfilter.md §3


def _movers(symbols: list[str], market: str = "stocks", category: str = CATEGORY_GAINER):
    return [
        Mover(
            market=market,
            category=category,
            symbol=symbol,
            rank=rank,
            price=Decimal("1.00"),
            change_pct=Decimal("5.0"),
            volume=None,
            screened_at=_SCREENED_AT,
        )
        for rank, symbol in enumerate(symbols, start=1)
    ]


def _filtered(symbols: list[str], market: str = "stocks", crypto_quote: str | None = None):
    kept = _filter_movers(
        _movers(symbols, market=market), exclude_derivatives=True, crypto_quote=crypto_quote
    )
    return [m.symbol for m in kept]


def test_warrants_and_rights_are_dropped_from_stock_movers() -> None:
    """Die echte Gainer-Liste vom 15.08.2026."""
    real = ["AACBR", "MYSEW", "WETO", "DUKRW", "ONFOW", "MDXH", "CAPR", "BANL", "HHS", "UMAL"]

    assert _filtered(real) == ["WETO", "MDXH", "CAPR", "BANL", "HHS", "UMAL"]


def test_four_letter_symbols_ending_in_w_are_kept() -> None:
    """Die Regel gilt erst ab fünf Stellen — vierstellig auf W ist eine Aktie."""
    assert _filtered(["WETO", "SNOW", "ABCW"]) == ["WETO", "SNOW", "ABCW"]


def test_crypto_pairs_are_reduced_to_the_usd_quote() -> None:
    pairs = ["LINK/USDC", "LINK/USD", "LINK/USDT", "LINK/BTC", "AVAX/USD", "AVAX/USDT"]

    assert _filtered(pairs, market="crypto", crypto_quote="USD") == ["LINK/USD", "AVAX/USD"]


def test_crypto_asset_without_usd_pair_is_kept() -> None:
    """Sonst verschwindet ein echter Mover, nur weil zufällig kein USD-Paar
    in derselben Lieferung steht."""
    pairs = ["LINK/USD", "LINK/USDT", "XYZ/USDT"]

    assert _filtered(pairs, market="crypto", crypto_quote="USD") == ["LINK/USD", "XYZ/USDT"]


def test_stock_filter_does_not_touch_crypto_symbols() -> None:
    """`SHIB/USD` hat fünf Zeichen vor dem Slash — die Aktien-Regel darf nicht greifen."""
    assert _filtered(["SHIB/USD", "PAXG/USD"], market="crypto") == ["SHIB/USD", "PAXG/USD"]


def test_ranks_stay_the_original_alpaca_ranks() -> None:
    """Nach dem Filter wird nicht neu nummeriert — eine erfundene Rangliste wäre
    schlimmer als eine löchrige."""
    kept = _filter_movers(
        _movers(["AACBR", "MYSEW", "MDXH"]), exclude_derivatives=True, crypto_quote=None
    )

    assert [(m.symbol, m.rank) for m in kept] == [("MDXH", 3)]


def test_take_top_per_group_counts_each_category_separately() -> None:
    movers = _movers(["A", "B", "C"], category=CATEGORY_GAINER) + _movers(
        ["D", "E", "F"], category=CATEGORY_LOSER
    )

    kept = _take_top_per_group(movers, top=2)

    assert [m.symbol for m in kept] == ["A", "B", "D", "E"]


def test_oversampling_fills_up_to_top_after_filtering(session: Session, tmp_path) -> None:
    """Der Kern: ohne Overfetch kämen aus 2 angefragten Gainern nach dem Filter 0."""

    class _WarrantHeavyProvider:
        def fetch_most_actives(self, top: int) -> list[Mover]:
            return []

        def fetch_movers(self, market: str, top: int) -> list[Mover]:
            # Erst Warrants, dann echte Aktien — genau die Reihenfolge, die ohne
            # Overfetch alles wegfiltern würde.
            symbols = ["AACBR", "MYSEW", "DUKRW", "MDXH", "CAPR", "BANL"][:top]
            return _movers(symbols, market=market)

    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "alpaca_screener:\n"
        "  key_id_env: TEST_MD_KEY_ID\n"
        "  secret_key_env: TEST_MD_SECRET_KEY\n"
        "  top: 2\n"
        "  exclude_derivative_classes: true\n"
        "  oversample: 3\n"
        "  market_types:\n    - stocks\n"
    )

    run_alpaca_screener_sync(session, config_path=config_path, provider=_WarrantHeavyProvider())

    rows = session.scalars(select(MarketMover).order_by(MarketMover.rank)).all()
    assert [r.symbol for r in rows] == ["MDXH", "CAPR"]


def test_filter_off_keeps_everything(session: Session, tmp_path) -> None:
    """Rollback-Pfad: ohne die F109-Schalter verhält sich der Job wie unter F105."""

    class _MixedProvider:
        def fetch_most_actives(self, top: int) -> list[Mover]:
            return []

        def fetch_movers(self, market: str, top: int) -> list[Mover]:
            return _movers(["AACBR", "MDXH"][:top], market=market)

    run_alpaca_screener_sync(
        session, config_path=_config(tmp_path, "    - stocks\n"), provider=_MixedProvider()
    )

    rows = session.scalars(select(MarketMover)).all()
    assert {r.symbol for r in rows} == {"AACBR", "MDXH"}
