import pytest

from src.telegram.commands import (
    PersonaStatus,
    format_status_message,
    parse_hitl_command,
    parse_persona_command,
)


def test_parse_persona_command_extracts_persona():
    assert parse_persona_command("/pause VULTURE", "pause") == "VULTURE"


def test_parse_persona_command_uppercases_persona():
    assert parse_persona_command("/pause vulture", "pause") == "VULTURE"


def test_parse_persona_command_missing_argument_raises():
    with pytest.raises(ValueError, match="Usage: /pause"):
        parse_persona_command("/pause", "pause")


def test_parse_persona_command_wrong_command_raises():
    with pytest.raises(ValueError, match="Usage: /resume"):
        parse_persona_command("/pause VULTURE", "resume")


def test_parse_hitl_command_on():
    assert parse_hitl_command("/hitl on") is True


def test_parse_hitl_command_off():
    assert parse_hitl_command("/hitl off") is False


def test_parse_hitl_command_invalid_value_raises():
    with pytest.raises(ValueError, match="Usage: /hitl on|off"):
        parse_hitl_command("/hitl maybe")


def test_parse_hitl_command_missing_argument_raises():
    with pytest.raises(ValueError, match="Usage: /hitl on|off"):
        parse_hitl_command("/hitl")


def test_format_status_message_includes_all_personas():
    statuses = [
        PersonaStatus(name="VULTURE", active=True, portfolio_value_usd=5200.0, open_positions=3),
        PersonaStatus(name="GUARDIAN", active=False, portfolio_value_usd=4950.0, open_positions=1),
    ]

    message = format_status_message(statuses)

    assert "VULTURE (aktiv): $5,200.00, 3 Positionen" in message
    assert "GUARDIAN (pausiert): $4,950.00, 1 Positionen" in message
