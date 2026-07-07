from pathlib import Path
from unittest.mock import patch

import pytest

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.internal_ledger import InternalLedgerAdapter
from src.broker.market_data import AlpacaCryptoMarketDataProvider, AlpacaStockMarketDataProvider
from src.broker.registry import get_adapter, get_adapter_type


@pytest.fixture(autouse=True)
def _no_real_trading_client():
    with (
        patch("src.broker.alpaca_paper.TradingClient"),
        patch("src.broker.market_data.StockHistoricalDataClient"),
        patch("src.broker.market_data.CryptoHistoricalDataClient"),
    ):
        yield


@pytest.fixture(autouse=True)
def _market_data_env(monkeypatch):
    monkeypatch.setenv("ALPACA_MARKET_DATA_KEY_ID", "md-key-id")
    monkeypatch.setenv("ALPACA_MARKET_DATA_SECRET_KEY", "md-secret-key")


def test_get_adapter_resolves_native_persona(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_VULTURE_KEY_ID", "key-id")
    monkeypatch.setenv("ALPACA_PAPER_VULTURE_SECRET_KEY", "secret-key")

    adapter = get_adapter("VULTURE")

    assert isinstance(adapter, AlpacaPaperAdapter)


def test_get_adapter_missing_env_var_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_GUARDIAN_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_GUARDIAN_SECRET_KEY", raising=False)

    with pytest.raises(ValueError, match="ALPACA_PAPER_GUARDIAN_KEY_ID"):
        get_adapter("GUARDIAN")


def test_get_adapter_unknown_persona_raises():
    with pytest.raises(ValueError, match="Unknown persona"):
        get_adapter("NONEXISTENT")


def test_get_adapter_resolves_virtual_stock_persona():
    adapter = get_adapter("HYPE")

    assert isinstance(adapter, InternalLedgerAdapter)
    assert isinstance(adapter._market_data, AlpacaStockMarketDataProvider)


def test_get_adapter_resolves_virtual_crypto_persona():
    adapter = get_adapter("CRYPTOR")

    assert isinstance(adapter, InternalLedgerAdapter)
    assert isinstance(adapter._market_data, AlpacaCryptoMarketDataProvider)


def test_get_adapter_virtual_persona_missing_market_data_env_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_MARKET_DATA_KEY_ID", raising=False)

    with pytest.raises(ValueError, match="ALPACA_MARKET_DATA_KEY_ID"):
        get_adapter("HYPE")


def test_get_adapter_type_resolves_native_and_virtual_personas():
    assert get_adapter_type("VULTURE") == "alpaca_paper"
    assert get_adapter_type("HYPE") == "internal_ledger"


def test_get_adapter_type_unknown_persona_raises():
    with pytest.raises(ValueError, match="Unknown persona"):
        get_adapter_type("NONEXISTENT")


def test_get_adapter_unknown_adapter_type_raises(tmp_path: Path):
    config_path = tmp_path / "broker.yaml"
    config_path.write_text("personas:\n  FOO:\n    adapter: something_else\n")

    with pytest.raises(ValueError, match="Unknown adapter type"):
        get_adapter("FOO", config_path=config_path)


def test_get_adapter_unknown_market_type_raises(tmp_path: Path):
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        "personas:\n"
        "  FOO:\n"
        "    adapter: internal_ledger\n"
        "    market: forex\n"
        "market_data:\n"
        "  key_id_env: ALPACA_MARKET_DATA_KEY_ID\n"
        "  secret_key_env: ALPACA_MARKET_DATA_SECRET_KEY\n"
    )

    with pytest.raises(ValueError, match="Unknown market type"):
        get_adapter("FOO", config_path=config_path)
