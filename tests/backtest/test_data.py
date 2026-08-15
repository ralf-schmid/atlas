"""Fingerprint and data-quality gate — F111 §8, tests 4-6."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.backtest.data import (
    InsufficientDataError,
    find_price_level_break,
    load_universe,
)
from src.db.models import MarketBar, MarketBarTimeframe
from src.orchestrator.indicators import detect_price_level_break
from tests.backtest.conftest import bar, make_universe


def test_fingerprint_is_deterministic_and_data_sensitive() -> None:
    """Test 4. The digest is the reproducibility anchor (F111 §4): it must be stable
    across runs and must change when a single bar changes."""
    bars = [bar(index, 100.0 + index) for index in range(10)]
    first = make_universe({"AAA": bars}).fingerprint
    second = make_universe({"AAA": list(bars)}).fingerprint
    assert first == second
    assert first["bars"] == 10
    assert first["symbols"] == 1

    changed = list(bars)
    changed[4] = bar(4, 104.000001)
    assert make_universe({"AAA": changed}).fingerprint["sha256"] != first["sha256"]


def test_fingerprint_covers_volume_too() -> None:
    """A re-synced bar that only corrects the volume still changes the slippage
    penalty, so it has to change the digest."""
    bars = [bar(index, 100.0) for index in range(5)]
    baseline = make_universe({"AAA": bars}).fingerprint["sha256"]
    louder = [bar(index, 100.0, volume=2_000_000.0) for index in range(5)]
    assert make_universe({"AAA": louder}).fingerprint["sha256"] != baseline


def test_price_level_break_agrees_with_the_live_detector(db_session: Session) -> None:
    """Test 5. Anti-drift against F108: the pure window version and the DB-bound one
    must reach the same verdict on the same series."""
    closes = [50.0] * 20 + [10.0] * 20  # a 5x overnight level change
    for index, close in enumerate(closes):
        open_ = close
        db_session.add(
            MarketBar(
                symbol="SPLIT",
                timeframe=MarketBarTimeframe.DAY,
                ts=datetime.datetime(2026, 1, 5) + datetime.timedelta(days=index),
                open=Decimal(str(open_)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=Decimal("1000000"),
            )
        )
    db_session.flush()

    bars = [bar(index, close, open_=close) for index, close in enumerate(closes)]
    pure = find_price_level_break(bars, 1.5)
    live = detect_price_level_break(db_session, "SPLIT", 1.5)

    assert pure is not None and live is not None
    assert pure[1] == pytest.approx(live.factor)
    assert pure[0] == live.ts.date()


def test_clean_series_has_no_break() -> None:
    bars = [bar(index, 100.0 + index * 0.5) for index in range(30)]
    assert find_price_level_break(bars, 1.5) is None


def test_symbols_below_the_warmup_are_excluded(db_session: Session) -> None:
    """Test 6. A symbol that joined the universe last week cannot carry an SMA50, and
    silently including it would put unwarmed signals into the result."""
    for symbol, count in (("OLD", 40), ("NEW", 5)):
        for index in range(count):
            db_session.add(
                MarketBar(
                    symbol=symbol,
                    timeframe=MarketBarTimeframe.DAY,
                    ts=datetime.datetime(2026, 1, 5) + datetime.timedelta(days=index),
                    open=Decimal("100"),
                    high=Decimal("100"),
                    low=Decimal("100"),
                    close=Decimal("100"),
                    volume=Decimal("1000000"),
                )
            )
    db_session.flush()

    universe = load_universe(
        db_session,
        symbols=["OLD", "NEW"],
        start=datetime.date(2026, 2, 10),
        end=datetime.date(2026, 2, 20),
        warmup_bars=30,
        max_gap_factor=1.5,
    )

    assert "OLD" in universe.series
    assert "NEW" not in universe.series
    assert "insufficient_warmup" in universe.excluded["NEW"]


def test_auto_start_is_not_confused_by_weekend_bars(db_session: Session) -> None:
    """Live-hit on 15.08.2026: the automatic window indexed into the *union* of all
    bar dates. Crypto trades weekends, equities do not, so the 61st calendar entry
    was only the ~43rd trading day for a stock — every one of the 656 symbols failed
    the 60-bar warmup check and the run produced an empty universe.

    The start now comes from the longest series, so a fully-covered equity qualifies.
    """
    base = datetime.datetime(2026, 1, 5)
    for index in range(60):
        weekday = base + datetime.timedelta(days=index)
        # The equity skips weekends; the crypto pair does not.
        if weekday.weekday() < 5:
            _add_bar(db_session, "STOCK", weekday)
        _add_bar(db_session, "COIN/USD", weekday)
    db_session.flush()

    universe = load_universe(
        db_session,
        symbols=["STOCK", "COIN/USD"],
        start=None,
        end=None,
        warmup_bars=30,
        max_gap_factor=1.5,
    )

    assert "COIN/USD" in universe.series
    assert universe.trading_days, "the run must not come out empty"
    # The crypto pair is the longest series, so its 31st bar sets the start.
    assert universe.start == (base + datetime.timedelta(days=30)).date()


def test_trading_days_come_from_participating_symbols_only(db_session: Session) -> None:
    """A symbol thrown out by the quality gate must not keep contributing calendar
    days — an equity strategy would get flat weekend points whose zero returns land
    straight in the Sortino denominator."""
    base = datetime.datetime(2026, 1, 5)
    for index in range(60):
        weekday = base + datetime.timedelta(days=index)
        if weekday.weekday() < 5:
            _add_bar(db_session, "STOCK", weekday)
    for index in range(5):  # too short — will be excluded
        _add_bar(db_session, "COIN/USD", base + datetime.timedelta(days=index))
    db_session.flush()

    universe = load_universe(
        db_session,
        symbols=["STOCK", "COIN/USD"],
        start=None,
        end=None,
        warmup_bars=20,
        max_gap_factor=1.5,
    )

    assert "COIN/USD" in universe.excluded
    assert all(day.weekday() < 5 for day in universe.trading_days)


def _add_bar(session: Session, symbol: str, ts: datetime.datetime) -> None:
    session.add(
        MarketBar(
            symbol=symbol,
            timeframe=MarketBarTimeframe.DAY,
            ts=ts,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("1000000"),
        )
    )


def test_missing_history_raises_rather_than_guessing(db_session: Session) -> None:
    with pytest.raises(InsufficientDataError):
        load_universe(
            db_session,
            symbols=["DOES-NOT-EXIST"],
            start=None,
            end=None,
            warmup_bars=60,
            max_gap_factor=1.5,
        )
