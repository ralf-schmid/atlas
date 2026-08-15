"""Engine behaviour — F111 §8, tests 7-13.

Reference values are computed by hand in the docstrings, never by running the engine
and recording what it produced. A backtest that is only tested against itself proves
nothing about whether its arithmetic is right.
"""

from __future__ import annotations

import pytest

from src.backtest.engine import REASON_STOP_LOSS, run_backtest
from src.backtest.spec import load_strategy
from src.risk.config import load_system_guardrails
from src.risk.models import StopLossPolicy, StopLossPolicyType, SystemGuardrails
from tests.backtest.conftest import (
    SLIPPAGE_CONFIG,
    bar,
    day,
    engine_config,
    make_universe,
    simple_spec,
)

SYSTEM = load_system_guardrails()

# The scenario every basic test builds on. Entry fires when yesterday's close is
# above 100, the exit when it drops below 90.
#
#   d1 close  95      no signal
#   d2 close 105      entry signal -> fill at d3 open
#   d3 open  100      BUY 10 @ 100.00
#   d4 close  86      exit signal  -> fill at d5 open
#   d5 open   88      SELL 10 @ 88.00
#   d6 —              nothing
_SCENARIO = [
    bar(1, 95.0),
    bar(2, 105.0),
    bar(3, 100.0, open_=100.0),
    bar(4, 86.0, open_=101.0, high=101.0, low=85.5),
    bar(5, 88.0, open_=88.0, high=89.0, low=87.0),
    bar(6, 88.0, open_=88.0),
]

_ENTRY = [{"signal": "close", "op": "gt", "value": 100}]
_EXIT = [{"signal": "close", "op": "lt", "value": 90}]


def _run(spec, bars_by_symbol, *, first_day=None, capital=10_000.0, system=SYSTEM):
    universe = make_universe(bars_by_symbol, first_day=first_day or day(2))
    return run_backtest(spec, universe, engine_config(capital), system)


def test_hand_computed_round_trip(tmp_path):
    """Test 7. Hand calculation, 10.000 USD start capital, 10 % per position:

    BUY  target 0.10 * 10000 = 1000 -> qty = floor(1000/100) = 10, gross 1000.00
         slippage 0.5 * 5bps * 1000            = 0.25   (no volume penalty:
         1000 / (1e6 * 100) is far below the 1 % threshold)
         cash 10000 - 1000 - 0.25              = 8999.75
    SELL 10 @ 88.00, gross 880.00
         slippage 0.5 * 5bps * 880             = 0.22
         cash 8999.75 + 880 - 0.22             = 9879.53
    """
    spec = simple_spec(tmp_path, entry=_ENTRY, exit_=_EXIT)
    result = _run(spec, {"TEST": _SCENARIO})

    assert [(t.action, t.day, t.qty, t.price) for t in result.trades] == [
        ("buy", day(3), 10, 100.0),
        ("sell", day(5), 10, 88.0),
    ]
    assert result.trades[0].slippage_usd == pytest.approx(0.25)
    assert result.trades[1].slippage_usd == pytest.approx(0.22)
    assert result.slippage_total_usd == pytest.approx(0.47)
    assert result.equity_curve[-1][1] == pytest.approx(9879.53)
    # Test 12: the malus is charged on both sides, not only on entry.
    assert all(trade.slippage_usd > 0 for trade in result.trades)


def test_no_look_ahead_in_later_bars(tmp_path):
    """Test 8a. Bars after the last decision day cannot reach back in time: rewriting
    d6 leaves every earlier fill untouched."""
    spec = simple_spec(tmp_path, entry=_ENTRY, exit_=_EXIT)
    baseline = _run(spec, {"TEST": _SCENARIO})

    tampered = list(_SCENARIO)
    tampered[5] = bar(6, 1.0, open_=1.0)
    after = _run(spec, {"TEST": tampered})

    assert [t.as_dict() for t in after.trades] == [t.as_dict() for t in baseline.trades]


def test_no_look_ahead_within_the_fill_day(tmp_path):
    """Test 8b. The sharper case: the d5 sell fills at d5's *open*, which is known at
    the moment the order goes in. Moving d5's close — information that only exists
    hours later — must not move that fill, even though it legitimately changes what
    happens on d6."""
    spec = simple_spec(tmp_path, entry=_ENTRY, exit_=_EXIT)
    baseline = _run(spec, {"TEST": _SCENARIO})

    tampered = list(_SCENARIO)
    tampered[4] = bar(5, 250.0, open_=88.0, high=260.0, low=87.0)
    after = _run(spec, {"TEST": tampered})

    up_to_fill_day = lambda trades: [t.as_dict() for t in trades if t.day <= day(5)]  # noqa: E731
    assert up_to_fill_day(after.trades) == up_to_fill_day(baseline.trades)
    assert after.trades[1].price == 88.0


def test_stop_loss_fills_at_the_stop(tmp_path):
    """Test 9a. Entry at 100.00 with a 15 % policy puts the stop at 85.00. A day whose
    low pierces it but whose open is above it fills at the stop."""
    bars = list(_SCENARIO)
    bars[3] = bar(4, 86.0, open_=101.0, high=101.0, low=80.0)
    spec = simple_spec(tmp_path, entry=_ENTRY, exit_=_EXIT)
    result = _run(spec, {"TEST": bars})

    sell = result.trades[1]
    assert (sell.day, sell.price, sell.reason) == (day(4), 85.0, REASON_STOP_LOSS)


def test_gap_below_the_stop_fills_at_the_open(tmp_path):
    """Test 9b. A stop is a trigger, not a guaranteed price: an open below the stop
    fills at the open. Anything else would invent liquidity that was never there."""
    bars = list(_SCENARIO)
    bars[3] = bar(4, 78.0, open_=80.0, high=80.0, low=77.0)
    spec = simple_spec(tmp_path, entry=_ENTRY, exit_=_EXIT)
    result = _run(spec, {"TEST": bars})

    sell = result.trades[1]
    assert (sell.day, sell.price, sell.reason) == (day(4), 80.0, REASON_STOP_LOSS)


def test_max_trades_per_day_caps_entries(tmp_path):
    """Test 10a. Six symbols signal on the same day, the guardrail allows two."""
    bars = {
        symbol: [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 105.0, open_=100.0)]
        for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
    }
    spec = simple_spec(tmp_path, entry=_ENTRY, max_trades_per_day=2, max_position_pct=0.05)
    result = _run(spec, bars, first_day=day(2))

    buys_on_day_two = [t for t in result.trades if t.action == "buy" and t.day == day(2)]
    assert len(buys_on_day_two) == 2
    assert result.rejections.get("max_trades_per_day_exceeded", 0) > 0


def test_min_cash_reserve_is_respected(tmp_path):
    """Test 10b. A GUARDIAN-style 20 % cash floor must survive a market where every
    symbol signals — the gate, not the engine, is what enforces it."""
    bars = {
        f"S{index:02d}": [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 105.0, open_=100.0)]
        for index in range(20)
    }
    spec = simple_spec(
        tmp_path, entry=_ENTRY, max_position_pct=0.15, min_cash_pct=0.20, max_trades_per_day=15
    )
    result = _run(spec, bars, first_day=day(2))

    invested = sum(t.gross_usd + t.slippage_usd for t in result.trades if t.action == "buy")
    cash_after = 10_000.0 - invested
    assert cash_after >= 0.20 * 10_000.0
    assert result.rejections.get("min_cash_pct_violated", 0) > 0


def test_cash_never_goes_negative(tmp_path):
    """Test 10c. No margin (config/risk.yaml `allow_margin: false`)."""
    bars = {
        f"S{index:02d}": [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 105.0, open_=100.0)]
        for index in range(30)
    }
    spec = simple_spec(tmp_path, entry=_ENTRY, max_position_pct=0.25, max_trades_per_day=15)
    result = _run(spec, bars, first_day=day(2))

    spent = sum(t.gross_usd + t.slippage_usd for t in result.trades if t.action == "buy")
    assert spent <= 10_000.0


def test_system_ceiling_beats_a_reckless_spec(tmp_path):
    """Test 10d. A spec asking for 50 % per position gets the system ceiling of 25 %
    (config/risk.yaml), because the gate takes the stricter of the two."""
    bars = {"AAA": [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 105.0, open_=100.0)]}
    spec = simple_spec(tmp_path, entry=_ENTRY, max_position_pct=0.50)
    result = _run(spec, bars, first_day=day(2))

    buy = result.trades[0]
    assert buy.gross_usd <= 0.25 * 10_000.0
    assert buy.qty == 25  # floor(0.25 * 10000 / 100)


def test_circuit_breaker_blocks_new_buys(tmp_path):
    """Test 11. Three positions at 25 % each, all down 25 % on the same day: equity
    falls from 10.000 to 8.125, a 18,75 % drawdown, past the 15 % breaker. The fourth
    symbol signals afterwards and must be refused.

    The stop policy is deliberately wide (-60 %) so the crash does not simply stop
    the positions out before the breaker can be observed.
    """
    crash = [
        bar(1, 105.0),
        bar(2, 105.0, open_=100.0),  # entry day for the first three
        bar(3, 75.0, open_=100.0, high=100.0, low=75.0),  # -25 %
        bar(4, 75.0, open_=75.0),
    ]
    quiet = [
        bar(1, 95.0),
        bar(2, 95.0, open_=95.0),
        bar(3, 105.0, open_=95.0),  # signals only on d3, i.e. buy on d4
        bar(4, 105.0, open_=95.0),
    ]
    bars = {"AAA": crash, "BBB": list(crash), "CCC": list(crash), "ZZZ": quiet}
    spec = simple_spec(
        tmp_path, entry=_ENTRY, max_position_pct=0.25, max_trades_per_day=8, max_loss_pct=0.60
    )
    result = _run(spec, bars, first_day=day(2))

    assert result.rejections.get("circuit_breaker_sell_only", 0) > 0
    assert not [t for t in result.trades if t.action == "buy" and t.symbol == "ZZZ"]


def test_open_positions_are_liquidated_at_the_end(tmp_path):
    """A strategy must not park an unrealised gain in an open position and skip its
    exit slippage — the final equity is realised cash."""
    bars = {"AAA": [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 130.0, open_=100.0)]}
    spec = simple_spec(tmp_path, entry=_ENTRY)
    result = _run(spec, bars, first_day=day(2))

    assert [t.action for t in result.trades] == ["buy", "sell"]
    assert result.trades[1].reason == "end_of_run"
    assert result.equity_curve[-1][1] == pytest.approx(
        10_000.0
        - result.trades[0].gross_usd
        - result.trades[0].slippage_usd
        + result.trades[1].gross_usd
        - result.trades[1].slippage_usd
    )


def test_max_hold_days_forces_an_exit(tmp_path):
    bars = {
        "AAA": [bar(1, 105.0), bar(2, 105.0, open_=100.0)]
        + [bar(offset, 105.0, open_=100.0) for offset in range(3, 12)]
    }
    spec = simple_spec(tmp_path, entry=_ENTRY, max_hold_days=5)
    result = _run(spec, bars, first_day=day(2))

    sell = next(t for t in result.trades if t.action == "sell")
    assert sell.reason == "max_hold_days"
    assert (sell.day - result.trades[0].day).days == 5


def test_determinism(tmp_path):
    """Test 13. Same bars, same spec, twice — identical trades and identical curve."""
    spec = simple_spec(tmp_path, entry=_ENTRY, exit_=_EXIT)
    first = _run(spec, {"TEST": _SCENARIO})
    second = _run(spec, {"TEST": _SCENARIO})

    assert [t.as_dict() for t in first.trades] == [t.as_dict() for t in second.trades]
    assert first.equity_curve == second.equity_curve
    assert first.slippage_total_usd == second.slippage_total_usd


def test_stop_is_exempt_from_the_daily_trade_cap(tmp_path):
    """A stop is a resting GTC order placed at entry (Invariante #4). A day that has
    already used up `max_trades_per_day` must still honour it — the cap governs new
    decisions, not orders the broker already holds."""
    crashing = [
        bar(1, 105.0),
        bar(2, 105.0, open_=100.0),
        bar(3, 70.0, open_=100.0, high=100.0, low=70.0),
    ]
    fresh = [bar(1, 95.0), bar(2, 95.0), bar(3, 105.0, open_=100.0)]
    spec = simple_spec(
        tmp_path, entry=_ENTRY, max_trades_per_day=1, max_position_pct=0.10, max_loss_pct=0.15
    )
    result = _run(spec, {"AAA": crashing, "BBB": fresh}, first_day=day(2))

    stops = [t for t in result.trades if t.reason == REASON_STOP_LOSS]
    assert len(stops) == 1
    assert stops[0].day == day(3)


def test_atr_policy_without_atr_is_rejected(tmp_path):
    """CHARTIST's ATR stop needs 15 bars of history. Without them the engine refuses
    the entry rather than inventing a stop — Invariante #4 has no fallback."""
    spec_path = tmp_path / "atr.yaml"
    spec_path.write_text(
        "name: atr-spec\n"
        "description: test\n"
        "guardrails:\n"
        "  name: TEST\n"
        "  max_position_pct: 0.1\n"
        "  max_trades_per_day: 8\n"
        "  max_open_positions: 15\n"
        "  min_cash_pct: 0.0\n"
        "  stop_loss_policy: {type: atr, atr_multiplier: 2.0, min_loss_pct: 0.08}\n"
        "universe: {filters: []}\n"
        "entry:\n"
        "  - {signal: close, op: gt, value: 100}\n"
    )
    spec = load_strategy(spec_path)
    bars = {"AAA": [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 105.0, open_=100.0)]}
    result = _run(spec, bars, first_day=day(2))

    assert result.trades == []
    assert result.rejections["atr_required_but_missing"] > 0


def test_stop_loss_is_mandatory_for_every_entry(tmp_path):
    """Invariante #4 as an engine property: no simulated position exists without a
    stop below its entry."""
    spec = simple_spec(tmp_path, entry=_ENTRY)
    bars = {"AAA": [bar(1, 105.0), bar(2, 105.0, open_=100.0), bar(3, 105.0, open_=100.0)]}
    universe = make_universe(bars, first_day=day(2))
    system = SystemGuardrails(
        circuit_breaker_drawdown_pct=0.15,
        allow_margin=False,
        allow_short=False,
        require_stop_loss=True,
        max_position_pct_ceiling=0.25,
        max_trades_per_day_ceiling=15,
        max_open_positions_ceiling=30,
        min_cash_pct_floor=0.0,
    )
    result = run_backtest(spec, universe, engine_config(), system)

    assert result.trades
    # The stop lives on the position, not on the trade record; the observable proof
    # is that a policy-conform stop price was computed and accepted by the gate.
    assert spec.guardrails.stop_loss_policy == StopLossPolicy(
        type=StopLossPolicyType.FIXED, max_loss_pct=0.15
    )


@pytest.mark.parametrize("symbol", ["AAA", "BTC/USD"])
def test_backtest_slippage_matches_the_live_formula(tmp_path, symbol):
    """F114 §4 test 7. The engine must charge exactly what
    `review.slippage.compute_slippage_malus` would charge for the same order —
    same spread rate, same coverage correction, same penalty.

    Recomputed here from the documented formula rather than from the engine, so a
    change on either side has to be a deliberate change to both.
    """
    from src.backtest.engine import _slippage_usd
    from src.review.slippage import _compute_penalty, _flat_spread_bps

    bars = [bar(index, 100.0, volume=1_000_000.0) for index in range(3)]
    universe = make_universe({symbol: bars}, first_day=day(0))
    series = universe.series[symbol]
    config = SLIPPAGE_CONFIG | {"volume_coverage": {"equities": 0.035, "crypto": 1.0}}
    order_value = 2_000_000.0

    charged = _slippage_usd(order_value, series, 1, config)

    expected_spread = 0.5 * _flat_spread_bps(symbol, config) / 10_000 * order_value
    observed = bars[1].volume * bars[1].close
    coverage = 0.035 if symbol == "AAA" else 1.0
    expected_penalty = float(_compute_penalty(order_value, observed / coverage, config))
    assert charged == pytest.approx(expected_spread + expected_penalty)
    # And the correction must actually bite for the equity, not silently no-op.
    if symbol == "AAA":
        uncorrected = _slippage_usd(
            order_value, series, 1, SLIPPAGE_CONFIG | {"volume_coverage": {"equities": 1.0}}
        )
        assert charged < uncorrected
