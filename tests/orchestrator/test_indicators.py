"""See docs/features/F036-technical-indicator-research-items.md §3. Expected
values for the synthetic 60-bar series are cross-checked against `pandas-ta`
during development (SMA/Bollinger/MACD matched; RSI intentionally uses a
simpler non-Wilder-smoothed formula, verified by hand instead — see module
docstring in `src/orchestrator/indicators.py`)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe
from src.orchestrator.indicators import (
    compute_bollinger,
    compute_macd,
    compute_rsi14,
    compute_sma,
    detect_sma_crossover,
)

_SERIES_60 = [
    100.0,
    100.6856,
    98.7906,
    97.9457,
    96.8832,
    97.9764,
    98.8185,
    100.5657,
    98.9308,
    98.7029,
    96.828,
    95.7463,
    95.8688,
    93.9803,
    92.8154,
    93.5449,
    93.8337,
    92.7596,
    93.2345,
    94.6341,
    92.6614,
    94.0458,
    94.978,
    94.4071,
    93.0601,
    95.0804,
    94.4941,
    92.8836,
    91.2898,
    92.8493,
    93.3849,
    94.7748,
    95.8397,
    96.0919,
    98.179,
    97.7688,
    98.0874,
    99.5709,
    100.1687,
    101.7879,
    102.2128,
    103.172,
    101.3645,
    100.3217,
    99.5371,
    97.8722,
    96.8499,
    95.2741,
    94.4416,
    95.1115,
    94.6438,
    94.1986,
    93.0785,
    92.1998,
    94.1337,
    94.8554,
    95.4138,
    94.1326,
    95.1949,
    93.8812,
]


def _insert_bars(session: Session, symbol: str, closes: list[float]) -> None:
    start = datetime.datetime(2026, 1, 1)
    for i, close in enumerate(closes):
        session.add(
            MarketBar(
                symbol=symbol,
                timeframe=MarketBarTimeframe.DAY,
                ts=start + datetime.timedelta(days=i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=Decimal("1000000"),
            )
        )
    session.flush()


def test_sma_matches_pandas_ta_reference(session: Session) -> None:
    _insert_bars(session, "XYZ", _SERIES_60)

    assert compute_sma(session, "XYZ", 20) == pytest.approx(96.394485)
    assert compute_sma(session, "XYZ", 50) == pytest.approx(95.650778)


def test_sma_returns_none_with_insufficient_bars(session: Session) -> None:
    _insert_bars(session, "XYZ", _SERIES_60[:10])

    assert compute_sma(session, "XYZ", 20) is None


def test_bollinger_matches_pandas_ta_reference(session: Session) -> None:
    _insert_bars(session, "XYZ", _SERIES_60)

    bands = compute_bollinger(session, "XYZ")

    assert bands is not None
    assert bands.middle == pytest.approx(96.394485)
    assert bands.upper == pytest.approx(102.829342, abs=1e-3)
    assert bands.lower == pytest.approx(89.959628, abs=1e-3)


def test_macd_matches_independent_reference_computation(session: Session) -> None:
    # compute_macd only fetches the last _MIN_BARS_FOR_MACD (45) bars, so the
    # reference must be computed over that same 45-bar window, not the full 60
    # inserted here (extra older bars must not change the result).
    _insert_bars(session, "XYZ", _SERIES_60)

    macd = compute_macd(session, "XYZ")

    assert macd is not None
    assert macd.macd_line == pytest.approx(-0.4335671650392072)
    assert macd.signal_line == pytest.approx(-0.06649310323490266)
    assert macd.histogram == pytest.approx(-0.3670740618043046)


def test_macd_returns_none_with_insufficient_bars(session: Session) -> None:
    _insert_bars(session, "XYZ", _SERIES_60[:30])

    assert compute_macd(session, "XYZ") is None


def test_rsi_hand_verified_mixed_gains_and_losses(session: Session) -> None:
    # 15 closes, 14 changes: +1 x10, -1 x4 -> avg_gain=10/14, avg_loss=4/14,
    # RS=2.5, RSI = 100 - 100/3.5 = 500/7.
    closes = [10, 11, 12, 11, 12, 13, 12, 13, 14, 13, 14, 15, 14, 15, 16]
    _insert_bars(session, "XYZ", [float(c) for c in closes])

    rsi = compute_rsi14(session, "XYZ")

    assert rsi == pytest.approx(500 / 7)


def test_rsi_is_100_when_only_gains(session: Session) -> None:
    closes = [float(100 + i) for i in range(15)]
    _insert_bars(session, "XYZ", closes)

    assert compute_rsi14(session, "XYZ") == 100.0


def test_rsi_is_0_when_only_losses(session: Session) -> None:
    closes = [float(100 - i) for i in range(15)]
    _insert_bars(session, "XYZ", closes)

    assert compute_rsi14(session, "XYZ") == 0.0


def test_rsi_returns_none_with_insufficient_bars(session: Session) -> None:
    _insert_bars(session, "XYZ", [100.0] * 10)

    assert compute_rsi14(session, "XYZ") is None


def test_crossover_detects_golden_cross(session: Session) -> None:
    closes = [100.0] * 50 + [130.0]
    _insert_bars(session, "XYZ", closes)

    assert detect_sma_crossover(session, "XYZ") == "golden_cross"


def test_crossover_detects_death_cross(session: Session) -> None:
    closes = [100.0] * 50 + [70.0]
    _insert_bars(session, "XYZ", closes)

    assert detect_sma_crossover(session, "XYZ") == "death_cross"


def test_crossover_returns_none_when_no_flip(session: Session) -> None:
    closes = [100.0] * 51
    _insert_bars(session, "XYZ", closes)

    assert detect_sma_crossover(session, "XYZ") is None


def test_crossover_returns_none_with_insufficient_bars(session: Session) -> None:
    _insert_bars(session, "XYZ", [100.0] * 40)

    assert detect_sma_crossover(session, "XYZ") is None
