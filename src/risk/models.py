"""Data types for the deterministic Risk-Gate. See docs/features/F004-risk-gate.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StopLossPolicyType(StrEnum):
    FIXED = "fixed"
    ATR = "atr"


class TradeAction(StrEnum):
    """Only the decision.action values that can reach the Risk-Gate — `hold` and
    `reject_idea` never produce an order and never call evaluate_decision()."""

    BUY = "buy"
    SELL = "sell"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class StopLossPolicy:
    type: StopLossPolicyType
    max_loss_pct: float | None = None  # required for FIXED
    atr_multiplier: float | None = None  # required for ATR
    min_loss_pct: float | None = None  # required for ATR

    def __post_init__(self) -> None:
        """Fail at config-load time, not at decision time (and never silently under
        `python -O`, which would strip a plain assert in the gate)."""
        if self.type == StopLossPolicyType.FIXED and self.max_loss_pct is None:
            raise ValueError("stop_loss_policy 'fixed' requires max_loss_pct")
        if self.type == StopLossPolicyType.ATR and self.atr_multiplier is None:
            raise ValueError("stop_loss_policy 'atr' requires atr_multiplier")
        if self.type == StopLossPolicyType.ATR and self.min_loss_pct is None:
            raise ValueError("stop_loss_policy 'atr' requires min_loss_pct")


@dataclass(frozen=True, slots=True)
class SystemGuardrails:
    circuit_breaker_drawdown_pct: float
    allow_margin: bool
    allow_short: bool
    require_stop_loss: bool
    max_position_pct_ceiling: float
    max_trades_per_day_ceiling: int
    max_open_positions_ceiling: int
    min_cash_pct_floor: float


@dataclass(frozen=True, slots=True)
class PersonaGuardrails:
    name: str
    max_position_pct: float
    max_trades_per_day: int
    max_open_positions: int | None  # None = no persona-specific cap, use system ceiling only
    min_cash_pct: float
    stop_loss_policy: StopLossPolicy


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    approved: bool
    rejection_reasons: list[str] = field(default_factory=list)
    rules_evaluated: dict[str, object] = field(default_factory=dict)
