import dataclasses

from src.risk.gate import evaluate_decision
from src.risk.models import TradeAction


def _evaluate(system, persona, base_buy_kwargs, action=TradeAction.BUY, **overrides):
    kwargs = {**base_buy_kwargs, **overrides}
    return evaluate_decision(action=action, system=system, persona=persona, **kwargs)


# --- Happy path -------------------------------------------------------------


def test_buy_within_all_limits_is_approved(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs)

    assert result.approved is True
    assert result.rejection_reasons == []
    assert all(
        rule.get("ok", True) is not False
        for rule in result.rules_evaluated.values()
        if isinstance(rule, dict)
    )


# --- Circuit breaker ---------------------------------------------------------


def test_circuit_breaker_blocks_buy_when_drawdown_exceeds_threshold(
    system, persona_fixed, base_buy_kwargs
):
    result = _evaluate(
        system,
        persona_fixed,
        base_buy_kwargs,
        portfolio_peak_equity_usd=50_000.0,
        portfolio_equity_usd=40_000.0,  # 20% drawdown > 15% threshold
    )

    assert result.approved is False
    assert "circuit_breaker_sell_only" in result.rejection_reasons


def test_circuit_breaker_does_not_block_sell(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(
        system,
        persona_fixed,
        base_buy_kwargs,
        action=TradeAction.SELL,
        portfolio_peak_equity_usd=50_000.0,
        portfolio_equity_usd=40_000.0,
    )

    assert "circuit_breaker_sell_only" not in result.rejection_reasons


def test_circuit_breaker_does_not_block_close(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(
        system,
        persona_fixed,
        base_buy_kwargs,
        action=TradeAction.CLOSE,
        portfolio_peak_equity_usd=50_000.0,
        portfolio_equity_usd=40_000.0,
    )

    assert "circuit_breaker_sell_only" not in result.rejection_reasons


def test_drawdown_is_zero_when_peak_equity_is_zero(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(
        system, persona_fixed, base_buy_kwargs, portfolio_peak_equity_usd=0.0
    )

    assert result.rules_evaluated["circuit_breaker"]["drawdown"] == 0.0
    assert "circuit_breaker_sell_only" not in result.rejection_reasons


def test_drawdown_exactly_at_threshold_does_not_trigger(
    system, persona_fixed, base_buy_kwargs
):
    # 15% drawdown == threshold, not strictly greater -> not triggered
    result = _evaluate(
        system,
        persona_fixed,
        base_buy_kwargs,
        portfolio_peak_equity_usd=100_000.0,
        portfolio_equity_usd=85_000.0,
    )

    assert "circuit_breaker_sell_only" not in result.rejection_reasons


# --- Trade count (applies to buy and sell) -----------------------------------


def test_trade_count_exceeded_blocks_buy(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, trades_today_count=10)

    assert "max_trades_per_day_exceeded" in result.rejection_reasons


def test_trade_count_exceeded_blocks_sell(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(
        system, persona_fixed, base_buy_kwargs, action=TradeAction.SELL, trades_today_count=10
    )

    assert "max_trades_per_day_exceeded" in result.rejection_reasons


def test_trade_count_one_below_limit_is_ok(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, trades_today_count=9)

    assert "max_trades_per_day_exceeded" not in result.rejection_reasons


def test_trade_count_uses_stricter_of_persona_and_system_ceiling(
    system, persona_fixed, base_buy_kwargs
):
    strict_system = dataclasses.replace(system, max_trades_per_day_ceiling=5)

    result = _evaluate(strict_system, persona_fixed, base_buy_kwargs, trades_today_count=5)

    assert "max_trades_per_day_exceeded" in result.rejection_reasons


# --- No margin ----------------------------------------------------------------


def test_buy_exceeding_cash_is_rejected_when_margin_disallowed(
    system, persona_fixed, base_buy_kwargs
):
    result = _evaluate(
        system,
        persona_fixed,
        base_buy_kwargs,
        position_value_usd=6_000.0,
        portfolio_cash_usd=5_000.0,
    )

    assert "insufficient_cash_no_margin" in result.rejection_reasons


def test_buy_exceeding_cash_is_allowed_when_margin_allowed(
    system, persona_fixed, base_buy_kwargs
):
    margin_system = dataclasses.replace(system, allow_margin=True)

    result = _evaluate(
        margin_system,
        persona_fixed,
        base_buy_kwargs,
        position_value_usd=6_000.0,
        portfolio_cash_usd=5_000.0,
    )

    assert "insufficient_cash_no_margin" not in result.rejection_reasons


# --- Position size ------------------------------------------------------------


def test_position_pct_exceeding_persona_limit_is_rejected(
    system, persona_fixed, base_buy_kwargs
):
    # persona_fixed.max_position_pct == 0.03 -> 3% of 50_000 == 1_500
    result = _evaluate(system, persona_fixed, base_buy_kwargs, position_value_usd=2_000.0)

    assert "max_position_pct_exceeded" in result.rejection_reasons


def test_position_pct_exactly_at_limit_is_allowed(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, position_value_usd=1_500.0)

    assert "max_position_pct_exceeded" not in result.rejection_reasons


def test_position_pct_uses_stricter_system_ceiling(system, persona_fixed, base_buy_kwargs):
    strict_system = dataclasses.replace(system, max_position_pct_ceiling=0.01)

    result = _evaluate(strict_system, persona_fixed, base_buy_kwargs, position_value_usd=750.0)

    assert "max_position_pct_exceeded" in result.rejection_reasons


def test_position_pct_is_infinite_when_equity_is_zero(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, portfolio_equity_usd=0.0)

    assert result.rules_evaluated["max_position_pct"]["position_pct"] == float("inf")
    assert "max_position_pct_exceeded" in result.rejection_reasons


# --- Open positions ------------------------------------------------------------


def test_open_positions_at_persona_limit_is_rejected(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, open_positions_count=25)

    assert "max_open_positions_exceeded" in result.rejection_reasons


def test_open_positions_one_below_limit_is_allowed(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, open_positions_count=24)

    assert "max_open_positions_exceeded" not in result.rejection_reasons


def test_open_positions_none_falls_back_to_system_ceiling(
    system, persona_no_open_cap, base_buy_kwargs
):
    result = _evaluate(
        system,
        persona_no_open_cap,
        base_buy_kwargs,
        open_positions_count=system.max_open_positions_ceiling,
    )

    ceiling = system.max_open_positions_ceiling
    assert result.rules_evaluated["max_open_positions"]["limit"] == ceiling
    assert "max_open_positions_exceeded" in result.rejection_reasons


# --- Min cash reserve -----------------------------------------------------------


def test_min_cash_reserve_violated_is_rejected(system, persona_min_cash, base_buy_kwargs):
    # 20% of 50_000 == 10_000 must remain; cash=5_000, position=1_000 -> remaining 4_000
    result = _evaluate(system, persona_min_cash, base_buy_kwargs)

    assert "min_cash_pct_violated" in result.rejection_reasons


def test_min_cash_reserve_satisfied_is_allowed(system, persona_min_cash, base_buy_kwargs):
    result = _evaluate(
        system,
        persona_min_cash,
        base_buy_kwargs,
        portfolio_cash_usd=40_000.0,
        position_value_usd=1_000.0,
    )

    assert "min_cash_pct_violated" not in result.rejection_reasons


def test_min_cash_reserve_zero_when_equity_is_zero(system, persona_min_cash, base_buy_kwargs):
    result = _evaluate(system, persona_min_cash, base_buy_kwargs, portfolio_equity_usd=0.0)

    assert result.rules_evaluated["min_cash_pct"]["remaining_cash_pct"] == 0.0


# --- Stop-loss required / direction ---------------------------------------------


def test_missing_stop_loss_is_rejected_when_required(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=None)

    assert "missing_stop_loss" in result.rejection_reasons


def test_missing_stop_loss_is_allowed_when_not_required(
    system, persona_fixed, base_buy_kwargs
):
    lenient_system = dataclasses.replace(system, require_stop_loss=False)

    result = _evaluate(lenient_system, persona_fixed, base_buy_kwargs, stop_loss_price=None)

    assert "missing_stop_loss" not in result.rejection_reasons
    assert "stop_loss_direction" not in result.rules_evaluated
    assert "stop_loss_policy" not in result.rules_evaluated


def test_zero_stop_loss_price_counts_as_missing(system, persona_fixed, base_buy_kwargs):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=0.0)

    assert "missing_stop_loss" in result.rejection_reasons


def test_stop_loss_above_entry_price_is_invalid_direction(
    system, persona_fixed, base_buy_kwargs
):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=110.0)

    assert "stop_loss_invalid_direction" in result.rejection_reasons
    assert "stop_loss_policy" not in result.rules_evaluated


def test_stop_loss_equal_to_entry_price_is_invalid_direction(
    system, persona_fixed, base_buy_kwargs
):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=100.0)

    assert "stop_loss_invalid_direction" in result.rejection_reasons


# --- Stop-loss policy: fixed -----------------------------------------------------


def test_fixed_stop_loss_wider_than_ceiling_is_rejected(
    system, persona_fixed, base_buy_kwargs
):
    # persona_fixed.max_loss_pct == 0.25 -> stop below 75.0 is too wide
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=70.0)

    assert "stop_loss_too_wide" in result.rejection_reasons


def test_fixed_stop_loss_exactly_at_ceiling_is_allowed(
    system, persona_fixed, base_buy_kwargs
):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=75.0)

    assert "stop_loss_too_wide" not in result.rejection_reasons


def test_fixed_stop_loss_tighter_than_ceiling_is_allowed(
    system, persona_fixed, base_buy_kwargs
):
    result = _evaluate(system, persona_fixed, base_buy_kwargs, stop_loss_price=95.0)

    assert "stop_loss_too_wide" not in result.rejection_reasons


# --- Stop-loss policy: ATR --------------------------------------------------------


def test_atr_stop_loss_missing_atr14_is_rejected(system, persona_atr, base_buy_kwargs):
    result = _evaluate(system, persona_atr, base_buy_kwargs, atr14=None)

    assert "atr_required_but_missing" in result.rejection_reasons


def test_atr_stop_loss_tighter_than_floor_is_rejected(system, persona_atr, base_buy_kwargs):
    # atr14=1.0 -> atr_stop_pct = 2*1/100 = 2%; floor = max(2%, 8%) = 8% -> stop must be <= 92.0
    result = _evaluate(system, persona_atr, base_buy_kwargs, atr14=1.0, stop_loss_price=95.0)

    assert "stop_loss_too_tight" in result.rejection_reasons


def test_atr_stop_loss_exactly_at_min_floor_is_allowed(system, persona_atr, base_buy_kwargs):
    result = _evaluate(system, persona_atr, base_buy_kwargs, atr14=1.0, stop_loss_price=92.0)

    assert "stop_loss_too_tight" not in result.rejection_reasons


def test_atr_stop_loss_wider_than_min_floor_via_high_atr_is_allowed(
    system, persona_atr, base_buy_kwargs
):
    # atr14=10 -> atr_stop_pct = 20% > 8% floor -> floor becomes 20%, stop must be <= 80.0
    result = _evaluate(system, persona_atr, base_buy_kwargs, atr14=10.0, stop_loss_price=79.0)

    assert "stop_loss_too_tight" not in result.rejection_reasons


def test_atr_stop_loss_tighter_than_high_atr_floor_is_rejected(
    system, persona_atr, base_buy_kwargs
):
    # atr14=10 -> floor 20%, stop at 85.0 implies only 15% loss -> too tight
    result = _evaluate(system, persona_atr, base_buy_kwargs, atr14=10.0, stop_loss_price=85.0)

    assert "stop_loss_too_tight" in result.rejection_reasons


# --- Multiple simultaneous violations ----------------------------------------------


def test_multiple_rule_violations_all_appear_in_rejection_reasons(
    system, persona_min_cash, base_buy_kwargs
):
    result = _evaluate(
        system,
        persona_min_cash,
        base_buy_kwargs,
        trades_today_count=5,  # persona_min_cash limit
        open_positions_count=12,  # persona_min_cash limit
        position_value_usd=10_000.0,  # exceeds 15% of 50_000 == 7_500
    )

    assert result.approved is False
    assert "max_trades_per_day_exceeded" in result.rejection_reasons
    assert "max_open_positions_exceeded" in result.rejection_reasons
    assert "max_position_pct_exceeded" in result.rejection_reasons
    assert "min_cash_pct_violated" in result.rejection_reasons
