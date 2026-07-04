"""Resolve persona -> BrokerAdapter instance via config/broker.yaml + environment.

See docs/adr/0001-alpaca-paper-account-limit.md for the native/virtual split.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.internal_ledger import InternalLedgerAdapter
from src.broker.ledger_store import JSONLedgerStore
from src.broker.market_data import (
    AlpacaCryptoMarketDataProvider,
    AlpacaStockMarketDataProvider,
    MarketDataProvider,
)
from src.broker.protocol import BrokerAdapter

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "broker.yaml"
_STARTING_CASH = 5000.0  # parity with native accounts, see docs/adr/0003


def get_adapter(persona: str, config_path: Path = _DEFAULT_CONFIG_PATH) -> BrokerAdapter:
    config = yaml.safe_load(config_path.read_text())
    personas = config["personas"]

    if persona not in personas:
        raise ValueError(f"Unknown persona: {persona!r}. Known personas: {sorted(personas)}")

    entry = personas[persona]
    adapter_type = entry["adapter"]

    if adapter_type == "alpaca_paper":
        key_id = _require_env(entry["key_id_env"])
        secret_key = _require_env(entry["secret_key_env"])
        return AlpacaPaperAdapter(api_key=key_id, secret_key=secret_key)

    if adapter_type == "internal_ledger":
        market_data = _build_market_data_provider(entry["market"], config["market_data"])
        return InternalLedgerAdapter(
            persona=persona,
            market_data=market_data,
            store=JSONLedgerStore(),
            starting_cash=_STARTING_CASH,
        )

    raise ValueError(f"Unknown adapter type {adapter_type!r} for persona {persona!r}")


def _build_market_data_provider(
    market: str, market_data_config: dict[str, str]
) -> MarketDataProvider:
    key_id = _require_env(market_data_config["key_id_env"])
    secret_key = _require_env(market_data_config["secret_key_env"])

    if market == "stock":
        return AlpacaStockMarketDataProvider(api_key=key_id, secret_key=secret_key)
    if market == "crypto":
        return AlpacaCryptoMarketDataProvider(api_key=key_id, secret_key=secret_key)
    raise ValueError(f"Unknown market type {market!r}")


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
