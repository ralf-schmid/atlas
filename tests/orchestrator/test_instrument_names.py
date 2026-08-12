"""F107: plain-text company name -> tradable symbol.

The false-positive tests matter more than the hit tests here: a wrong instrument tag
points a persona at a symbol the text never discussed, which is worse than no tag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.orchestrator.instrument_names import load_instrument_aliases, match_instruments

ALIASES = {
    "Berkshire Hathaway": "BRK.B",
    "Berkshire": "BRK.B",
    "Meta Platforms": "META",
    "Alphabet": "GOOGL",
    "Bitcoin": "BTC/USD",
}


def test_matches_a_company_name_in_prose() -> None:
    text = "Berkshire Hathaway investierte im zweiten Quartal wieder in Aktien."

    assert match_instruments(text, ALIASES) == ["BRK.B"]


def test_reports_each_company_once_even_with_several_aliases() -> None:
    """ "Berkshire" and "Berkshire Hathaway" are the same company — the longer alias
    wins and the symbol appears once."""
    text = "Berkshire Hathaway kauft zu. Berkshire hält weiter viel Cash."

    assert match_instruments(text, ALIASES) == ["BRK.B"]


def test_orders_symbols_by_first_appearance() -> None:
    text = "Zuerst Alphabet, dann Berkshire Hathaway, zuletzt Bitcoin."

    assert match_instruments(text, ALIASES) == ["GOOGL", "BRK.B", "BTC/USD"]


def test_requires_word_boundaries() -> None:
    """Substring matching would tag "Alphabetisierung" as Alphabet."""
    text = "Die Alphabetisierung stieg, und Bitcoinbörsen sind kein Bitcoin."

    assert match_instruments(text, ALIASES) == ["BTC/USD"]  # only the standalone word


def test_is_case_sensitive_to_keep_everyday_words_out() -> None:
    """German prose is full of words that only differ from a company name by their
    capitalisation — case sensitivity is what keeps them out (F107 §2)."""
    assert match_instruments("Auf der meta platforms Ebene", ALIASES) == []
    assert match_instruments("Meta Platforms kauft ein", ALIASES) == ["META"]


def test_empty_inputs_yield_nothing() -> None:
    assert match_instruments("", ALIASES) == []
    assert match_instruments("Berkshire Hathaway", {}) == []


def test_live_config_is_loadable_and_maps_known_names() -> None:
    """The real file, not a fixture — an alias dropped in config/instrument_names.yaml
    has to fail here rather than silently stop tagging."""
    aliases = load_instrument_aliases()

    assert aliases["Berkshire Hathaway"] == "BRK.B"
    assert aliases["Eli Lilly"] == "LLY"
    assert aliases["Bitcoin"] == "BTC/USD"


def test_live_config_holds_no_collision_prone_short_aliases() -> None:
    for alias in load_instrument_aliases():
        assert len(alias) >= 4, alias


def test_short_alias_is_rejected_loudly(tmp_path: Path) -> None:
    """Silently skipping it would later look like a matching bug."""
    config = tmp_path / "instrument_names.yaml"
    config.write_text("aliases:\n  BP: BP\n  Alphabet: GOOGL\n")

    with pytest.raises(ValueError, match="BP"):
        load_instrument_aliases(config)
