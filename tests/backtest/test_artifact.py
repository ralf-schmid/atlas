"""Thresholds, caveats and scoring — F111 §8, tests 14-17 and 21."""

from __future__ import annotations

import datetime

import pytest

from src.backtest.artifact import (
    DISCLAIMER,
    FIXED_CAVEATS,
    Thresholds,
    attach_scores,
    build_payload,
    build_result,
    reference_return,
)
from src.backtest.engine import run_backtest
from src.db.models import BacktestRunStatus
from src.metrics.competition_score import CRITERION_WEIGHTS
from src.risk.config import load_system_guardrails
from tests.backtest.conftest import bar, day, engine_config, make_universe, simple_spec, write_spec

SYSTEM = load_system_guardrails()
THRESHOLDS = Thresholds(min_trading_days=60, min_trades=10)
LENIENT = Thresholds(min_trading_days=1, min_trades=0)


def _result(tmp_path, thresholds, *, days: int = 5, entries: int = 0):
    """A run over `days` trading days, forced to produce `entries` buys."""
    entry = [{"signal": "close", "op": "gt", "value": 100}]
    spec = simple_spec(tmp_path, entry=entry, max_position_pct=0.02)
    symbols = {
        f"S{index:02d}": [bar(offset, 105.0, open_=100.0) for offset in range(days + 1)]
        for index in range(max(entries, 1))
    }
    if entries == 0:
        symbols = {"AAA": [bar(offset, 50.0, open_=50.0) for offset in range(days + 1)]}
    universe = make_universe(symbols, first_day=day(1))
    engine_result = run_backtest(spec, universe, engine_config(), SYSTEM)
    return spec, universe, engine_result


def test_too_few_trading_days_is_insufficient_data(tmp_path):
    """Test 14."""
    spec, universe, engine_result = _result(tmp_path, THRESHOLDS, days=5, entries=20)
    result = build_result(spec, universe, engine_result, engine_config(), THRESHOLDS)

    assert result.status is BacktestRunStatus.INSUFFICIENT_DATA
    assert result.metrics["sortino"] is None
    assert result.metrics["competition_score"] is None
    assert any("insufficient_data" in caveat for caveat in result.caveats)


def test_too_few_trades_is_insufficient_data(tmp_path):
    """Test 15. Enough days, but almost nothing happened."""
    spec, universe, engine_result = _result(tmp_path, LENIENT, days=5, entries=0)
    thresholds = Thresholds(min_trading_days=1, min_trades=10)
    result = build_result(spec, universe, engine_result, engine_config(), thresholds)

    assert result.status is BacktestRunStatus.INSUFFICIENT_DATA
    assert result.metrics["entries"] == 0
    assert result.metrics["sortino"] is None
    assert any("Einstiege" in caveat for caveat in result.caveats)


def test_mandatory_caveats_and_disclaimer_are_always_present(tmp_path):
    """Test 16. Not conditional on the outcome — a good-looking backtest needs them
    more than a bad one."""
    spec, universe, engine_result = _result(tmp_path, LENIENT, days=5, entries=3)
    result = build_result(spec, universe, engine_result, engine_config(), LENIENT)

    for caveat in FIXED_CAVEATS:
        assert caveat in result.caveats
    payload = build_payload(result, universe, engine_config())
    assert payload["config"]["disclaimer"] == DISCLAIMER


def test_unmodelled_screen_criteria_are_named(tmp_path):
    """Test 17. VULTURE's market-cap screen cannot be represented from OHLCV bars; the
    caveat has to say so by name, not in general terms."""
    spec = write_spec(
        tmp_path,
        {
            "name": "vulture-like",
            "description": "test",
            "persona": "VULTURE",
            "screen_modelled": ["price_max", "daily_volume_min"],
            "screen_not_modelled": ["market_cap_max"],
            "universe": {"filters": []},
            "entry": [{"signal": "close", "op": "lt", "value": 5}],
        },
    )
    universe = make_universe(
        {"AAA": [bar(offset, 3.0, open_=3.0) for offset in range(6)]}, first_day=day(1)
    )
    engine_result = run_backtest(spec, universe, engine_config(), SYSTEM)
    result = build_result(spec, universe, engine_result, engine_config(), LENIENT)

    assert any("market_cap_max" in caveat for caveat in result.caveats)


def test_excluded_symbols_are_reported(tmp_path):
    spec, universe, engine_result = _result(tmp_path, LENIENT, days=5, entries=1)
    universe = make_universe(
        {"AAA": [bar(offset, 105.0, open_=100.0) for offset in range(6)]},
        first_day=day(1),
        excluded={"BAD": "price_level_break (factor 5.00 on 2026-01-09)"},
    )
    result = build_result(spec, universe, engine_result, engine_config(), LENIENT)

    assert any("Datenqualität" in caveat and "BAD" in caveat for caveat in result.caveats)


def test_an_empty_strategy_universe_says_so(tmp_path):
    """A strategy whose every symbol was filtered out must not report a bare zero:
    "no window" and "no signal" look identical in the numbers and are not the same
    finding (live-hit with CRYPTOR on 15.08.2026)."""
    spec = simple_spec(
        tmp_path, entry=[{"signal": "close", "op": "gt", "value": 1}], symbols=["GONE"]
    )
    universe = make_universe(
        {"AAA": [bar(offset, 105.0, open_=100.0) for offset in range(6)]},
        first_day=day(1),
        excluded={"GONE": "insufficient_warmup (30/60 bars before 2026-05-13)"},
    )
    engine_result = run_backtest(spec, universe, engine_config(), SYSTEM)
    result = build_result(spec, universe, engine_result, engine_config(), LENIENT)

    assert engine_result.trades == []
    assert any("Kein einziges Symbol" in caveat for caveat in result.caveats)
    assert any("--strategy test-spec" in caveat for caveat in result.caveats)


def test_score_drops_the_criteria_a_backtest_cannot_have(tmp_path):
    """Test 21. Thesis quality and operational reliability do not exist without
    reviews and agent_runs, so §4.7 must fall back to the three measurable criteria
    with their weights renormalised — 40/25/15 of 0.80 becomes 50/31.25/18.75 %."""
    results = []
    for index, name in enumerate(("alpha", "beta")):
        spec, universe, engine_result = _result(tmp_path, LENIENT, days=5, entries=2)
        object.__setattr__(spec, "name", name)
        result = build_result(spec, universe, engine_result, engine_config(), LENIENT)
        result.metrics["sortino"] = 1.0 + index
        result.metrics["return_net"] = 0.05 * (index + 1)
        result.metrics["max_drawdown"] = 0.10 * (index + 1)
        results.append(result)

    score = attach_scores(results)

    assert score is not None
    assert set(score.counted_criteria) == {"sortino", "adjusted_return", "max_drawdown"}
    assert set(score.skipped_criteria) == {"thesis_quality", "reliability"}
    weight_sum = sum(CRITERION_WEIGHTS[name] for name in score.counted_criteria)
    assert score.effective_weights["sortino"] == pytest.approx(0.40 / weight_sum)
    assert sum(score.effective_weights.values()) == pytest.approx(1.0)
    assert all(result.metrics["score_field"] == ["alpha", "beta"] for result in results)


def test_score_needs_a_field(tmp_path):
    """A single strategy has no field to be normalised against — min-max over one
    value would print 0.5 and look like a verdict."""
    spec, universe, engine_result = _result(tmp_path, LENIENT, days=5, entries=2)
    result = build_result(spec, universe, engine_result, engine_config(), LENIENT)

    assert attach_scores([result]) is None
    assert result.metrics["competition_score"] is None


def test_reference_return_is_a_price_line(tmp_path):
    universe = make_universe(
        {"SPY": [bar(offset, 100.0 + offset, open_=100.0) for offset in range(6)]},
        first_day=day(0),
    )
    assert reference_return(universe, "SPY") == pytest.approx(105.0 / 100.0 - 1)
    assert reference_return(universe, "NOPE") is None


def test_payload_carries_the_full_contract(tmp_path):
    """F111 §4: strategy_spec, config, fingerprint and caveats all travel with the
    numbers, or a later reader cannot tell what produced them."""
    spec, universe, engine_result = _result(tmp_path, LENIENT, days=5, entries=2)
    result = build_result(spec, universe, engine_result, engine_config(), LENIENT)
    payload = build_payload(result, universe, engine_config())

    assert payload["strategy_spec"] == spec.raw
    assert payload["data_fingerprint"]["sha256"]
    assert payload["config"]["start_capital_usd"] == 10_000.0
    assert payload["config"]["conviction"] == 1.0
    assert isinstance(payload["period_start"], datetime.date)
    assert payload["caveats"]
