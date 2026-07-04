"""Orchestrator-side cost brake — independent of LiteLLM's own per-key budgets
(Invariant #7: "doppelt durchgesetzt", ARCHITECTURE.md §6.3). Pure functions,
no IO — the caller sums `cost_ledger` and passes the total in.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.llm.config import CostCaps


class BudgetStatus(enum.Enum):
    OK = "ok"
    WARN = "warn"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    status: BudgetStatus
    spent_usd: float
    cap_usd: float
    pct_used: float


def check_system_budget(spent_today_usd: float, caps: CostCaps) -> BudgetCheck:
    return _check_hard_cap(spent_today_usd, caps.system_daily_usd)


def check_persona_budget(spent_today_usd: float, caps: CostCaps) -> BudgetCheck:
    return _check_hard_cap(spent_today_usd, caps.persona_daily_usd)


def check_monthly_soft_cap(spent_month_usd: float, caps: CostCaps) -> BudgetCheck:
    """Soft cap: only ever `ok`/`warn`, never `blocked` (§6.3)."""
    pct_used = _pct_used(spent_month_usd, caps.monthly_soft_cap_usd)
    status = BudgetStatus.WARN if pct_used >= caps.monthly_soft_cap_warn_pct else BudgetStatus.OK
    return BudgetCheck(
        status=status,
        spent_usd=spent_month_usd,
        cap_usd=caps.monthly_soft_cap_usd,
        pct_used=pct_used,
    )


def _check_hard_cap(spent_usd: float, cap_usd: float, warn_pct: float = 0.8) -> BudgetCheck:
    pct_used = _pct_used(spent_usd, cap_usd)
    if pct_used >= 1.0:
        status = BudgetStatus.BLOCKED
    elif pct_used >= warn_pct:
        status = BudgetStatus.WARN
    else:
        status = BudgetStatus.OK
    return BudgetCheck(status=status, spent_usd=spent_usd, cap_usd=cap_usd, pct_used=pct_used)


def _pct_used(spent_usd: float, cap_usd: float) -> float:
    return spent_usd / cap_usd if cap_usd > 0 else 0.0
