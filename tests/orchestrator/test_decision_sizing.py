"""See docs/features/F021-persona-analysis-agent.md §3, tests 5-8. Pure arithmetic,
no DB needed (this directory's conftest opts every module into the real-Postgres
schema, but these tests simply don't touch a session)."""

from __future__ import annotations

import pytest

from src.orchestrator.decision_sizing import compute_position_value_usd, compute_stop_loss_price
from src.risk.models import StopLossPolicy, StopLossPolicyType


def test_compute_position_value_usd_full_conviction() -> None:
    value = compute_position_value_usd(1.0, 0.03, 5000.0)

    assert value == pytest.approx(150.0)


def test_compute_position_value_usd_half_conviction() -> None:
    value = compute_position_value_usd(0.5, 0.03, 5000.0)

    assert value == pytest.approx(75.0)


def test_compute_stop_loss_price_fixed_policy() -> None:
    policy = StopLossPolicy(type=StopLossPolicyType.FIXED, max_loss_pct=0.25)

    stop = compute_stop_loss_price(100.0, policy, None)

    assert stop == pytest.approx(75.0)


def test_compute_stop_loss_price_atr_policy() -> None:
    policy = StopLossPolicy(type=StopLossPolicyType.ATR, atr_multiplier=2.0, min_loss_pct=0.08)

    stop = compute_stop_loss_price(100.0, policy, atr14=5.0)

    # atr_stop_pct = 2.0*5/100 = 0.10, floor_pct = max(0.10, 0.08) = 0.10
    assert stop == pytest.approx(90.0)


def test_compute_stop_loss_price_atr_policy_without_atr_returns_none() -> None:
    policy = StopLossPolicy(type=StopLossPolicyType.ATR, atr_multiplier=2.0, min_loss_pct=0.08)

    stop = compute_stop_loss_price(100.0, policy, atr14=None)

    assert stop is None
