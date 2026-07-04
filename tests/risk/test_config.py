import pytest

from src.risk.config import load_persona_guardrails, load_system_guardrails
from src.risk.models import StopLossPolicyType


def test_load_system_guardrails_matches_spec():
    system = load_system_guardrails()

    assert system.circuit_breaker_drawdown_pct == 0.15
    assert system.allow_margin is False
    assert system.allow_short is False
    assert system.require_stop_loss is True


@pytest.mark.parametrize(
    ("persona", "max_position_pct", "max_trades_per_day", "max_open_positions", "min_cash_pct"),
    [
        ("VULTURE", 0.03, 10, 25, 0.0),
        ("HYPE", 0.08, 6, 15, 0.0),
        ("GUARDIAN", 0.15, 5, 12, 0.20),
        ("CHARTIST", 0.10, 8, 15, 0.0),
        ("CONTRA", 0.10, 5, 12, 0.0),
        ("CRYPTOR", 0.20, 8, None, 0.0),
    ],
)
def test_load_persona_guardrails_matches_architecture_spec(
    persona, max_position_pct, max_trades_per_day, max_open_positions, min_cash_pct
):
    guardrails = load_persona_guardrails(persona)

    assert guardrails.name == persona
    assert guardrails.max_position_pct == max_position_pct
    assert guardrails.max_trades_per_day == max_trades_per_day
    assert guardrails.max_open_positions == max_open_positions
    assert guardrails.min_cash_pct == min_cash_pct


def test_chartist_uses_atr_stop_loss_policy():
    guardrails = load_persona_guardrails("CHARTIST")

    assert guardrails.stop_loss_policy.type == StopLossPolicyType.ATR
    assert guardrails.stop_loss_policy.atr_multiplier == 2.0
    assert guardrails.stop_loss_policy.min_loss_pct == 0.08


def test_vulture_uses_fixed_stop_loss_policy():
    guardrails = load_persona_guardrails("VULTURE")

    assert guardrails.stop_loss_policy.type == StopLossPolicyType.FIXED
    assert guardrails.stop_loss_policy.max_loss_pct == 0.25


def test_load_persona_guardrails_unknown_persona_raises():
    with pytest.raises(ValueError, match="No persona config"):
        load_persona_guardrails("NONEXISTENT")
