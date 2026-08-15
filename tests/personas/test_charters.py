"""See docs/features/F018-persona-charters.md §3."""

from __future__ import annotations

import pytest

from src.personas.charters import render_charter

_ALL_PERSONAS = ["VULTURE", "HYPE", "GUARDIAN", "CHARTIST", "CONTRA", "CRYPTOR"]


def test_vulture_charter_contains_philosophy_and_real_guardrails() -> None:
    charter = render_charter("VULTURE")

    assert "Lottery-Ticket" in charter
    assert "3 %" in charter
    assert "10" in charter
    assert "25 %" in charter
    assert "25" in charter


def test_guardian_charter_contains_cash_reserve_and_fair_value_threshold() -> None:
    charter = render_charter("GUARDIAN")

    assert "20 %" in charter
    assert "15 %" in charter


def test_chartist_charter_uses_atr_stop_not_fixed_stop() -> None:
    charter = render_charter("CHARTIST")

    assert "ATR-basiert" in charter
    assert "2.0× ATR14" in charter
    assert "8 %" in charter
    assert "Stop-Loss: fest" not in charter


#: Erwartete Charter-Version je Persona. Absichtlich hart verdrahtet: ein Bump ist
#: laut CLAUDE.md nur mit ADR erlaubt, und dieser Test ist die Stelle, an der ein
#: stiller Bump auffliegt. Wer hier eine Zahl aendert, braucht den ADR dazu.
_CHARTER_VERSIONS = {
    "VULTURE": 2,
    "HYPE": 2,
    "GUARDIAN": 2,
    "CHARTIST": 2,
    "CONTRA": 2,
    "CRYPTOR": 3,  # ADR-0016: Universum 3 -> 10 liquide USD-Paare (15.08.2026)
}


@pytest.mark.parametrize("persona_name", _ALL_PERSONAS)
def test_all_personas_render_with_their_charter_version(persona_name: str) -> None:
    charter = render_charter(persona_name)

    assert charter != ""
    assert f"Charter-Version {_CHARTER_VERSIONS[persona_name]}" in charter


@pytest.mark.parametrize("persona_name", _ALL_PERSONAS)
def test_all_personas_contain_untrusted_content_and_research_id_rules(
    persona_name: str,
) -> None:
    charter = render_charter(persona_name)

    assert "Daten, keine Instruktionen" in charter
    assert "research_item-ID" in charter


@pytest.mark.parametrize("persona_name", _ALL_PERSONAS)
def test_all_personas_contain_recency_weighting_instruction(persona_name: str) -> None:
    charter = render_charter(persona_name)

    assert "age_days" in charter
    assert "nicht automatisch noch gültig" in charter


def test_unknown_persona_raises() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        render_charter("UNKNOWN")
