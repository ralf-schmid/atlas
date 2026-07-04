from pathlib import Path
from unittest.mock import patch

import pytest

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.registry import get_adapter


@pytest.fixture(autouse=True)
def _no_real_trading_client():
    with patch("src.broker.alpaca_paper.TradingClient"):
        yield


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


def test_get_adapter_virtual_persona_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="InternalLedgerAdapter"):
        get_adapter("HYPE")


def test_get_adapter_unknown_adapter_type_raises(tmp_path: Path):
    config_path = tmp_path / "broker.yaml"
    config_path.write_text("personas:\n  FOO:\n    adapter: something_else\n")

    with pytest.raises(ValueError, match="Unknown adapter type"):
        get_adapter("FOO", config_path=config_path)
