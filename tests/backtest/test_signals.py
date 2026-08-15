"""Signal series — F111 §8, tests 1-3.

The first test is the important one: it pins the backtest's rolling indicators to
the values the live path computes for the same series. If someone fixes RSI in
`src/orchestrator/indicators.py` and the backtest keeps its own copy, this fails.
"""

from __future__ import annotations

import datetime
import math
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.backtest.signals import atr14_at, compute_signals
from src.db.models import MarketBar, MarketBarTimeframe
from src.orchestrator.indicators import (
    compute_macd,
    compute_rsi14,
    compute_sma,
    detect_sma_crossover,
)
from src.orchestrator.market_pricing import compute_atr14
from tests.backtest.conftest import bar

# Deterministic, no randomness: a drifting sine crosses its own moving averages
# several times, which is what makes the crossover comparison meaningful.
_CLOSES = [round(100 + 12 * math.sin(index / 4.0) + index * 0.15, 4) for index in range(80)]
_BARS = [
    bar(index, close, open_=close - 0.3, high=close + 0.6, low=close - 0.9)
    for index, close in enumerate(_CLOSES)
]


def test_rolling_values_match_the_live_indicators(db_session: Session) -> None:
    """Test 1. Same closes into both implementations, same numbers out."""
    for index, close in enumerate(_CLOSES):
        db_session.add(
            MarketBar(
                symbol="DRIFT",
                timeframe=MarketBarTimeframe.DAY,
                ts=datetime.datetime(2026, 1, 5) + datetime.timedelta(days=index),
                open=Decimal(str(close - 0.3)),
                high=Decimal(str(close + 0.6)),
                low=Decimal(str(close - 0.9)),
                close=Decimal(str(close)),
                volume=Decimal("1000000"),
            )
        )
    db_session.flush()

    signals = compute_signals(_BARS, {"sma20", "sma50", "rsi14", "macd_histogram", "sma_crossover"})
    last = len(_BARS) - 1

    assert signals["sma20"][last] == pytest.approx(compute_sma(db_session, "DRIFT", 20))
    assert signals["sma50"][last] == pytest.approx(compute_sma(db_session, "DRIFT", 50))
    assert signals["rsi14"][last] == pytest.approx(compute_rsi14(db_session, "DRIFT"))
    live_macd = compute_macd(db_session, "DRIFT")
    assert live_macd is not None
    assert signals["macd_histogram"][last] == pytest.approx(live_macd.histogram)
    assert signals["sma_crossover"][last] == detect_sma_crossover(db_session, "DRIFT")
    assert atr14_at(_BARS, last) == pytest.approx(compute_atr14(db_session, "DRIFT"))


def test_drawdown_20d_against_hand_computed_values() -> None:
    """Test 2a. Peak of the trailing 20 closes vs today."""
    closes = [100.0] * 19 + [120.0] + [90.0]
    bars = [bar(index, close) for index, close in enumerate(closes)]
    series = compute_signals(bars, {"drawdown_20d"})["drawdown_20d"]

    assert series[18] is None  # only 19 closes so far
    assert series[19] == pytest.approx(0.0)  # today is the peak
    assert series[20] == pytest.approx((120.0 - 90.0) / 120.0)


def test_return_and_sma_relation_against_hand_computed_values() -> None:
    """Test 2b."""
    closes = [10.0] * 20 + [11.0]
    bars = [bar(index, close) for index, close in enumerate(closes)]
    signals = compute_signals(bars, {"return_5d", "return_20d", "close_vs_sma20"})

    assert signals["return_5d"][20] == pytest.approx(11.0 / 10.0 - 1)
    assert signals["return_20d"][20] == pytest.approx(11.0 / 10.0 - 1)
    # SMA20 over closes[1..20] = (19 * 10 + 11) / 20 = 10.05
    assert signals["close_vs_sma20"][20] == pytest.approx(11.0 / 10.05 - 1)


def test_volume_ratio_uses_the_trailing_window() -> None:
    bars = [bar(index, 10.0, volume=100.0) for index in range(20)]
    bars.append(bar(20, 10.0, volume=250.0))
    series = compute_signals(bars, {"volume_ratio_20d"})["volume_ratio_20d"]

    assert series[19] is None or series[19] == pytest.approx(1.0)
    assert series[20] == pytest.approx(2.5)


def test_short_series_yields_none_not_a_crash() -> None:
    """Test 3. A missing value must stay missing — `Condition.matches` treats None as
    "does not fire", which is only safe if the series really reports None."""
    bars = [bar(index, 10.0) for index in range(5)]
    signals = compute_signals(
        bars,
        {"rsi14", "macd_histogram", "sma20", "sma50", "sma_crossover", "drawdown_20d", "atr14_pct"},
    )

    for name, series in signals.items():
        assert all(value is None for value in series), name
