"""See docs/features/F025-cycle-scheduling.md §3, tests 1-2."""

from __future__ import annotations

from src.orchestrator.cycles_config import load_cycles_config


def test_loads_all_four_stock_cycles_from_config() -> None:
    config = load_cycles_config()

    assert config.stock_timezone == "America/New_York"
    assert [c.seq for c in config.stock_cycles] == [1, 2, 3, 4]
    assert [c.time for c in config.stock_cycles] == ["09:00", "10:30", "13:00", "15:15"]
    assert all(c.active for c in config.stock_cycles)


def test_loads_crypto_weekday_and_weekend_times() -> None:
    config = load_cycles_config()

    assert config.crypto_timezone == "UTC"
    assert config.crypto_weekday_times == ["00:00", "06:00", "12:00", "18:00"]
    assert config.crypto_weekend_times == ["06:00", "18:00"]


def test_loads_digest_time() -> None:
    config = load_cycles_config()

    assert config.digest_time == "16:30"
