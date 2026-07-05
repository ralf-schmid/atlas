"""Parsing/formatting for the bot commands from ARCHITECTURE.md §6.4:
/status, /pause <persona>, /resume <persona>, /hitl on|off, /digest.

Pure functions only — no DB access here (Folgearbeit once the persona/portfolio
state machine exists), so these are fully unit-testable without a live bot.
"""

from __future__ import annotations

from dataclasses import dataclass

KNOWN_PERSONAS = frozenset({"VULTURE", "HYPE", "GUARDIAN", "CHARTIST", "CONTRA", "CRYPTOR"})


def parse_persona_command(text: str, command_name: str) -> str:
    """Parses `/pause VULTURE` / `/resume VULTURE` -> "VULTURE"."""
    parts = text.strip().split()
    if len(parts) != 2 or parts[0].lstrip("/").lower() != command_name:
        raise ValueError(f"Usage: /{command_name} <PERSONA>")
    persona = parts[1].upper()
    if persona not in KNOWN_PERSONAS:
        raise ValueError(f"Unknown persona: {persona}. Known: {', '.join(sorted(KNOWN_PERSONAS))}")
    return persona


def parse_hitl_command(text: str) -> bool:
    """Parses `/hitl on` / `/hitl off` -> True/False."""
    parts = text.strip().split()
    if (
        len(parts) != 2
        or parts[0].lstrip("/").lower() != "hitl"
        or parts[1].lower()
        not in {
            "on",
            "off",
        }
    ):
        raise ValueError("Usage: /hitl on|off")
    return parts[1].lower() == "on"


@dataclass(frozen=True, slots=True)
class PersonaStatus:
    name: str
    active: bool
    portfolio_value_usd: float
    open_positions: int


def format_status_message(statuses: list[PersonaStatus]) -> str:
    lines = ["\U0001f4c8 Status"]
    for s in statuses:
        state = "aktiv" if s.active else "pausiert"
        lines.append(
            f"{s.name} ({state}): ${s.portfolio_value_usd:,.2f}, {s.open_positions} Positionen"
        )
    return "\n".join(lines)
