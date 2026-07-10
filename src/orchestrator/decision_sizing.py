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


def _round_to_tick(price: float) -> float:
    """Alpaca rejects stop/limit prices that don't fulfil its sub-penny rule: at or
    above $1.00 the price must be a $0.01 increment, below $1.00 a $0.0001 increment
    is allowed. Live-confirmed 2026-07-10 (F050): raw ATR-derived floats like
    290.8672 came back as `422 sub-penny increment does not fulfill minimum pricing
    criteria` — every BUY decision's stop-loss failed at the broker, silently
    stalling at status=APPROVED with no order ever placed."""
    return round(price, 2) if price >= 1.0 else round(price, 4)


def compute_stop_loss_price(
    entry_price: float, policy: StopLossPolicy, atr14: float | None
) -> float | None:
    if policy.type == StopLossPolicyType.FIXED:
        assert policy.max_loss_pct is not None
        return _round_to_tick(entry_price * (1 - policy.max_loss_pct))

    if atr14 is None:
        return None
    assert policy.atr_multiplier is not None
    assert policy.min_loss_pct is not None
    atr_stop_pct = policy.atr_multiplier * atr14 / entry_price
    floor_pct = max(atr_stop_pct, policy.min_loss_pct)
    return _round_to_tick(entry_price * (1 - floor_pct))
