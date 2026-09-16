"""F122 (Phase 6 preparation): the dormant live adapter and the two gates in front
of it. Nothing here trades — every Alpaca client is patched out."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.broker.alpaca_live import AlpacaLiveAdapter
from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.registry import adapter_mode, get_adapter, validate_all_credentials

_LIVE_CONFIG = (
    "personas:\n"
    "  WINNER:\n"
    "    adapter: alpaca_live\n"
    "    key_id_env: ALPACA_LIVE_WINNER_KEY_ID\n"
    "    secret_key_env: ALPACA_LIVE_WINNER_SECRET_KEY\n"
    "market_data:\n"
    "  key_id_env: ALPACA_MARKET_DATA_KEY_ID\n"
    "  secret_key_env: ALPACA_MARKET_DATA_SECRET_KEY\n"
)


@pytest.fixture
def live_config(tmp_path: Path) -> Path:
    path = tmp_path / "broker.yaml"
    path.write_text(_LIVE_CONFIG)
    return path


@pytest.fixture
def live_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE_WINNER_KEY_ID", "live-key-id")
    monkeypatch.setenv("ALPACA_LIVE_WINNER_SECRET_KEY", "live-secret-key")
    monkeypatch.setenv("ALPACA_MARKET_DATA_KEY_ID", "md-key-id")
    monkeypatch.setenv("ALPACA_MARKET_DATA_SECRET_KEY", "md-secret-key")


def test_live_adapter_talks_to_the_live_endpoint() -> None:
    with patch("src.broker.alpaca_paper.TradingClient") as client:
        AlpacaLiveAdapter(api_key="k", secret_key="s")

    assert client.call_args.kwargs["paper"] is False


def test_paper_adapter_stays_on_the_paper_endpoint() -> None:
    with patch("src.broker.alpaca_paper.TradingClient") as client:
        AlpacaPaperAdapter(api_key="k", secret_key="s")

    assert client.call_args.kwargs["paper"] is True


def test_live_adapter_inherits_the_proven_order_path() -> None:
    """The whole point of the subclass: identical behaviour, one different flag."""
    assert AlpacaLiveAdapter.place_order is AlpacaPaperAdapter.place_order
    assert AlpacaLiveAdapter.close_position is AlpacaPaperAdapter.close_position
    assert AlpacaLiveAdapter.requires_whole_shares is True


def test_live_adapter_is_refused_without_the_explicit_flag(
    live_config: Path, live_keys, monkeypatch
) -> None:
    """Invariant #5: an `adapter: alpaca_live` entry plus live keys is not enough."""
    monkeypatch.delenv("ATLAS_LIVE_TRADING_ENABLED", raising=False)

    with pytest.raises(ValueError, match="ATLAS_LIVE_TRADING_ENABLED"):
        get_adapter("WINNER", config_path=live_config)


def test_live_adapter_is_refused_when_the_flag_is_not_true(
    live_config: Path, live_keys, monkeypatch
) -> None:
    monkeypatch.setenv("ATLAS_LIVE_TRADING_ENABLED", "1")

    with pytest.raises(ValueError, match="ATLAS_LIVE_TRADING_ENABLED"):
        get_adapter("WINNER", config_path=live_config)


def test_live_adapter_is_built_once_phase_6_enables_it(
    live_config: Path, live_keys, monkeypatch
) -> None:
    monkeypatch.setenv("ATLAS_LIVE_TRADING_ENABLED", "true")

    with patch("src.broker.alpaca_paper.TradingClient"):
        adapter = get_adapter("WINNER", config_path=live_config)

    assert isinstance(adapter, AlpacaLiveAdapter)


def test_validate_all_credentials_covers_a_live_persona(
    live_config: Path, live_keys, monkeypatch
) -> None:
    monkeypatch.setenv("ATLAS_LIVE_TRADING_ENABLED", "true")

    with (
        patch("src.broker.alpaca_paper.TradingClient") as trading_client,
        patch("src.broker.market_data.StockHistoricalDataClient"),
    ):
        validate_all_credentials(config_path=live_config)

    trading_client.return_value.get_account.assert_called_once()


def test_validate_all_credentials_refuses_a_live_persona_without_the_flag(
    live_config: Path, live_keys, monkeypatch
) -> None:
    monkeypatch.delenv("ATLAS_LIVE_TRADING_ENABLED", raising=False)

    with pytest.raises(ValueError, match="ATLAS_LIVE_TRADING_ENABLED"):
        validate_all_credentials(config_path=live_config)


@pytest.mark.parametrize(
    ("adapter_type", "mode"),
    [("alpaca_paper", "paper"), ("internal_ledger", "paper"), ("alpaca_live", "live")],
)
def test_adapter_mode_maps_every_adapter_type(adapter_type: str, mode: str) -> None:
    assert adapter_mode(adapter_type) == mode


def test_adapter_mode_rejects_an_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown adapter type"):
        adapter_mode("kraken")
