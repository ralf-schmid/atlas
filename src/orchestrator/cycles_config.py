"""Loads config/cycles.yaml — cycle times, ARCHITECTURE.md §5.2. See
docs/features/F025-cycle-scheduling.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "cycles.yaml"


@dataclass(frozen=True, slots=True)
class StockCycle:
    seq: int
    time: str  # "HH:MM"
    active: bool


@dataclass(frozen=True, slots=True)
class CyclesConfig:
    stock_timezone: str
    stock_cycles: list[StockCycle]
    crypto_timezone: str
    crypto_weekday_times: list[str]
    crypto_weekend_times: list[str]
    digest_time: str  # "HH:MM", America/New_York (stock_timezone) — F070


def load_cycles_config(path: Path = _DEFAULT_CONFIG_PATH) -> CyclesConfig:
    raw = yaml.safe_load(path.read_text())
    stock = raw["stock"]
    crypto = raw["crypto"]
    return CyclesConfig(
        stock_timezone=stock["timezone"],
        stock_cycles=[
            StockCycle(seq=c["seq"], time=c["time"], active=c["active"]) for c in stock["cycles"]
        ],
        crypto_timezone=crypto["timezone"],
        crypto_weekday_times=crypto["weekday_times"],
        crypto_weekend_times=crypto["weekend_times"],
        digest_time=raw["digest"]["time"],
    )
