"""See docs/features/F025-cycle-scheduling.md §3, tests 4-6 and
docs/features/F029-scheduler-logging-alert.md §3, tests 1-4. `build_scheduler` is
never `.start()`ed — pure job-registration inspection, no real time trigger."""

from __future__ import annotations

import pytest

from src.db.models import MarketSession
from src.orchestrator import scheduler as scheduler_module
from src.orchestrator.cycles_config import CyclesConfig, StockCycle, load_cycles_config
from src.orchestrator.scheduler import _run_cycle_job, build_scheduler
from src.telegram.config import TelegramConfig


def _field(job: object, name: str) -> str:
    for f in job.trigger.fields:  # type: ignore[attr-defined]
        if f.name == name:
            return str(f)
    raise AssertionError(f"no field {name!r} on trigger")


def test_build_scheduler_registers_all_active_cycles() -> None:
    config = load_cycles_config()

    scheduler = build_scheduler(graph=None, session_factory=lambda: None, cycles_config=config)  # type: ignore[arg-type]

    jobs = scheduler.get_jobs()
    stock_jobs = [j for j in jobs if j.id.startswith("stock-")]
    crypto_jobs = [j for j in jobs if j.id.startswith("crypto-")]
    assert len(stock_jobs) == 4
    assert len(crypto_jobs) == 4 + 2  # weekday + weekend times


def test_build_scheduler_skips_inactive_stock_cycle() -> None:
    config = CyclesConfig(
        stock_timezone="America/New_York",
        stock_cycles=[
            StockCycle(seq=1, time="09:00", active=True),
            StockCycle(seq=2, time="10:30", active=False),
        ],
        crypto_timezone="UTC",
        crypto_weekday_times=["00:00"],
        crypto_weekend_times=["06:00"],
    )

    scheduler = build_scheduler(graph=None, session_factory=lambda: None, cycles_config=config)  # type: ignore[arg-type]

    stock_jobs = [j for j in scheduler.get_jobs() if j.id.startswith("stock-")]
    assert len(stock_jobs) == 1
    assert stock_jobs[0].id == "stock-c1"


def test_stock_jobs_use_exchange_timezone_and_crypto_jobs_use_utc() -> None:
    config = load_cycles_config()

    scheduler = build_scheduler(graph=None, session_factory=lambda: None, cycles_config=config)  # type: ignore[arg-type]

    stock_job = scheduler.get_job("stock-c1")
    crypto_job = scheduler.get_job("crypto-weekday-00:00")
    assert str(stock_job.trigger.timezone) == "America/New_York"
    assert str(crypto_job.trigger.timezone) == "UTC"
    assert _field(stock_job, "hour") == "9"
    assert _field(stock_job, "minute") == "0"


def test_stock_jobs_are_restricted_to_weekdays() -> None:
    # F061: unlike crypto (day_of_week="mon-fri"/"sat,sun" explicitly set for its
    # two job groups), stock cycles had no day_of_week filter at all and would
    # fire on a closed weekend market.
    config = load_cycles_config()

    scheduler = build_scheduler(graph=None, session_factory=lambda: None, cycles_config=config)  # type: ignore[arg-type]

    for seq in (1, 2, 3, 4):
        stock_job = scheduler.get_job(f"stock-c{seq}")
        assert _field(stock_job, "day_of_week") == "mon-fri"


@pytest.fixture(autouse=True)
def _reset_failure_counters():
    scheduler_module._consecutive_failures.clear()
    yield
    scheduler_module._consecutive_failures.clear()


@pytest.fixture
def _fake_telegram_config(monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "load_telegram_config",
        lambda: TelegramConfig(bot_token="test-token", allowed_chat_id=1),
    )


def test_run_cycle_job_logs_structured_error_on_failure(monkeypatch) -> None:
    # Not caplog: alembic's `command.upgrade` (session-scoped `_migrated_schema`
    # fixture, autouse in this directory) calls `fileConfig`, which — by its own
    # `disable_existing_loggers=True` default — disables every logger that already
    # existed at that point, including this module's. Spying on `logger.error`
    # directly sidesteps that global logging-plumbing quirk entirely.
    def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(scheduler_module, "run_one_cycle", _raise)
    calls = []
    monkeypatch.setattr(scheduler_module.logger, "error", lambda *a, **k: calls.append((a, k)))

    _run_cycle_job(None, lambda: None, 1, MarketSession.US_EQUITY, "America/New_York")  # type: ignore[arg-type]

    (call,) = calls
    args, kwargs = call
    assert args[0] == "cycle failed"
    assert kwargs["extra"]["seq"] == 1
    assert kwargs["extra"]["market_session"] == "us_equity"


def test_run_cycle_job_does_not_alert_on_first_failure(monkeypatch, _fake_telegram_config) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(scheduler_module, "run_one_cycle", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    _run_cycle_job(None, lambda: None, 1, MarketSession.US_EQUITY, "America/New_York")  # type: ignore[arg-type]

    assert sent == []


def test_run_cycle_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(scheduler_module, "run_one_cycle", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    _run_cycle_job(None, lambda: None, 1, MarketSession.US_EQUITY, "America/New_York")  # type: ignore[arg-type]
    _run_cycle_job(None, lambda: None, 1, MarketSession.US_EQUITY, "America/New_York")  # type: ignore[arg-type]

    assert len(sent) == 1
    assert "2x in Folge" in sent[0]


def test_run_cycle_job_resets_failure_streak_on_success(monkeypatch, _fake_telegram_config) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(scheduler_module, "run_one_cycle", _raise)
    _run_cycle_job(None, lambda: None, 1, MarketSession.US_EQUITY, "America/New_York")  # type: ignore[arg-type]

    monkeypatch.setattr(scheduler_module, "run_one_cycle", lambda *a, **k: {})
    _run_cycle_job(None, lambda: None, 1, MarketSession.US_EQUITY, "America/New_York")  # type: ignore[arg-type]

    assert scheduler_module._consecutive_failures["us_equity-1"] == 0
