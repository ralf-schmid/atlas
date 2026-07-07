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


def compute_stop_loss_price(
    entry_price: float, policy: StopLossPolicy, atr14: float | None
) -> float | None:
    if policy.type == StopLossPolicyType.FIXED:
        assert policy.max_loss_pct is not None
        return entry_price * (1 - policy.max_loss_pct)

    if atr14 is None:
        return None
    assert policy.atr_multiplier is not None
    assert policy.min_loss_pct is not None
    atr_stop_pct = policy.atr_multiplier * atr14 / entry_price
    floor_pct = max(atr_stop_pct, policy.min_loss_pct)
    return entry_price * (1 - floor_pct)
