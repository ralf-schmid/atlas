import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from alpaca.data.models.bars import Bar as AlpacaBar
from alpaca.data.models.bars import BarSet

from src.ingestion.crypto_market_data_sync import AlpacaCryptoBarsProvider, run_daily_crypto_sync
from src.ingestion.market_data_sync import Bar


def _alpaca_bar(symbol: str, ts: datetime.datetime, close: float) -> AlpacaBar:
    return AlpacaBar.model_construct(
        symbol=symbol,
        timestamp=ts,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=10.0,
        trade_count=None,
        vwap=None,
    )


def test_alpaca_crypto_bars_provider_maps_bar_set_to_bar_dataclass():
    ts = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    bar_set = BarSet.model_construct(
        data={"BTC/USD": [_alpaca_bar("BTC/USD", ts, 64000.0)]},
    )
    with patch("src.ingestion.crypto_market_data_sync.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_bars.return_value = bar_set

        provider = AlpacaCryptoBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        bars = provider.get_daily_bars(["BTC/USD"], day, day)

        mock_cls.assert_called_once_with("key", "secret")
        assert bars == [
            Bar(
                symbol="BTC/USD",
                ts=ts.replace(tzinfo=None),
                open=Decimal("63999.0"),
                high=Decimal("64001.0"),
                low=Decimal("63998.0"),
                close=Decimal("64000.0"),
                volume=Decimal("10.0"),
            )
        ]


def test_alpaca_crypto_bars_provider_uses_inclusive_end_of_day_for_same_day_range():
    """Same start-inclusive/end-exclusive caution as the stock provider
    (test_market_data_sync.py) — kept for consistency even though live
    verification showed crypto day-bars also matched a zero-width window
    (see module docstring)."""
    bar_set = BarSet.model_construct(data={})
    with patch("src.ingestion.crypto_market_data_sync.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_bars.return_value = bar_set

        provider = AlpacaCryptoBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        provider.get_daily_bars(["BTC/USD"], day, day)

        request = mock_cls.return_value.get_crypto_bars.call_args[0][0]
        assert request.start == datetime.datetime(2026, 7, 1, 0, 0, 0)
        assert request.end == datetime.datetime(2026, 7, 1, 23, 59, 59, 999999)


def test_alpaca_crypto_bars_provider_skips_symbols_with_no_bars():
    bar_set = BarSet.model_construct(data={})
    with patch("src.ingestion.crypto_market_data_sync.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_bars.return_value = bar_set

        provider = AlpacaCryptoBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        bars = provider.get_daily_bars(["ZZZ/USD"], day, day)

        assert bars == []


def test_run_daily_crypto_sync_reads_config_and_env(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "crypto_market_data:\n"
        "  key_id_env: TEST_CMD_KEY_ID\n"
        "  secret_key_env: TEST_CMD_SECRET_KEY\n"
        "  watchlist:\n"
        "    - BTC/USD\n"
    )
    monkeypatch.setenv("TEST_CMD_KEY_ID", "key")
    monkeypatch.setenv("TEST_CMD_SECRET_KEY", "secret")

    ts = datetime.datetime(2026, 7, 1)
    bar_set = BarSet.model_construct(data={"BTC/USD": [_alpaca_bar("BTC/USD", ts, 64000.0)]})
    with patch("src.ingestion.crypto_market_data_sync.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_bars.return_value = bar_set

        count = run_daily_crypto_sync(session, datetime.date(2026, 7, 1), config_path=config_path)

    assert count == 1


def test_run_daily_crypto_sync_defaults_to_a_90_day_lookback_window(session, tmp_path, monkeypatch):
    """Unlike the stock sync (default lookback_days=1, F048's fix layered on
    top of pre-existing single-day callers), crypto ingestion is new — it
    starts directly with the F048 lesson applied, no separate backfill step
    needed for CRYPTOR's technical indicators to have enough history from the
    first run."""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "crypto_market_data:\n"
        "  key_id_env: TEST_CMD_KEY_ID\n"
        "  secret_key_env: TEST_CMD_SECRET_KEY\n"
        "  watchlist:\n"
        "    - BTC/USD\n"
    )
    monkeypatch.setenv("TEST_CMD_KEY_ID", "key")
    monkeypatch.setenv("TEST_CMD_SECRET_KEY", "secret")

    bar_set = BarSet.model_construct(data={})
    trading_day = datetime.date(2026, 7, 10)
    with patch("src.ingestion.crypto_market_data_sync.CryptoHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_crypto_bars.return_value = bar_set

        run_daily_crypto_sync(session, trading_day, config_path=config_path)

        request = mock_cls.return_value.get_crypto_bars.call_args[0][0]

    expected_start = trading_day - datetime.timedelta(days=89)
    assert request.start == datetime.datetime.combine(expected_start, datetime.time.min)
    assert request.end == datetime.datetime.combine(trading_day, datetime.time.max)


def test_run_daily_crypto_sync_raises_when_env_var_missing(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "crypto_market_data:\n"
        "  key_id_env: TEST_CMD_KEY_ID_MISSING\n"
        "  secret_key_env: TEST_CMD_SECRET_KEY_MISSING\n"
        "  watchlist:\n"
        "    - BTC/USD\n"
    )
    monkeypatch.delenv("TEST_CMD_KEY_ID_MISSING", raising=False)
    monkeypatch.delenv("TEST_CMD_SECRET_KEY_MISSING", raising=False)

    with pytest.raises(ValueError, match="TEST_CMD_KEY_ID_MISSING"):
        run_daily_crypto_sync(session, datetime.date(2026, 7, 1), config_path=config_path)
