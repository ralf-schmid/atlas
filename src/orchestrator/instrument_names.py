"""Plain-text company names -> tradable symbols. See docs/features/F107.

Newsletters and magazine articles name companies in prose ("Berkshire Hathaway kauft
zu"), not as `$TICKER`. Without this, those impulses reach the pool with an empty
`instruments` list — present, but invisible to the per-symbol search (F045) and
unattachable to a position.

Deliberately a curated map in `config/instrument_names.yaml` rather than a derived
index over Alpaca's ~11k assets: a name index that broad turns ordinary words into
false instrument references, and a wrong tag is worse than a missing one — it points
a persona at a symbol the text never discussed.

Same list for every persona and every source (Invariant #10). No LLM: matching is a
word-boundary scan, deterministic and unit-tested.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "instrument_names.yaml"

# Shorter aliases collide with ordinary words far too often ("BP", "HD", "KO" all read
# as prose in German). Tickers that short belong in the per-newsletter `ticker_map`,
# which only matches the `$BP` form.
_MIN_ALIAS_CHARS = 4


def load_instrument_aliases(config_path: Path = _DEFAULT_CONFIG_PATH) -> dict[str, str]:
    """Returns alias -> symbol. Raises on an alias below the length floor, rather than
    skipping it silently: a rejected entry the curator never hears about would look
    like a matching bug later."""
    raw = yaml.safe_load(config_path.read_text()) or {}
    aliases: dict[str, str] = dict(raw.get("aliases", {}))
    too_short = sorted(alias for alias in aliases if len(alias) < _MIN_ALIAS_CHARS)
    if too_short:
        raise ValueError(
            f"instrument_names.yaml: aliases shorter than {_MIN_ALIAS_CHARS} characters "
            f"are too collision-prone: {too_short}"
        )
    return aliases


def match_instruments(text: str, aliases: dict[str, str]) -> list[str]:
    """Symbols whose alias appears in `text`, in order of first appearance.

    Case-sensitive on purpose (F107 §2): company names are always capitalised, so this
    is what keeps "Meta-Ebene" or "ein Block" from becoming an instrument reference.
    Longest alias first, so "Meta Platforms" wins over a shorter alias contained in it
    and one company is never counted twice.
    """
    if not text or not aliases:
        return []

    hits: list[tuple[int, str]] = []
    matched_symbols: set[str] = set()
    for alias in sorted(aliases, key=len, reverse=True):
        symbol = aliases[alias]
        if symbol in matched_symbols:
            continue
        match = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
        if match is not None:
            hits.append((match.start(), symbol))
            matched_symbols.add(symbol)

    return [symbol for _, symbol in sorted(hits)]
