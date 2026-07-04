import pytest

from src.llm.config import CostCaps
from src.llm.cost_guard import (
    BudgetStatus,
    check_monthly_soft_cap,
    check_persona_budget,
    check_system_budget,
)


@pytest.fixture
def caps() -> CostCaps:
    return CostCaps(
        system_daily_usd=5.0,
        persona_daily_usd=1.0,
        monthly_soft_cap_usd=120.0,
        monthly_soft_cap_warn_pct=0.8,
    )


def test_system_budget_ok_below_80_pct(caps):
    result = check_system_budget(3.0, caps)  # 60%

    assert result.status == BudgetStatus.OK


def test_system_budget_warn_between_80_and_100_pct(caps):
    result = check_system_budget(4.5, caps)  # 90%

    assert result.status == BudgetStatus.WARN


def test_system_budget_blocked_at_100_pct(caps):
    result = check_system_budget(5.0, caps)  # exactly 100%

    assert result.status == BudgetStatus.BLOCKED


def test_system_budget_blocked_above_100_pct(caps):
    result = check_system_budget(6.0, caps)

    assert result.status == BudgetStatus.BLOCKED


def test_system_budget_warn_exactly_at_80_pct(caps):
    result = check_system_budget(4.0, caps)  # exactly 80%

    assert result.status == BudgetStatus.WARN


def test_persona_budget_uses_persona_cap(caps):
    result = check_persona_budget(0.9, caps)  # 90% of 1.0

    assert result.status == BudgetStatus.WARN
    assert result.cap_usd == 1.0


def test_monthly_soft_cap_ok_below_80_pct(caps):
    result = check_monthly_soft_cap(50.0, caps)  # ~42%

    assert result.status == BudgetStatus.OK


def test_monthly_soft_cap_warn_at_80_pct(caps):
    result = check_monthly_soft_cap(96.0, caps)  # exactly 80%

    assert result.status == BudgetStatus.WARN


def test_monthly_soft_cap_never_blocks_even_above_100_pct(caps):
    result = check_monthly_soft_cap(200.0, caps)

    assert result.status == BudgetStatus.WARN
