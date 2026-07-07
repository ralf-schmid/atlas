"""See docs/features/F021-persona-analysis-agent.md §3, tests 1-4."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import MarketBar, MarketBarTimeframe
from src.orchestrator.market_pricing import compute_atr14, get_latest_price


def _add_bar(
    session: Session,
    symbol: str,
    ts: datetime.datetime,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> None:
    session.add(
        MarketBar(
            symbol=symbol,
            timeframe=MarketBarTimeframe.DAY,
            ts=ts,
            open=Decimal(str(open_)),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
            volume=Decimal("1000000"),
        )
    )
    session.flush()


def test_get_latest_price_returns_most_recent_close(session: Session) -> None:
    _add_bar(
        session,
        "AAPL",
        datetime.datetime(2026, 7, 5),
        open_=100,
        high=101,
        low=99,
        close=100,
    )
    _add_bar(
        session,
        "AAPL",
        datetime.datetime(2026, 7, 6),
        open_=100,
        high=103,
        low=100,
        close=102,
    )

    price = get_latest_price(session, "AAPL")

    assert price == 102.0


def test_get_latest_price_returns_none_without_bars(session: Session) -> None:
    price = get_latest_price(session, "UNKNOWN")

    assert price is None


def test_compute_atr14_with_enough_bars(session: Session) -> None:
    base = datetime.datetime(2026, 6, 1)
    close = 100.0
    for i in range(15):
        _add_bar(
            session,
            "TEST",
            base + datetime.timedelta(days=i),
            open_=close,
            high=close + 2,
            low=close - 2,
            close=close,
        )
        close += 0.0  # constant close -> true range is always high-low = 4

    atr = compute_atr14(session, "TEST")

    assert atr == 4.0


def test_compute_atr14_returns_none_with_too_few_bars(session: Session) -> None:
    base = datetime.datetime(2026, 6, 1)
    for i in range(10):
        _add_bar(
            session,
            "TEST2",
            base + datetime.timedelta(days=i),
            open_=100,
            high=102,
            low=98,
            close=100,
        )

    atr = compute_atr14(session, "TEST2")

    assert atr is None
