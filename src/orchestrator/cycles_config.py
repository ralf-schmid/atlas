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
    # F124: operator off-switch for the trading-calendar gate on the US equity
    # cycles. Defaults to `True` — the gate is the intended state, switching it
    # off has to be a deliberate line in config/cycles.yaml
    # (docs/adr/0019-handelskalender-gate-fail-open.md).
    stock_calendar_gate: bool = True


def load_cycles_config(path: Path = _DEFAULT_CONFIG_PATH) -> CyclesConfig:
    raw = yaml.safe_load(path.read_text())
    stock = raw["stock"]
    crypto = raw["crypto"]
    return CyclesConfig(
        stock_timezone=stock["timezone"],
        stock_cycles=[
            StockCycle(seq=c["seq"], time=c["time"], active=c["active"]) for c in stock["cycles"]
        ],
        stock_calendar_gate=bool(stock.get("calendar_gate", True)),
        crypto_timezone=crypto["timezone"],
        crypto_weekday_times=crypto["weekday_times"],
        crypto_weekend_times=crypto["weekend_times"],
        digest_time=raw["digest"]["time"],
    )
