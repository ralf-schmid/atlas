"""See docs/features/F025-cycle-scheduling.md §3, tests 4-6. `build_scheduler` is
never `.start()`ed — pure job-registration inspection, no real time trigger."""

from __future__ import annotations

from src.orchestrator.cycles_config import CyclesConfig, StockCycle, load_cycles_config
from src.orchestrator.scheduler import build_scheduler


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
