"""Signal values per trading day — see docs/features/F111-backtest-modul.md §6.2.

The live path (`src/orchestrator/indicators.py`, `market_pricing.py`) only ever
needs *today's* indicator value and therefore queries the DB per call. A backtest
needs the value as of every historical day, so the series are computed here — but
the arithmetic itself is imported from the live modules wherever it is non-trivial.

That import of two private helpers is deliberate: if the backtest reimplemented
RSI or MACD, a later fix in the live path would silently stop applying to the
backtest, and the two would drift apart while still claiming to test the same
strategy. Identical numbers are a correctness requirement here, not a convenience.
`tests/backtest/test_signals.py` pins the equality.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from src.orchestrator.indicators import (
    _MIN_BARS_FOR_CROSSOVER,
    _MIN_BARS_FOR_MACD,
    _MIN_BARS_FOR_RSI,
    _macd_from_closes,
    _rsi_from_closes,
)

_SMA_SHORT = 20
_SMA_LONG = 50
_DRAWDOWN_WINDOW = 20
_VOLUME_WINDOW = 20
_ATR_PERIODS = 14
_MIN_BARS_FOR_ATR = _ATR_PERIODS + 1

SignalValue = float | str | None


@dataclass(frozen=True, slots=True)
class Bar:
    day: datetime.date
    open: float
    high: float
    low: float
    close: float
    volume: float


def compute_signals(bars: list[Bar], needed: set[str]) -> dict[str, list[SignalValue]]:
    """One list per requested signal, aligned index-for-index with *bars*.

    A value is `None` while the series is too short for that indicator — never a
    fabricated default, because a condition on a missing value must not fire
    (see `Condition.matches`).
    """
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    n = len(bars)
    out: dict[str, list[SignalValue]] = {}

    sma20 = _sma_series(closes, _SMA_SHORT) if _needs_sma20(needed) else None
    sma50 = _sma_series(closes, _SMA_LONG) if _needs_sma50(needed) else None

    if "close" in needed:
        out["close"] = list(closes)
    if "volume" in needed:
        out["volume"] = list(volumes)
    if "dollar_volume" in needed:
        out["dollar_volume"] = [closes[i] * volumes[i] for i in range(n)]
    if "sma20" in needed and sma20 is not None:
        out["sma20"] = list(sma20)
    if "sma50" in needed and sma50 is not None:
        out["sma50"] = list(sma50)
    if "close_vs_sma20" in needed and sma20 is not None:
        out["close_vs_sma20"] = [_relative(closes[i], sma20[i]) for i in range(n)]
    if "rsi14" in needed:
        out["rsi14"] = [
            _rsi_from_closes(closes[i - _MIN_BARS_FOR_RSI + 1 : i + 1])
            if i + 1 >= _MIN_BARS_FOR_RSI
            else None
            for i in range(n)
        ]
    if "macd_histogram" in needed:
        # Trailing window, not the full history: the live `compute_macd` fetches
        # exactly `_MIN_BARS_FOR_MACD` closes, and an EMA seeded on a longer history
        # settles differently. Feeding everything available here produced a
        # histogram of 2.02 where the live path said 1.60 on the same series — a
        # backtest that "improves" on the live indicator is testing a strategy the
        # personas do not run.
        out["macd_histogram"] = [
            _macd_from_closes(closes[max(0, i + 1 - _MIN_BARS_FOR_MACD) : i + 1]).histogram
            if i + 1 >= _MIN_BARS_FOR_MACD
            else None
            for i in range(n)
        ]
    if "sma_crossover" in needed and sma20 is not None and sma50 is not None:
        out["sma_crossover"] = _crossover_series(sma20, sma50)
    if "drawdown_20d" in needed:
        out["drawdown_20d"] = _drawdown_series(closes)
    if "return_5d" in needed:
        out["return_5d"] = _return_series(closes, 5)
    if "return_20d" in needed:
        out["return_20d"] = _return_series(closes, 20)
    if "volume_ratio_20d" in needed:
        out["volume_ratio_20d"] = _volume_ratio_series(volumes)
    if "atr14_pct" in needed:
        out["atr14_pct"] = [
            atr / closes[i] if (atr := _atr14_at(bars, i)) is not None and closes[i] else None
            for i in range(n)
        ]
    return out


def atr14_at(bars: list[Bar], index: int) -> float | None:
    """ATR14 over the 15 bars ending at *index* — mirrors `market_pricing.compute_atr14`
    (simple mean of true ranges, no Wilder smoothing). Used by the stop-loss policy."""
    return _atr14_at(bars, index)


def _relative(value: float, base: float | None) -> float | None:
    """`value / base − 1`, or None while *base* is undefined or zero."""
    return value / base - 1.0 if base else None


def _needs_sma20(needed: set[str]) -> bool:
    return bool(needed & {"sma20", "close_vs_sma20", "sma_crossover"})


def _needs_sma50(needed: set[str]) -> bool:
    return bool(needed & {"sma50", "sma_crossover"})


def _sma_series(closes: list[float], period: int) -> list[float | None]:
    """Rolling mean via a running sum — the same value `compute_sma` returns for the
    corresponding window."""
    out: list[float | None] = []
    running = 0.0
    for i, close in enumerate(closes):
        running += close
        if i >= period:
            running -= closes[i - period]
        out.append(running / period if i + 1 >= period else None)
    return out


def _crossover_series(
    sma_short: list[float | None], sma_long: list[float | None]
) -> list[SignalValue]:
    """Reports a value only on the day the 20/50 relationship flips — the same
    definition as `detect_sma_crossover`, not the ongoing regime."""
    out: list[SignalValue] = []
    for i in range(len(sma_short)):
        today_short, today_long = sma_short[i], sma_long[i]
        previous_short = sma_short[i - 1] if i else None
        previous_long = sma_long[i - 1] if i else None
        if (
            i + 1 < _MIN_BARS_FOR_CROSSOVER
            or today_short is None
            or today_long is None
            or previous_short is None
            or previous_long is None
        ):
            out.append(None)
            continue
        if previous_short <= previous_long and today_short > today_long:
            out.append("golden_cross")
        elif previous_short >= previous_long and today_short < today_long:
            out.append("death_cross")
        else:
            out.append(None)
    return out


def _drawdown_series(closes: list[float]) -> list[SignalValue]:
    """Decline from the highest close of the trailing 20 sessions, as a positive
    fraction — CONTRA's `drawdown_min_pct` screen expressed as a signal."""
    out: list[SignalValue] = []
    for i in range(len(closes)):
        if i + 1 < _DRAWDOWN_WINDOW:
            out.append(None)
            continue
        peak = max(closes[i - _DRAWDOWN_WINDOW + 1 : i + 1])
        out.append((peak - closes[i]) / peak if peak > 0 else None)
    return out


def _return_series(closes: list[float], lookback: int) -> list[SignalValue]:
    out: list[SignalValue] = []
    for i in range(len(closes)):
        base = closes[i - lookback] if i >= lookback else None
        out.append(closes[i] / base - 1.0 if base else None)
    return out


def _volume_ratio_series(volumes: list[float]) -> list[SignalValue]:
    """Today's volume against the trailing 20-session average — VULTURE's
    "Volumen-Spike" (ARCHITECTURE.md §4.1) as a number."""
    out: list[SignalValue] = []
    for i in range(len(volumes)):
        if i < _VOLUME_WINDOW:
            out.append(None)
            continue
        average = sum(volumes[i - _VOLUME_WINDOW : i]) / _VOLUME_WINDOW
        out.append(volumes[i] / average if average > 0 else None)
    return out


def _atr14_at(bars: list[Bar], index: int) -> float | None:
    if index + 1 < _MIN_BARS_FOR_ATR:
        return None
    window = bars[index - _MIN_BARS_FOR_ATR + 1 : index + 1]
    true_ranges = [
        max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close))
        for previous, bar in zip(window, window[1:], strict=False)
    ]
    return sum(true_ranges) / len(true_ranges)
