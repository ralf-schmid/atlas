"""See docs/features/F021-persona-analysis-agent.md §3, tests 5-8. Pure arithmetic,
no DB needed (this directory's conftest opts every module into the real-Postgres
schema, but these tests simply don't touch a session)."""

from __future__ import annotations

import pytest

from src.orchestrator.decision_sizing import (
    compute_incremental_buy_value_usd,
    compute_position_value_usd,
    compute_stop_loss_price,
)
from src.risk.models import StopLossPolicy, StopLossPolicyType


def test_compute_position_value_usd_full_conviction() -> None:
    value = compute_position_value_usd(1.0, 0.03, 5000.0)

    assert value == pytest.approx(150.0)


def test_compute_position_value_usd_half_conviction() -> None:
    value = compute_position_value_usd(0.5, 0.03, 5000.0)

    assert value == pytest.approx(75.0)


def test_compute_incremental_buy_value_usd_with_no_existing_position() -> None:
    value = compute_incremental_buy_value_usd(150.0, 0.0)

    assert value == pytest.approx(150.0)


def test_compute_incremental_buy_value_usd_tops_up_the_remaining_gap() -> None:
    # already holding 50 of a 150 target -> only the missing 100 should be bought
    value = compute_incremental_buy_value_usd(150.0, 50.0)

    assert value == pytest.approx(100.0)


def test_compute_incremental_buy_value_usd_floors_at_zero_when_already_at_target() -> None:
    value = compute_incremental_buy_value_usd(150.0, 150.0)

    assert value == 0.0


def test_compute_incremental_buy_value_usd_floors_at_zero_when_above_target() -> None:
    # e.g. price appreciation pushed the existing position above the current target
    value = compute_incremental_buy_value_usd(150.0, 200.0)

    assert value == 0.0


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


def test_compute_stop_loss_price_rounds_to_cent_at_or_above_one_dollar() -> None:
    # Live incident 2026-07-10 (F050): AAPL entry 296.78 with ATR14 2.9565 produced
    # a raw stop of 290.8672 — Alpaca rejects that as a sub-penny increment.
    policy = StopLossPolicy(type=StopLossPolicyType.ATR, atr_multiplier=2.0, min_loss_pct=0.02)

    stop = compute_stop_loss_price(296.78, policy, atr14=2.9565)

    assert stop is not None
    assert stop == round(stop, 2)


def test_fixed_stop_loss_rounds_up_so_the_loss_cap_holds() -> None:
    # F101 live case: CONTRA/AUPH entry 14.86, 15 % cap -> raw stop 12.631. Nearest
    # rounding gave 12.63 = 15.007 % loss and the gate rejected its own decision.
    policy = StopLossPolicy(type=StopLossPolicyType.FIXED, max_loss_pct=0.15)

    stop = compute_stop_loss_price(14.86, policy, None)

    assert stop == pytest.approx(12.64)
    assert (14.86 - stop) / 14.86 <= 0.15


def test_atr_stop_loss_rounds_down_so_the_distance_floor_holds() -> None:
    # F101 live case: CHARTIST/ADSK entry 234.31, ATR floor 8.2684 % -> raw stop
    # 214.9364. Nearest rounding gave 214.94 = 8.2668 %, just under the floor.
    policy = StopLossPolicy(type=StopLossPolicyType.ATR, atr_multiplier=2.0, min_loss_pct=0.02)
    atr14 = 0.0826835 * 234.31 / 2.0

    stop = compute_stop_loss_price(234.31, policy, atr14=atr14)

    assert stop == pytest.approx(214.93)
    assert (234.31 - stop) / 234.31 >= 0.0826835


def test_compute_stop_loss_price_allows_sub_penny_below_one_dollar() -> None:
    # Alpaca permits $0.0001 increments below $1.00 — penny-stock stops must not
    # get rounded down to 2 decimals (that would distort the intended stop%).
    policy = StopLossPolicy(type=StopLossPolicyType.ATR, atr_multiplier=2.0, min_loss_pct=0.08)

    stop = compute_stop_loss_price(0.85, policy, atr14=0.02)

    assert stop is not None
    assert stop == round(stop, 4)
