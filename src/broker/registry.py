"""Resolve persona -> BrokerAdapter instance via config/broker.yaml + environment.

See docs/adr/0001-alpaca-paper-account-limit.md for the native/virtual split.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.protocol import BrokerAdapter

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "broker.yaml"


def get_adapter(persona: str, config_path: Path = _DEFAULT_CONFIG_PATH) -> BrokerAdapter:
    personas = yaml.safe_load(config_path.read_text())["personas"]

    if persona not in personas:
        raise ValueError(f"Unknown persona: {persona!r}. Known personas: {sorted(personas)}")

    entry = personas[persona]
    adapter_type = entry["adapter"]

    if adapter_type == "alpaca_paper":
        key_id = _require_env(entry["key_id_env"])
        secret_key = _require_env(entry["secret_key_env"])
        return AlpacaPaperAdapter(api_key=key_id, secret_key=secret_key)

    if adapter_type == "internal_ledger":
        raise NotImplementedError(
            f"Persona {persona!r} is configured for 'internal_ledger', but "
            "InternalLedgerAdapter does not exist yet (separate feature, see "
            "docs/adr/0001-alpaca-paper-account-limit.md)."
        )

    raise ValueError(f"Unknown adapter type {adapter_type!r} for persona {persona!r}")


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
