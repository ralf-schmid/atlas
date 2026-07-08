"""Technical indicators computed from the already-ingested `market_bar` table
(F008) — see docs/features/F036-technical-indicator-research-items.md.

Same style as `market_pricing.py::compute_atr14`: pure Python, no pandas/numpy
(this repo has neither as a dependency), returns `None` when there aren't
enough bars rather than raising — the caller (research_synthesis.py) simply
omits an indicator it can't compute yet instead of failing the whole cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe

_RSI_PERIOD = 14
_MIN_BARS_FOR_RSI = _RSI_PERIOD + 1  # need one extra close for the first day-over-day change

_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
# generous warm-up buffer so the seeded EMA has settled before the signal line
# is computed from it — see F036 §2 Design-Entscheidungen.
_MIN_BARS_FOR_MACD = _MACD_SLOW + _MACD_SIGNAL + 10

_BOLLINGER_PERIOD = 20
_BOLLINGER_NUM_STD = 2.0

_SMA_SHORT = 20
_SMA_LONG = 50
_MIN_BARS_FOR_CROSSOVER = _SMA_LONG + 1  # need yesterday's SMAs too, to detect a fresh cross


@dataclass(frozen=True, slots=True)
class MacdResult:
    macd_line: float
    signal_line: float
    histogram: float


@dataclass(frozen=True, slots=True)
class BollingerBands:
    upper: float
    lower: float
    middle: float


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    """Every field is independently optional — a symbol with 20 bars gets SMA20/
    Bollinger but not MACD/crossover yet, gracefully, not all-or-nothing."""

    sma20: float | None
    sma50: float | None
    rsi14: float | None
    macd: MacdResult | None
    bollinger: BollingerBands | None
    crossover: str | None  # "golden_cross" | "death_cross" | None


def compute_sma(session: Session, symbol: str, period: int) -> float | None:
    closes = _fetch_closes(session, symbol, period)
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_rsi14(session: Session, symbol: str) -> float | None:
    closes = _fetch_closes(session, symbol, _MIN_BARS_FOR_RSI)
    if len(closes) < _MIN_BARS_FOR_RSI:
        return None
    return _rsi_from_closes(closes[-_MIN_BARS_FOR_RSI:])


def compute_macd(session: Session, symbol: str) -> MacdResult | None:
    closes = _fetch_closes(session, symbol, _MIN_BARS_FOR_MACD)
    if len(closes) < _MIN_BARS_FOR_MACD:
        return None
    return _macd_from_closes(closes)


def compute_bollinger(session: Session, symbol: str) -> BollingerBands | None:
    closes = _fetch_closes(session, symbol, _BOLLINGER_PERIOD)
    if len(closes) < _BOLLINGER_PERIOD:
        return None
    window = closes[-_BOLLINGER_PERIOD:]
    middle = sum(window) / _BOLLINGER_PERIOD
    # Sample stddev (N-1), matching the standard Bollinger Bands convention
    # (TradingView/pandas-ta) rather than population stddev — verified against
    # pandas-ta's `bbands` output during development, see F036 §3.
    variance = sum((c - middle) ** 2 for c in window) / (_BOLLINGER_PERIOD - 1)
    stddev = variance**0.5
    return BollingerBands(
        upper=middle + _BOLLINGER_NUM_STD * stddev,
        lower=middle - _BOLLINGER_NUM_STD * stddev,
        middle=middle,
    )


def detect_sma_crossover(session: Session, symbol: str) -> str | None:
    """Compares today's SMA20-vs-SMA50 relationship to yesterday's — only reports
    a value the day the relationship actually flips, not the ongoing regime."""
    closes = _fetch_closes(session, symbol, _MIN_BARS_FOR_CROSSOVER)
    if len(closes) < _MIN_BARS_FOR_CROSSOVER:
        return None

    today_short = sum(closes[-_SMA_SHORT:]) / _SMA_SHORT
    today_long = sum(closes[-_SMA_LONG:]) / _SMA_LONG
    yesterday_closes = closes[:-1]
    yesterday_short = sum(yesterday_closes[-_SMA_SHORT:]) / _SMA_SHORT
    yesterday_long = sum(yesterday_closes[-_SMA_LONG:]) / _SMA_LONG

    was_below = yesterday_short <= yesterday_long
    is_above = today_short > today_long
    if was_below and is_above:
        return "golden_cross"
    was_above = yesterday_short >= yesterday_long
    is_below = today_short < today_long
    if was_above and is_below:
        return "death_cross"
    return None


def compute_indicator_snapshot(session: Session, symbol: str) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        sma20=compute_sma(session, symbol, _SMA_SHORT),
        sma50=compute_sma(session, symbol, _SMA_LONG),
        rsi14=compute_rsi14(session, symbol),
        macd=compute_macd(session, symbol),
        bollinger=compute_bollinger(session, symbol),
        crossover=detect_sma_crossover(session, symbol),
    )


def _fetch_closes(session: Session, symbol: str, limit: int) -> list[float]:
    stmt = (
        select(MarketBar.close)
        .where(MarketBar.symbol == symbol, MarketBar.timeframe == MarketBarTimeframe.DAY)
        .order_by(MarketBar.ts.desc())
        .limit(limit)
    )
    closes = [float(c) for c in session.scalars(stmt).all()]
    closes.reverse()  # oldest first
    return closes


def _rsi_from_closes(closes: list[float]) -> float:
    """Simple (non-Wilder-smoothed) 14-period RSI over exactly 15 closes — a
    deliberate simplification over the recursive Wilder average, which needs the
    entire price history to seed accurately; see F036 §2."""
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [c for c in changes if c > 0]
    losses = [-c for c in changes if c < 0]
    avg_gain = sum(gains) / len(changes)
    avg_loss = sum(losses) / len(changes)
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _ema_series(closes: list[float], period: int) -> list[float]:
    """EMA series seeded with the SMA of the first `period` closes, then the
    standard recursive smoothing for the rest — one EMA value per close from
    index `period - 1` onward."""
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    series = [seed]
    for price in closes[period:]:
        series.append(price * k + series[-1] * (1 - k))
    return series


def _macd_from_closes(closes: list[float]) -> MacdResult:
    ema_fast = _ema_series(closes, _MACD_FAST)
    ema_slow = _ema_series(closes, _MACD_SLOW)
    # Align both series to the same (later) starting point — ema_slow starts
    # _MACD_SLOW - _MACD_FAST closes later than ema_fast.
    offset = _MACD_SLOW - _MACD_FAST
    macd_series = [fast - slow for fast, slow in zip(ema_fast[offset:], ema_slow, strict=True)]
    signal_series = _ema_series(macd_series, _MACD_SIGNAL)
    macd_line = macd_series[-1]
    signal_line = signal_series[-1]
    return MacdResult(
        macd_line=macd_line,
        signal_line=signal_line,
        histogram=macd_line - signal_line,
    )
