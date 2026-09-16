"""Alpaca trading-calendar lookup behind the US-equity cycle gate.

See docs/features/F124-handelskalender-gate.md and
docs/adr/0019-handelskalender-gate-fail-open.md. Deterministic code, no LLM — this
decides whether a cycle runs at all, never what it decides.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Protocol

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

from src.broker.registry import load_market_data_credentials

logger = logging.getLogger(__name__)

# One fetch covers roughly two months of cycles. Wide enough that a long-running
# scheduler refetches only a handful of times a year, narrow enough that the first
# call after a container restart stays small.
_FETCH_WINDOW_DAYS = 45

REASON_TRADING_DAY = "trading_day"
REASON_NOT_A_TRADING_DAY = "not_a_trading_day"
REASON_AFTER_CLOSE = "after_close"
REASON_CALENDAR_UNAVAILABLE = "calendar_unavailable"


@dataclass(frozen=True, slots=True)
class TradingDay:
    """One open exchange day. Times are exchange-local (America/New_York) — see
    `AlpacaCalendarSource.fetch` for why they arrive as naive datetimes."""

    date: datetime.date
    open_time: datetime.time
    close_time: datetime.time


@dataclass(frozen=True, slots=True)
class CalendarVerdict:
    allowed: bool
    reason: str


class CalendarSource(Protocol):
    def fetch(self, start: datetime.date, end: datetime.date) -> list[TradingDay]: ...


class AlpacaCalendarSource:
    """`TradingClient.get_calendar` over the shared, persona-independent market-data
    key (config/broker.yaml) — the exchange calendar is account-independent
    infrastructure, so coupling it to a persona key would invent a dependency that
    doesn't exist (ADR-0019 (5)).

    Credentials are resolved on the first fetch, not in `__init__`: a missing key
    has to surface as a fail-open calendar lookup, not as an exception while the
    scheduler is still registering its jobs.
    """

    def __init__(self) -> None:
        self._client: TradingClient | None = None

    def _get_client(self) -> TradingClient:
        if self._client is None:
            api_key, secret_key = load_market_data_credentials()
            self._client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
        return self._client

    def fetch(self, start: datetime.date, end: datetime.date) -> list[TradingDay]:
        """Alpaca returns only the *open* days in the range — a date missing from
        the response is a weekend or a holiday.

        `Calendar.open`/`.close` are naive `datetime`s in exchange-local time, not
        `time` and not UTC: `Calendar.__init__` concatenates the date with the
        API's `"%H:%M"` string (verified against alpaca-py 0.43.5). Only the time
        part is kept here, and it is compared against a `now` in the exchange
        timezone.
        """
        calendars = self._get_client().get_calendar(GetCalendarRequest(start=start, end=end))
        if not isinstance(calendars, list):
            raise TypeError(f"unexpected get_calendar response type: {type(calendars)!r}")
        return [
            TradingDay(date=c.date, open_time=c.open.time(), close_time=c.close.time())
            for c in calendars
        ]


class MarketCalendar:
    """Caches the exchange calendar for a moving window in process memory.

    A given date's calendar never changes, so the cache needs no invalidation — the
    window simply moves forward (ADR-0019 (3)). A *failed* fetch is deliberately
    not cached: caching it would freeze "this window has no trading days" and block
    every cycle until the next restart, which is exactly what the fail-open
    decision is meant to prevent.
    """

    def __init__(self, source: CalendarSource) -> None:
        self._source = source
        self._days: dict[datetime.date, TradingDay] = {}
        self._covered: tuple[datetime.date, datetime.date] | None = None

    def evaluate(self, now: datetime.datetime) -> CalendarVerdict:
        """`now` must be in the exchange timezone — the close comparison is
        exchange-local (see `AlpacaCalendarSource.fetch`)."""
        day = now.date()
        try:
            self._ensure_covered(day)
        except Exception:
            # Fail-open (ADR-0019 (1)): WARNING, not ERROR — the gate is degraded,
            # not broken, and this is exactly the pre-F124 behaviour.
            logger.warning(
                "trading calendar unavailable, cycle gate falls open",
                exc_info=True,
                extra={"trading_day": day.isoformat()},
            )
            return CalendarVerdict(allowed=True, reason=REASON_CALENDAR_UNAVAILABLE)

        trading_day = self._days.get(day)
        if trading_day is None:
            return CalendarVerdict(allowed=False, reason=REASON_NOT_A_TRADING_DAY)
        # Only the close is checked, never the open: C1 runs at 09:00 ET, 30 minutes
        # before the bell, by design (ARCHITECTURE.md §5.2). `>=` because a cycle
        # starting exactly at the close would place its orders into a shut market.
        if now.time() >= trading_day.close_time:
            return CalendarVerdict(allowed=False, reason=REASON_AFTER_CLOSE)
        return CalendarVerdict(allowed=True, reason=REASON_TRADING_DAY)

    def _ensure_covered(self, day: datetime.date) -> None:
        if self._covered is not None and self._covered[0] <= day <= self._covered[1]:
            return
        end = day + datetime.timedelta(days=_FETCH_WINDOW_DAYS)
        fetched = self._source.fetch(day, end)
        # Committed only after a successful fetch — an exception above leaves the
        # previous cache untouched and the next call retries.
        self._days = {d.date: d for d in fetched}
        self._covered = (day, end)


_calendar: MarketCalendar | None = None


def get_market_calendar() -> MarketCalendar:
    """Process-wide singleton — a per-call instance would throw the cache away and
    turn every cycle into an API call."""
    global _calendar
    if _calendar is None:
        _calendar = MarketCalendar(AlpacaCalendarSource())
    return _calendar
