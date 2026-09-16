"""Resolve persona -> BrokerAdapter instance via config/broker.yaml + environment.

See docs/adr/0001-alpaca-paper-account-limit.md for the native/virtual split.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.broker.alpaca_live import AlpacaLiveAdapter
from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.internal_ledger import InternalLedgerAdapter
from src.broker.ledger_store import JSONLedgerStore
from src.broker.market_data import (
    AlpacaCryptoMarketDataProvider,
    AlpacaStockMarketDataProvider,
    SpreadProvider,
)
from src.broker.protocol import BrokerAdapter

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "broker.yaml"
_STARTING_CASH = 5000.0  # parity with native accounts, see docs/adr/0003

# F122 (Phase 6 preparation): which trading mode an adapter type belongs to. The
# strings are `PortfolioMode` values — src/broker deliberately does not import the
# DB layer, and the one caller that compares the two (`src.orchestrator.trading`)
# has both at hand.
ADAPTER_MODES = {
    "alpaca_paper": "paper",
    "internal_ledger": "paper",
    "alpaca_live": "live",
}

# Invariant #5: live trading is never one config typo away. Even with an
# `adapter: alpaca_live` entry and live keys in the environment, this flag has to
# be set deliberately for the live adapter to be constructed at all.
_LIVE_TRADING_FLAG = "ATLAS_LIVE_TRADING_ENABLED"


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

    if adapter_type == "alpaca_live":
        _require_live_trading_enabled(persona)
        key_id = _require_env(entry["key_id_env"])
        secret_key = _require_env(entry["secret_key_env"])
        return AlpacaLiveAdapter(api_key=key_id, secret_key=secret_key)

    if adapter_type == "internal_ledger":
        market_data = build_market_data_provider(entry["market"], config["market_data"])
        return InternalLedgerAdapter(
            persona=persona,
            market_data=market_data,
            store=JSONLedgerStore(),
            starting_cash=_STARTING_CASH,
        )

    raise ValueError(f"Unknown adapter type {adapter_type!r} for persona {persona!r}")


def adapter_mode(adapter_type: str) -> str:
    """The `portfolio.mode` value an adapter type may serve — see
    `src.orchestrator.trading.execute_decision`, which refuses to place an order
    when the portfolio and its adapter disagree (Invariant #5)."""
    try:
        return ADAPTER_MODES[adapter_type]
    except KeyError:
        raise ValueError(f"Unknown adapter type {adapter_type!r}") from None


def _require_live_trading_enabled(persona: str) -> None:
    if os.environ.get(_LIVE_TRADING_FLAG, "").lower() != "true":
        raise ValueError(
            f"Persona {persona!r} is configured for live trading, but "
            f"{_LIVE_TRADING_FLAG} is not set to 'true'. Live trading is enabled "
            "deliberately (Phase 6, ARCHITECTURE.md §8), never as a side effect of "
            "a config edit."
        )


def get_adapter_type(persona: str, config_path: Path = _DEFAULT_CONFIG_PATH) -> str:
    """Just the adapter type string (e.g. "alpaca_paper") — used for `order_record.broker`,
    which shouldn't need to construct a real adapter to know this."""
    config = yaml.safe_load(config_path.read_text())
    personas = config["personas"]
    if persona not in personas:
        raise ValueError(f"Unknown persona: {persona!r}. Known personas: {sorted(personas)}")
    return str(personas[persona]["adapter"])


def load_market_data_config(config_path: Path = _DEFAULT_CONFIG_PATH) -> dict[str, str]:
    """F074: lets the chart endpoint (`src/api/routes.py`) build a live-price
    `MarketDataProvider` without duplicating the `config/broker.yaml` -> dict lookup
    `get_adapter` already does inline."""
    config = yaml.safe_load(config_path.read_text())
    return dict(config["market_data"])


def load_market_data_credentials(config_path: Path = _DEFAULT_CONFIG_PATH) -> tuple[str, str]:
    """F124: the resolved (key_id, secret_key) of the shared market-data key, for
    callers that need an Alpaca client this module doesn't build — the trading
    calendar uses a `TradingClient`, not a market-data client. Keeps env-var
    resolution in the one module that owns it (Invariant #6)."""
    market_data = load_market_data_config(config_path)
    return _require_env(market_data["key_id_env"]), _require_env(market_data["secret_key_env"])


def build_market_data_provider(
    market: str, market_data_config: dict[str, str]
) -> AlpacaStockMarketDataProvider | AlpacaCryptoMarketDataProvider:
    """Returns the concrete provider, not just the `MarketDataProvider` protocol:
    both classes also satisfy `SpreadProvider` (F104), and naming them here lets
    `build_spread_provider` reuse this without a narrowing assert."""
    key_id = _require_env(market_data_config["key_id_env"])
    secret_key = _require_env(market_data_config["secret_key_env"])

    if market == "stock":
        return AlpacaStockMarketDataProvider(api_key=key_id, secret_key=secret_key)
    if market == "crypto":
        return AlpacaCryptoMarketDataProvider(api_key=key_id, secret_key=secret_key)
    raise ValueError(f"Unknown market type {market!r}")


def build_spread_provider(market: str, config_path: Path = _DEFAULT_CONFIG_PATH) -> SpreadProvider:
    """F104: same shared market-data key as `build_market_data_provider` — the
    quote behind the slippage malus must be identical for every persona
    (Invariant #10)."""
    return build_market_data_provider(market, load_market_data_config(config_path))


def validate_market_data_credentials(config_path: Path = _DEFAULT_CONFIG_PATH) -> None:
    """F092: validate only the shared market-data key. Called by the ingestion
    market-data sync job on each run (not just at startup), so a key that expires
    mid-deployment is caught before the next StockBarsRequest, not after."""
    config = yaml.safe_load(config_path.read_text())
    stock_provider = build_market_data_provider("stock", config["market_data"])
    stock_provider.validate_credentials()


def validate_all_credentials(config_path: Path = _DEFAULT_CONFIG_PATH) -> None:
    """F092: validate ALL configured Alpaca keys at startup. Raises on the first
    invalid key — the caller should exit with a clear message.

    Personas with `internal_ledger` adapter are skipped (no external credentials);
    a live persona is validated the same way once Phase 6 configures one.
    Market data credentials are validated against both stock and crypto endpoints
    (same key, different API client).
    """
    config = yaml.safe_load(config_path.read_text())
    personas = config["personas"]

    for persona, entry in sorted(personas.items()):
        adapter_class = _ALPACA_ADAPTERS.get(entry["adapter"])
        if adapter_class is None:
            continue
        if adapter_class is AlpacaLiveAdapter:
            _require_live_trading_enabled(persona)
        key_id = _require_env(entry["key_id_env"])
        secret_key = _require_env(entry["secret_key_env"])
        adapter_class(api_key=key_id, secret_key=secret_key).validate_credentials()

    market_data = config["market_data"]
    stock_provider = build_market_data_provider("stock", market_data)
    stock_provider.validate_credentials()


_ALPACA_ADAPTERS: dict[str, type[AlpacaPaperAdapter]] = {
    "alpaca_paper": AlpacaPaperAdapter,
    "alpaca_live": AlpacaLiveAdapter,
}


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
