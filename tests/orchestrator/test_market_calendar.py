"""See docs/features/F124-handelskalender-gate.md §4, tests 1-9. No network: every
test drives a fake `CalendarSource`."""

from __future__ import annotations

import datetime
import logging

import pytest
from alpaca.trading.models import Calendar

from src.orchestrator import market_calendar as market_calendar_module
from src.orchestrator.market_calendar import (
    MarketCalendar,
    TradingDay,
    get_market_calendar,
)

_ET = datetime.timezone(datetime.timedelta(hours=-4))  # EDT; only the wall clock matters

# A regular session and a half-day, as Alpaca reports them (exchange-local times).
_REGULAR = TradingDay(
    date=datetime.date(2026, 9, 17),
    open_time=datetime.time(9, 30),
    close_time=datetime.time(16, 0),
)
_HALF_DAY = TradingDay(
    date=datetime.date(2026, 11, 27),
    open_time=datetime.time(9, 30),
    close_time=datetime.time(13, 0),
)


class _FakeSource:
    def __init__(self, days: list[TradingDay]) -> None:
        self._days = days
        self.calls: list[tuple[datetime.date, datetime.date]] = []

    def fetch(self, start: datetime.date, end: datetime.date) -> list[TradingDay]:
        self.calls.append((start, end))
        return [d for d in self._days if start <= d.date <= end]


class _FailingSource:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, start: datetime.date, end: datetime.date) -> list[TradingDay]:
        self.calls += 1
        raise RuntimeError("alpaca unreachable")


def _at(day: datetime.date, hour: int, minute: int) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=_ET)


def test_pre_market_cycle_is_allowed_on_a_regular_trading_day() -> None:
    """C1 runs at 09:00 ET, 30 minutes before the bell, by design — the gate must
    not check the open (ADR-0019 (2))."""
    calendar = MarketCalendar(_FakeSource([_REGULAR]))

    verdict = calendar.evaluate(_at(_REGULAR.date, 9, 0))

    assert verdict.allowed
    assert verdict.reason == "trading_day"


@pytest.mark.parametrize(("hour", "minute"), [(13, 0), (15, 15)])
def test_intraday_cycles_are_allowed_on_a_regular_trading_day(hour: int, minute: int) -> None:
    calendar = MarketCalendar(_FakeSource([_REGULAR]))

    assert calendar.evaluate(_at(_REGULAR.date, hour, minute)).allowed


def test_holiday_is_rejected() -> None:
    """Alpaca returns only open days — a date missing from the response is closed."""
    calendar = MarketCalendar(_FakeSource([_REGULAR]))

    verdict = calendar.evaluate(_at(datetime.date(2026, 11, 26), 9, 0))  # Thanksgiving

    assert not verdict.allowed
    assert verdict.reason == "not_a_trading_day"


def test_half_day_allows_the_morning_cycle_but_not_the_afternoon_ones() -> None:
    calendar = MarketCalendar(_FakeSource([_HALF_DAY]))

    assert calendar.evaluate(_at(_HALF_DAY.date, 9, 0)).allowed
    # Exactly at the close counts as closed: orders would go into a shut market.
    at_close = calendar.evaluate(_at(_HALF_DAY.date, 13, 0))
    after_close = calendar.evaluate(_at(_HALF_DAY.date, 15, 15))
    assert not at_close.allowed
    assert at_close.reason == "after_close"
    assert not after_close.allowed
    assert after_close.reason == "after_close"


def test_unavailable_calendar_falls_open_with_a_warning(caplog) -> None:
    """ADR-0019 (1): a fetch failure must never silently swallow a real trading
    day. WARNING, not ERROR — degraded, not broken."""
    calendar = MarketCalendar(_FailingSource())
    caplog.set_level(logging.WARNING, logger=market_calendar_module.logger.name)

    verdict = calendar.evaluate(_at(_REGULAR.date, 9, 0))

    assert verdict.allowed
    assert verdict.reason == "calendar_unavailable"
    (record,) = [r for r in caplog.records if r.name == market_calendar_module.logger.name]
    assert record.levelno == logging.WARNING


def test_second_lookup_of_the_same_day_is_served_from_cache() -> None:
    source = _FakeSource([_REGULAR])
    calendar = MarketCalendar(source)

    calendar.evaluate(_at(_REGULAR.date, 9, 0))
    calendar.evaluate(_at(_REGULAR.date, 13, 0))

    assert len(source.calls) == 1


def test_date_outside_the_cached_window_triggers_a_refetch() -> None:
    source = _FakeSource([_REGULAR, _HALF_DAY])
    calendar = MarketCalendar(source)

    calendar.evaluate(_at(_REGULAR.date, 9, 0))  # window: 17.09. + 45 days
    verdict = calendar.evaluate(_at(_HALF_DAY.date, 9, 0))  # 27.11. — beyond it

    assert len(source.calls) == 2
    assert verdict.allowed


def test_a_failed_fetch_is_not_cached() -> None:
    """Caching the failure would freeze "no trading days" until the next restart
    and block every cycle — the opposite of fail-open."""
    source = _FailingSource()
    calendar = MarketCalendar(source)

    calendar.evaluate(_at(_REGULAR.date, 9, 0))
    calendar.evaluate(_at(_REGULAR.date, 13, 0))

    assert source.calls == 2


def test_get_market_calendar_returns_the_same_instance(monkeypatch) -> None:
    """A per-call instance would throw the cache away every cycle."""
    monkeypatch.setattr(market_calendar_module, "_calendar", None)

    assert get_market_calendar() is get_market_calendar()


# --- AlpacaCalendarSource: the mapping Alpaca -> TradingDay --------------------


class _FakeTradingClient:
    def __init__(self, response: object, **kwargs: object) -> None:
        self.response = response
        self.kwargs = kwargs
        self.requests: list[object] = []

    def get_calendar(self, filters: object = None) -> object:
        self.requests.append(filters)
        return self.response


@pytest.fixture
def _fake_credentials(monkeypatch):
    monkeypatch.setattr(
        market_calendar_module, "load_market_data_credentials", lambda: ("key", "secret")
    )


def _install_trading_client(monkeypatch, response: object) -> list[_FakeTradingClient]:
    built: list[_FakeTradingClient] = []

    def _factory(**kwargs: object) -> _FakeTradingClient:
        client = _FakeTradingClient(response, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(market_calendar_module, "TradingClient", _factory)
    return built


def test_source_maps_alpacas_naive_datetimes_to_exchange_local_times(
    monkeypatch, _fake_credentials
) -> None:
    """`Calendar.open`/`.close` arrive as naive datetimes in exchange-local time —
    alpaca-py concatenates the date with the API's "%H:%M" string."""
    calendar_row = Calendar(date="2026-11-27", open="09:30", close="13:00")
    built = _install_trading_client(monkeypatch, [calendar_row])
    source = market_calendar_module.AlpacaCalendarSource()

    days = source.fetch(datetime.date(2026, 11, 1), datetime.date(2026, 12, 1))

    assert days == [
        TradingDay(
            date=datetime.date(2026, 11, 27),
            open_time=datetime.time(9, 30),
            close_time=datetime.time(13, 0),
        )
    ]
    # Paper endpoint, shared market-data key — never a persona key, never live.
    assert built[0].kwargs == {"api_key": "key", "secret_key": "secret", "paper": True}


def test_source_builds_its_client_once(monkeypatch, _fake_credentials) -> None:
    built = _install_trading_client(monkeypatch, [])
    source = market_calendar_module.AlpacaCalendarSource()

    source.fetch(datetime.date(2026, 11, 1), datetime.date(2026, 12, 1))
    source.fetch(datetime.date(2027, 1, 1), datetime.date(2027, 2, 1))

    assert len(built) == 1


def test_source_rejects_an_unexpected_response_shape(monkeypatch, _fake_credentials) -> None:
    """`get_calendar` is typed `list | dict`; a dict means raw_data and must not be
    silently read as "no trading days"."""
    _install_trading_client(monkeypatch, {"calendar": []})
    source = market_calendar_module.AlpacaCalendarSource()

    with pytest.raises(TypeError, match="unexpected get_calendar response"):
        source.fetch(datetime.date(2026, 11, 1), datetime.date(2026, 12, 1))
