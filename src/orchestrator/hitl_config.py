"""Loads config/hitl.yaml — HITL on/off per mode, ARCHITECTURE.md §5.3. See
docs/features/F022-hitl-flow.md.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.db.models import PortfolioMode

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "hitl.yaml"


def is_hitl_required(mode: PortfolioMode, path: Path = _DEFAULT_CONFIG_PATH) -> bool:
    raw = yaml.safe_load(path.read_text())
    return bool(raw[mode.value])
