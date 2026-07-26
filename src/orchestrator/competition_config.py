"""Loads config/competition.yaml — competition start date, capital, and SPY
benchmark settings. See docs/features/F081-spy-benchmark-portfolio.md §1.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "competition.yaml"


@dataclass(frozen=True, slots=True)
class CompetitionConfig:
    start_date: datetime.date
    start_capital_usd: int
    benchmark_enabled: bool
    benchmark_symbol: str


def load_competition_config(path: Path = _DEFAULT_CONFIG_PATH) -> CompetitionConfig:
    raw = yaml.safe_load(path.read_text()) or {}
    comp = raw.get("competition", {})
    bench = raw.get("benchmark", {})
    # YAML (safe_load) parses an unquoted ISO date like `2026-07-27` straight into a
    # datetime.date — only a quoted value arrives as str. Accept both so the config
    # works either way (date.fromisoformat rejects a date object).
    raw_start = comp["start_date"]
    start_date = (
        raw_start
        if isinstance(raw_start, datetime.date)
        else datetime.date.fromisoformat(raw_start)
    )
    return CompetitionConfig(
        start_date=start_date,
        start_capital_usd=int(comp.get("start_capital_usd", 5000)),
        benchmark_enabled=bench.get("enabled", True),
        benchmark_symbol=bench.get("benchmark_symbol", "SPY"),
    )
