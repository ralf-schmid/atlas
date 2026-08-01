"""Load config/llm.yaml — routing + cost-cap config. See F006."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
class ResearchAgentsConfig:
    """F095 budget knobs for the two shared research roles.

    Lives here rather than next to the agents themselves so `LlmConfig` can carry it
    without `src/llm` importing from `src/orchestrator`. `enabled: false` restores
    the pre-F095 behaviour exactly — the deterministic synthesis pass is untouched —
    and is the documented rollback path.
    """

    enabled: bool
    news_max_items_per_cycle: int
    news_batch_size: int
    market_enabled: bool

    @classmethod
    def from_raw(cls, raw: object) -> ResearchAgentsConfig:
        values = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=bool(values.get("enabled", False)),
            news_max_items_per_cycle=int(values.get("news_max_items_per_cycle", 200)),
            news_batch_size=int(values.get("news_batch_size", 25)),
            market_enabled=bool(values.get("market_enabled", True)),
        )


@dataclass(frozen=True, slots=True)
class ReviewConfig:
    """F084 knobs. `enabled: false` is the rollback path — already-written reviews
    stay, they are pure data and harm nothing."""

    enabled: bool
    max_reviews_per_run: int
    intermediate_after_days: int

    @classmethod
    def from_raw(cls, raw: object) -> ReviewConfig:
        values = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=bool(values.get("enabled", False)),
            max_reviews_per_run=int(values.get("max_reviews_per_run", 10)),
            intermediate_after_days=int(values.get("intermediate_after_days", 14)),
        )


@dataclass(frozen=True, slots=True)
class MetaReviewConfig:
    """F099 knobs. Same rollback contract as `ReviewConfig`: `enabled: false` stops
    future runs, written meta-reviews stay.

    `max_per_run` is the §5.2 sample size (max. 5/Woche) and the only cost brake
    that matters here — the sweep fires weekly, so per-run == per-week.
    """

    enabled: bool
    max_per_run: int

    @classmethod
    def from_raw(cls, raw: object) -> MetaReviewConfig:
        values = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=bool(values.get("enabled", False)),
            max_per_run=int(values.get("max_per_run", 5)),
        )


@dataclass(frozen=True, slots=True)
class LlmConfig:
    base_url: str
    caps: CostCaps
    roles: dict[str, RoleConfig]
    research_agents: ResearchAgentsConfig = field(
        # Missing section = feature off, so an older config file keeps working.
        default_factory=lambda: ResearchAgentsConfig.from_raw(None)
    )
    review: ReviewConfig = field(default_factory=lambda: ReviewConfig.from_raw(None))
    meta_review: MetaReviewConfig = field(default_factory=lambda: MetaReviewConfig.from_raw(None))


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
    # config/llm.yaml's base_url is "http://localhost:4000", correct for scripts run
    # on the host (port-forwarded LiteLLM) but unreachable from inside a container's
    # own network namespace — the scheduler container overrides it via this env var
    # to reach the litellm service by its Compose DNS name.
    base_url = os.environ.get("LITELLM_BASE_URL", raw["base_url"])
    return LlmConfig(
        base_url=base_url,
        caps=caps,
        roles=roles,
        research_agents=ResearchAgentsConfig.from_raw(raw.get("research_agents")),
        review=ReviewConfig.from_raw(raw.get("review")),
        meta_review=MetaReviewConfig.from_raw(raw.get("meta_review")),
    )
