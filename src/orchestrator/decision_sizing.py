"""Pure arithmetic: turns an LLM-supplied conviction (0-1, no dollar amounts) plus
persona guardrails into concrete Risk-Gate inputs. See
docs/features/F021-persona-analysis-agent.md §1 ("Sizing-Formel").

Deliberately not part of the Risk-Gate itself (src.risk.gate) — this proposes a
number for the gate to check, it doesn't decide anything.
"""

from __future__ import annotations

from src.risk.models import StopLossPolicy, StopLossPolicyType


def compute_position_value_usd(
    conviction: float, max_position_pct: float, equity_usd: float
) -> float:
    clamped = max(0.0, min(1.0, conviction))
    return clamped * max_position_pct * equity_usd


def compute_incremental_buy_value_usd(
    target_position_value_usd: float, existing_position_value_usd: float
) -> float:
    """F071: `compute_position_value_usd` returns the *total* position value a
    persona's conviction should reach (F021 §1: "conviction=1.0 -> exakt die
    persona-eigene Obergrenze ausgeschöpft, nie mehr") — it says nothing about
    what's already held. A persona that repeatedly proposes `buy` on an
    instrument it already holds (changed probabilities, a new impulse) must
    only buy the remaining gap up to that target, never the full target again,
    or the position silently overshoots the intended size. Floored at 0: an
    existing position already at or above the target means nothing to buy.
    """
    return max(0.0, target_position_value_usd - existing_position_value_usd)


def round_to_tick(price: float) -> float:
    """Alpaca rejects stop/limit prices that don't fulfil its sub-penny rule: at or
    above $1.00 the price must be a $0.01 increment, below $1.00 a $0.0001 increment
    is allowed. Live-confirmed 2026-07-10 (F050): raw ATR-derived floats like
    290.8672 came back as `422 sub-penny increment does not fulfill minimum pricing
    criteria` — every BUY decision's stop-loss failed at the broker, silently
    stalling at status=APPROVED with no order ever placed. Also applied defensively
    in `src.orchestrator.trading.execute_decision` right before the broker call, to
    cover decisions persisted before this fix existed."""
    return round(price, 2) if price >= 1.0 else round(price, 4)


def compute_stop_loss_price(
    entry_price: float, policy: StopLossPolicy, atr14: float | None
) -> float | None:
    if policy.type == StopLossPolicyType.FIXED:
        assert policy.max_loss_pct is not None
        return round_to_tick(entry_price * (1 - policy.max_loss_pct))

    if atr14 is None:
        return None
    assert policy.atr_multiplier is not None
    assert policy.min_loss_pct is not None
    atr_stop_pct = policy.atr_multiplier * atr14 / entry_price
    floor_pct = max(atr_stop_pct, policy.min_loss_pct)
    return round_to_tick(entry_price * (1 - floor_pct))
