"""Load config/llm.yaml — routing + cost-cap config. See F006."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.yaml"


@dataclass(frozen=True, slots=True)
class RoleConfig:
    name: str
    model: str
    provider: str
    shared: bool
    prompt_caching: bool


@dataclass(frozen=True, slots=True)
class CostCaps:
    system_daily_usd: float
    persona_daily_usd: float
    monthly_soft_cap_usd: float
    monthly_soft_cap_warn_pct: float


@dataclass(frozen=True, slots=True)
class LlmConfig:
    base_url: str
    caps: CostCaps
    roles: dict[str, RoleConfig]


def load_llm_config(path: Path = _DEFAULT_CONFIG_PATH) -> LlmConfig:
    raw = yaml.safe_load(path.read_text())
    caps_raw = raw["caps"]
    caps = CostCaps(
        system_daily_usd=caps_raw["system_daily_usd"],
        persona_daily_usd=caps_raw["persona_daily_usd"],
        monthly_soft_cap_usd=caps_raw["monthly_soft_cap_usd"],
        monthly_soft_cap_warn_pct=caps_raw["monthly_soft_cap_warn_pct"],
    )
    roles = {
        name: RoleConfig(
            name=name,
            model=role_raw["model"],
            provider=role_raw["provider"],
            shared=role_raw["shared"],
            prompt_caching=role_raw["prompt_caching"],
        )
        for name, role_raw in raw["roles"].items()
    }
    return LlmConfig(base_url=raw["base_url"], caps=caps, roles=roles)
