"""Loads/writes config/hitl.yaml — HITL on/off per mode, ARCHITECTURE.md §5.3. See
docs/features/F022-hitl-flow.md and F078 (the /hitl Telegram command actually
writing this file, not just replying as if it had).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from src.db.models import PortfolioMode

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "hitl.yaml"

# F078: a plain yaml.safe_load + yaml.safe_dump round-trip would silently drop
# every comment in config/hitl.yaml (including the Invariant #5 explanation of
# why `live` is never touched here) — a targeted line replacement keeps the rest
# of the file, comments included, byte-for-byte unchanged.
_MODE_LINE_PATTERN = {
    PortfolioMode.PAPER: re.compile(r"^paper:\s*\S+", re.MULTILINE),
    PortfolioMode.LIVE: re.compile(r"^live:\s*\S+", re.MULTILINE),
}


def is_hitl_required(mode: PortfolioMode, path: Path = _DEFAULT_CONFIG_PATH) -> bool:
    raw = yaml.safe_load(path.read_text())
    return bool(raw[mode.value])


def set_hitl_required(
    enabled: bool, mode: PortfolioMode = PortfolioMode.PAPER, path: Path = _DEFAULT_CONFIG_PATH
) -> None:
    """The only writer of config/hitl.yaml — Invariant #5: "die HITL-Schaltung ist
    Config (/hitl on|off), niemals hart codierte Umgehung." `mode` defaults to
    `PAPER`: the Telegram command (`src/telegram/bot.py::_handle_hitl`) never
    passes `LIVE` — `live` stays a deliberate manual file edit until Phase 6
    defines its own toggle logic, not something a chat command can flip.
    """
    text = path.read_text()
    pattern = _MODE_LINE_PATTERN[mode]
    if not pattern.search(text):
        raise ValueError(f"config/hitl.yaml has no {mode.value!r} line to update")
    new_text = pattern.sub(f"{mode.value}: {str(enabled).lower()}", text, count=1)
    path.write_text(new_text)
