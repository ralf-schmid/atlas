import pytest

from src.risk.models import (
    PersonaGuardrails,
    StopLossPolicy,
    StopLossPolicyType,
    SystemGuardrails,
)


@pytest.fixture
def system() -> SystemGuardrails:
    return SystemGuardrails(
        circuit_breaker_drawdown_pct=0.15,
        allow_margin=False,
        allow_short=False,
        require_stop_loss=True,
        max_position_pct_ceiling=0.25,
        max_trades_per_day_ceiling=15,
        max_open_positions_ceiling=30,
        min_cash_pct_floor=0.0,
    )


@pytest.fixture
def persona_fixed() -> PersonaGuardrails:
    """Mirrors VULTURE: fixed stop-loss policy, no min cash reserve."""
    return PersonaGuardrails(
        name="VULTURE",
        max_position_pct=0.03,
        max_trades_per_day=10,
        max_open_positions=25,
        min_cash_pct=0.0,
        stop_loss_policy=StopLossPolicy(type=StopLossPolicyType.FIXED, max_loss_pct=0.25),
    )


@pytest.fixture
def persona_min_cash() -> PersonaGuardrails:
    """Mirrors GUARDIAN: min cash reserve requirement."""
    return PersonaGuardrails(
        name="GUARDIAN",
        max_position_pct=0.15,
        max_trades_per_day=5,
        max_open_positions=12,
        min_cash_pct=0.20,
        stop_loss_policy=StopLossPolicy(type=StopLossPolicyType.FIXED, max_loss_pct=0.15),
    )


@pytest.fixture
def persona_atr() -> PersonaGuardrails:
    """Mirrors CHARTIST: ATR-based stop-loss floor."""
    return PersonaGuardrails(
        name="CHARTIST",
        max_position_pct=0.10,
        max_trades_per_day=8,
        max_open_positions=15,
        min_cash_pct=0.0,
        stop_loss_policy=StopLossPolicy(
            type=StopLossPolicyType.ATR, atr_multiplier=2.0, min_loss_pct=0.08
        ),
    )


@pytest.fixture
def persona_no_open_cap() -> PersonaGuardrails:
    """Mirrors CRYPTOR: max_open_positions=None, falls back to system ceiling."""
    return PersonaGuardrails(
        name="CRYPTOR",
        max_position_pct=0.20,
        max_trades_per_day=8,
        max_open_positions=None,
        min_cash_pct=0.0,
        stop_loss_policy=StopLossPolicy(type=StopLossPolicyType.FIXED, max_loss_pct=0.10),
    )


@pytest.fixture
def base_buy_kwargs() -> dict[str, object]:
    """A buy that should pass every rule under `persona_fixed` + `system`."""
    return dict(
        position_value_usd=1000.0,
        entry_price=100.0,
        stop_loss_price=90.0,
        atr14=None,
        portfolio_equity_usd=50_000.0,
        portfolio_cash_usd=5_000.0,
        portfolio_peak_equity_usd=50_000.0,
        open_positions_count=5,
        trades_today_count=2,
    )
