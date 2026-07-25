"""See docs/features/F081-spy-benchmark-portfolio.md §3, tests 1-8."""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe
from src.orchestrator.benchmark import compute_benchmark_value

# Tests use a fixed competition start date of 2026-08-03 (Monday) regardless
# of the real config/competition.yaml — we patch _get_config to return a
# deterministic CompetitionConfig.
from src.orchestrator.competition_config import CompetitionConfig


def _config(**overrides) -> CompetitionConfig:
    defaults = dict(
        start_date=datetime.date(2026, 8, 3),
        start_capital_usd=5000,
        benchmark_enabled=True,
        benchmark_symbol="SPY",
    )
    defaults.update(overrides)
    return CompetitionConfig(**defaults)


def _add_bar(
    session: Session,
    symbol: str,
    ts: datetime.datetime,
    close: float,
) -> None:
    session.add(
        MarketBar(
            symbol=symbol,
            timeframe=MarketBarTimeframe.DAY,
            ts=ts,
            open=Decimal(str(close - 1)),
            high=Decimal(str(close + 1)),
            low=Decimal(str(close - 2)),
            close=Decimal(str(close)),
            volume=Decimal("1000000"),
        )
    )
    session.flush()


class TestBenchmarkValue:
    """Tests 1-7 from F081 §3."""

    def test_basic(self, session: Session) -> None:
        """Test 1: shares = 5000/100 = 50; value at 104 = 5200."""
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 3), 100.0)
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 5), 104.0)
        now = datetime.datetime(2026, 8, 5, 18, 0)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            result = compute_benchmark_value(session, now)
        assert result == pytest.approx(5200.00)

    def test_before_start_date(self, session: Session) -> None:
        """Test 2: now < start_date → None."""
        _add_bar(session, "SPY", datetime.datetime(2026, 7, 31), 100.0)
        now = datetime.datetime(2026, 8, 1, 12, 0)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            result = compute_benchmark_value(session, now)
        assert result is None

    def test_start_date_bar_not_yet_ingested(self, session: Session) -> None:
        """Test 3: start_date bar missing, no later bar yet → None (sync delay)."""
        # No bars at all.
        now = datetime.datetime(2026, 8, 3, 9, 30)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            result = compute_benchmark_value(session, now)
        assert result is None

    def test_weekend_carries_friday_close(self, session: Session) -> None:
        """Test 4: no bar on Saturday → Friday close carried forward."""
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 3), 100.0)
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 7), 105.0)  # Friday
        # Saturday: now = Aug 8, last bar <= now is Aug 7 (Fri)
        now = datetime.datetime(2026, 8, 8, 12, 0)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            result = compute_benchmark_value(session, now)
        # shares = 5000/100 = 50; value = 50*105 = 5250
        assert result == pytest.approx(5250.00)

    def test_holiday_start_date(self, session: Session) -> None:
        """Test 5: start_date is a holiday → first available bar is next day."""
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 4), 98.0)  # Tue after Mon holiday
        now = datetime.datetime(2026, 8, 4, 18, 0)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            result = compute_benchmark_value(session, now)
        # shares = 5000/98 = 51.0204...; value = shares*98 = 5000
        assert result == pytest.approx(5000.00)

    def test_decimal_precision(self, session: Session) -> None:
        """Test 6: fractional shares, result rounded to 2 decimal places."""
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 3), 555.55)
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 4), 560.00)
        now = datetime.datetime(2026, 8, 4, 18, 0)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            result = compute_benchmark_value(session, now)
        expected = round(5000 / 555.55 * 560.00, 2)
        assert result == pytest.approx(expected)

    def test_benchmark_disabled(self, session: Session) -> None:
        """Test: benchmark.enabled: false → None."""
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 3), 100.0)
        now = datetime.datetime(2026, 8, 5, 18, 0)
        cfg = _config(benchmark_enabled=False)
        with patch("src.orchestrator.benchmark._get_config", return_value=cfg):
            result = compute_benchmark_value(session, now)
        assert result is None

    def test_multiple_portfolios_same_value(self, session: Session) -> None:
        """Test 7 (integration aspect): two calls in same session → identical."""
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 3), 100.0)
        _add_bar(session, "SPY", datetime.datetime(2026, 8, 5), 104.0)
        now = datetime.datetime(2026, 8, 5, 18, 0)
        with patch("src.orchestrator.benchmark._get_config", return_value=_config()):
            v1 = compute_benchmark_value(session, now)
            v2 = compute_benchmark_value(session, now)
        assert v1 == v2
