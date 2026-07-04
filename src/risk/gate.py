"""The deterministic Risk-Gate. Pure function, no LLM, no IO — see F004 §1.

Invariant #1: this is the only place that decides whether a trade decision is
risk-approved. Callers pass in all portfolio/market state; this module never
reads a database or calls an API itself.
"""

from __future__ import annotations

from src.risk.models import (
    PersonaGuardrails,
    RiskCheckResult,
    StopLossPolicy,
    StopLossPolicyType,
    SystemGuardrails,
    TradeAction,
)


def evaluate_decision(
    *,
    action: TradeAction,
    position_value_usd: float,
    entry_price: float,
    stop_loss_price: float | None,
    atr14: float | None,
    portfolio_equity_usd: float,
    portfolio_cash_usd: float,
    portfolio_peak_equity_usd: float,
    open_positions_count: int,
    trades_today_count: int,
    system: SystemGuardrails,
    persona: PersonaGuardrails,
) -> RiskCheckResult:
    rules: dict[str, object] = {}
    reasons: list[str] = []

    drawdown = _drawdown(portfolio_peak_equity_usd, portfolio_equity_usd)
    circuit_breaker_triggered = drawdown > system.circuit_breaker_drawdown_pct
    rules["circuit_breaker"] = {
        "drawdown": drawdown,
        "threshold": system.circuit_breaker_drawdown_pct,
        "triggered": circuit_breaker_triggered,
    }
    if circuit_breaker_triggered and action == TradeAction.BUY:
        reasons.append("circuit_breaker_sell_only")

    max_trades_per_day = min(persona.max_trades_per_day, system.max_trades_per_day_ceiling)
    trade_count_ok = trades_today_count < max_trades_per_day
    rules["max_trades_per_day"] = {
        "trades_today": trades_today_count,
        "limit": max_trades_per_day,
        "ok": trade_count_ok,
    }
    if not trade_count_ok:
        reasons.append("max_trades_per_day_exceeded")

    if action == TradeAction.BUY:
        _evaluate_buy_only_rules(
            position_value_usd=position_value_usd,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            atr14=atr14,
            portfolio_equity_usd=portfolio_equity_usd,
            portfolio_cash_usd=portfolio_cash_usd,
            open_positions_count=open_positions_count,
            system=system,
            persona=persona,
            rules=rules,
            reasons=reasons,
        )

    return RiskCheckResult(
        approved=len(reasons) == 0, rejection_reasons=reasons, rules_evaluated=rules
    )


def _evaluate_buy_only_rules(
    *,
    position_value_usd: float,
    entry_price: float,
    stop_loss_price: float | None,
    atr14: float | None,
    portfolio_equity_usd: float,
    portfolio_cash_usd: float,
    open_positions_count: int,
    system: SystemGuardrails,
    persona: PersonaGuardrails,
    rules: dict[str, object],
    reasons: list[str],
) -> None:
    margin_ok = system.allow_margin or position_value_usd <= portfolio_cash_usd
    rules["no_margin"] = {
        "position_value_usd": position_value_usd,
        "cash_usd": portfolio_cash_usd,
        "ok": margin_ok,
    }
    if not margin_ok:
        reasons.append("insufficient_cash_no_margin")

    max_position_pct = min(persona.max_position_pct, system.max_position_pct_ceiling)
    position_pct = (
        position_value_usd / portfolio_equity_usd if portfolio_equity_usd > 0 else float("inf")
    )
    position_size_ok = position_pct <= max_position_pct
    rules["max_position_pct"] = {
        "position_pct": position_pct,
        "limit": max_position_pct,
        "ok": position_size_ok,
    }
    if not position_size_ok:
        reasons.append("max_position_pct_exceeded")

    persona_open_cap = (
        persona.max_open_positions
        if persona.max_open_positions is not None
        else system.max_open_positions_ceiling
    )
    max_open_positions = min(persona_open_cap, system.max_open_positions_ceiling)
    open_positions_ok = open_positions_count < max_open_positions
    rules["max_open_positions"] = {
        "count": open_positions_count,
        "limit": max_open_positions,
        "ok": open_positions_ok,
    }
    if not open_positions_ok:
        reasons.append("max_open_positions_exceeded")

    min_cash_pct = max(persona.min_cash_pct, system.min_cash_pct_floor)
    remaining_cash_pct = (
        (portfolio_cash_usd - position_value_usd) / portfolio_equity_usd
        if portfolio_equity_usd > 0
        else 0.0
    )
    cash_reserve_ok = remaining_cash_pct >= min_cash_pct
    rules["min_cash_pct"] = {
        "remaining_cash_pct": remaining_cash_pct,
        "limit": min_cash_pct,
        "ok": cash_reserve_ok,
    }
    if not cash_reserve_ok:
        reasons.append("min_cash_pct_violated")

    stop_loss_present = stop_loss_price is not None and stop_loss_price > 0
    rules["stop_loss_required"] = {
        "present": stop_loss_present,
        "required": system.require_stop_loss,
    }
    if system.require_stop_loss and not stop_loss_present:
        reasons.append("missing_stop_loss")
    elif stop_loss_present:
        assert stop_loss_price is not None
        direction_ok = stop_loss_price < entry_price
        rules["stop_loss_direction"] = {
            "stop_loss_price": stop_loss_price,
            "entry_price": entry_price,
            "ok": direction_ok,
        }
        if not direction_ok:
            reasons.append("stop_loss_invalid_direction")
        else:
            policy_ok, detail = _check_stop_loss_policy(
                persona.stop_loss_policy, entry_price, stop_loss_price, atr14
            )
            rules["stop_loss_policy"] = detail
            if not policy_ok:
                reasons.append(str(detail["reason"]))


def _drawdown(peak_equity_usd: float, current_equity_usd: float) -> float:
    if peak_equity_usd <= 0:
        return 0.0
    return (peak_equity_usd - current_equity_usd) / peak_equity_usd


def _check_stop_loss_policy(
    policy: StopLossPolicy, entry_price: float, stop_loss_price: float, atr14: float | None
) -> tuple[bool, dict[str, object]]:
    actual_loss_pct = (entry_price - stop_loss_price) / entry_price

    if policy.type == StopLossPolicyType.FIXED:
        assert policy.max_loss_pct is not None
        ok = actual_loss_pct <= policy.max_loss_pct
        return ok, {
            "type": "fixed",
            "actual_loss_pct": actual_loss_pct,
            "max_loss_pct": policy.max_loss_pct,
            "ok": ok,
            "reason": "stop_loss_too_wide",
        }

    # ATR-based policy (CHARTIST) — stop distance floor, see F004 §2.
    if atr14 is None:
        return False, {"type": "atr", "ok": False, "reason": "atr_required_but_missing"}

    assert policy.atr_multiplier is not None
    assert policy.min_loss_pct is not None
    atr_stop_pct = policy.atr_multiplier * atr14 / entry_price
    floor_pct = max(atr_stop_pct, policy.min_loss_pct)
    ok = actual_loss_pct >= floor_pct - 1e-9
    return ok, {
        "type": "atr",
        "actual_loss_pct": actual_loss_pct,
        "atr_stop_pct": atr_stop_pct,
        "floor_pct": floor_pct,
        "ok": ok,
        "reason": "stop_loss_too_tight",
    }
