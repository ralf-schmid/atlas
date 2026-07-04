"""Load config/risk.yaml and config/personas/<name>.yaml into typed dataclasses."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.risk.models import (
    PersonaGuardrails,
    StopLossPolicy,
    StopLossPolicyType,
    SystemGuardrails,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RISK_CONFIG_PATH = _REPO_ROOT / "config" / "risk.yaml"
_DEFAULT_PERSONAS_DIR = _REPO_ROOT / "config" / "personas"


def load_system_guardrails(path: Path = _DEFAULT_RISK_CONFIG_PATH) -> SystemGuardrails:
    raw = yaml.safe_load(path.read_text())
    return SystemGuardrails(
        circuit_breaker_drawdown_pct=raw["circuit_breaker_drawdown_pct"],
        allow_margin=raw["allow_margin"],
        allow_short=raw["allow_short"],
        require_stop_loss=raw["require_stop_loss"],
        max_position_pct_ceiling=raw["max_position_pct_ceiling"],
        max_trades_per_day_ceiling=raw["max_trades_per_day_ceiling"],
        max_open_positions_ceiling=raw["max_open_positions_ceiling"],
        min_cash_pct_floor=raw["min_cash_pct_floor"],
    )


def load_persona_guardrails(
    persona: str, personas_dir: Path = _DEFAULT_PERSONAS_DIR
) -> PersonaGuardrails:
    path = personas_dir / f"{persona.lower()}.yaml"
    if not path.exists():
        raise ValueError(f"No persona config found for {persona!r} at {path}")

    raw = yaml.safe_load(path.read_text())
    policy_raw = raw["stop_loss_policy"]
    stop_loss_policy = StopLossPolicy(
        type=StopLossPolicyType(policy_raw["type"]),
        max_loss_pct=policy_raw.get("max_loss_pct"),
        atr_multiplier=policy_raw.get("atr_multiplier"),
        min_loss_pct=policy_raw.get("min_loss_pct"),
    )
    return PersonaGuardrails(
        name=raw["name"],
        max_position_pct=raw["max_position_pct"],
        max_trades_per_day=raw["max_trades_per_day"],
        max_open_positions=raw["max_open_positions"],
        min_cash_pct=raw["min_cash_pct"],
        stop_loss_policy=stop_loss_policy,
    )
