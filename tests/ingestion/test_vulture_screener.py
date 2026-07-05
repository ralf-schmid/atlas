import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from alpaca.data.models.bars import Bar as AlpacaBar
from alpaca.data.models.snapshots import Snapshot as AlpacaSnapshot
from alpaca.data.models.trades import Trade
from alpaca.trading.models import Asset

from src.ingestion.vulture_screener import (
    AlpacaAssetUniverseProvider,
    AlpacaSnapshotProvider,
    Snapshot,
    run_daily_screener,
    run_screener,
    sync_screener_results,
)


def _asset(symbol: str, tradable: bool = True) -> Asset:
    return Asset.model_construct(symbol=symbol, tradable=tradable)


def _alpaca_snapshot(symbol: str, price: float, volume: float) -> AlpacaSnapshot:
    return AlpacaSnapshot.model_construct(
        symbol=symbol,
        latest_trade=Trade.model_construct(symbol=symbol, price=price),
        latest_quote=None,
        minute_bar=None,
        daily_bar=AlpacaBar.model_construct(
            symbol=symbol,
            timestamp=datetime.datetime(2026, 7, 1),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            trade_count=None,
            vwap=None,
        ),
        previous_daily_bar=None,
    )


def test_asset_universe_provider_returns_only_tradable_symbols():
    with patch("src.ingestion.vulture_screener.TradingClient") as mock_cls:
        mock_cls.return_value.get_all_assets.return_value = [
            _asset("PENY", tradable=True),
            _asset("HALT", tradable=False),
        ]

        provider = AlpacaAssetUniverseProvider(api_key="key", secret_key="secret")
        symbols = provider.get_tradable_symbols()

        assert symbols == ["PENY"]


def test_snapshot_provider_maps_snapshots_and_skips_incomplete():
    with patch("src.ingestion.vulture_screener.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_snapshot.return_value = {
            "PENY": _alpaca_snapshot("PENY", 3.5, 500_000),
            "NODATA": AlpacaSnapshot.model_construct(
                symbol="NODATA",
                latest_trade=None,
                latest_quote=None,
                minute_bar=None,
                daily_bar=None,
                previous_daily_bar=None,
            ),
        }

        provider = AlpacaSnapshotProvider(api_key="key", secret_key="secret")
        snapshots = provider.get_snapshots(["PENY", "NODATA"])

        assert snapshots == [
            Snapshot(symbol="PENY", price=Decimal("3.5"), volume=Decimal("500000"))
        ]


class _FakeUniverse:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    def get_tradable_symbols(self) -> list[str]:
        return self._symbols


class _FakeSnapshots:
    def __init__(self, snapshots: list[Snapshot]) -> None:
        self._snapshots = snapshots

    def get_snapshots(self, symbols: list[str]) -> list[Snapshot]:
        return self._snapshots


def test_run_screener_filters_by_price_and_min_volume():
    snapshots = [
        Snapshot(symbol="PENY", price=Decimal("3.5"), volume=Decimal("500000")),
        Snapshot(symbol="EXPENSIVE", price=Decimal("150.0"), volume=Decimal("500000")),
        Snapshot(symbol="ILLIQUID", price=Decimal("2.0"), volume=Decimal("10")),
    ]
    candidates = run_screener(
        _FakeUniverse(["PENY", "EXPENSIVE", "ILLIQUID"]),
        _FakeSnapshots(snapshots),
        max_price=Decimal("5.0"),
        min_volume=Decimal("100000"),
    )

    assert candidates == [Snapshot(symbol="PENY", price=Decimal("3.5"), volume=Decimal("500000"))]


def test_run_screener_returns_empty_for_empty_universe():
    candidates = run_screener(
        _FakeUniverse([]),
        _FakeSnapshots([]),
        max_price=Decimal("5.0"),
        min_volume=Decimal("100000"),
    )
    assert candidates == []


def test_sync_screener_results_returns_zero_for_empty_list(session):
    assert sync_screener_results(session, datetime.date(2026, 7, 1), []) == 0


def test_sync_screener_results_inserts_and_is_idempotent_on_rerun(session):
    day = datetime.date(2026, 7, 1)
    v1 = [Snapshot(symbol="PENY", price=Decimal("3.5"), volume=Decimal("500000"))]
    v2 = [Snapshot(symbol="PENY", price=Decimal("4.0"), volume=Decimal("600000"))]

    first_count = sync_screener_results(session, day, v1)
    second_count = sync_screener_results(session, day, v2)

    assert first_count == 1
    assert second_count == 1

    from sqlalchemy import select

    from src.db.models import ScreenerResult

    rows = session.scalars(select(ScreenerResult).where(ScreenerResult.symbol == "PENY")).all()
    assert len(rows) == 1
    assert rows[0].price == Decimal("4.000000")
    assert rows[0].volume == Decimal("600000.000000")


def test_run_daily_screener_reads_config_and_env(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "vulture_screener:\n"
        "  key_id_env: TEST_SCREENER_KEY_ID\n"
        "  secret_key_env: TEST_SCREENER_SECRET_KEY\n"
        "  max_price: 5.0\n"
        "  min_volume: 100000\n"
    )
    monkeypatch.setenv("TEST_SCREENER_KEY_ID", "key")
    monkeypatch.setenv("TEST_SCREENER_SECRET_KEY", "secret")

    with (
        patch("src.ingestion.vulture_screener.TradingClient") as mock_trading_cls,
        patch("src.ingestion.vulture_screener.StockHistoricalDataClient") as mock_data_cls,
    ):
        mock_trading_cls.return_value.get_all_assets.return_value = [_asset("PENY")]
        mock_data_cls.return_value.get_stock_snapshot.return_value = {
            "PENY": _alpaca_snapshot("PENY", 3.5, 500_000),
        }

        count = run_daily_screener(session, datetime.date(2026, 7, 1), config_path=config_path)

    assert count == 1


def test_run_daily_screener_raises_when_env_var_missing(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "vulture_screener:\n"
        "  key_id_env: TEST_SCREENER_KEY_ID_MISSING\n"
        "  secret_key_env: TEST_SCREENER_SECRET_KEY_MISSING\n"
        "  max_price: 5.0\n"
        "  min_volume: 100000\n"
    )
    monkeypatch.delenv("TEST_SCREENER_KEY_ID_MISSING", raising=False)

    with pytest.raises(ValueError, match="TEST_SCREENER_KEY_ID_MISSING"):
        run_daily_screener(session, datetime.date(2026, 7, 1), config_path=config_path)
