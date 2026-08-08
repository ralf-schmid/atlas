"""See docs/features/F025-cycle-scheduling.md §3, tests 1-2."""

from __future__ import annotations

from src.orchestrator.cycles_config import load_cycles_config


def test_loads_all_stock_cycles_including_the_deactivated_one() -> None:
    """All four cycles stay declared; C2 is switched off rather than deleted so the
    cost throttling of 08.08.2026 is a one-line revert (F102 §1)."""
    config = load_cycles_config()

    assert config.stock_timezone == "America/New_York"
    assert [c.seq for c in config.stock_cycles] == [1, 2, 3, 4]
    assert [c.time for c in config.stock_cycles] == ["09:00", "10:30", "13:00", "15:15"]
    assert [c.seq for c in config.stock_cycles if c.active] == [1, 3, 4]


def test_loads_crypto_weekday_and_weekend_times() -> None:
    config = load_cycles_config()

    assert config.crypto_timezone == "UTC"
    # 00:00 UTC dropped with the same throttling — thinnest liquidity/news slot.
    assert config.crypto_weekday_times == ["06:00", "12:00", "18:00"]
    assert config.crypto_weekend_times == ["06:00", "18:00"]


def test_loads_digest_time() -> None:
    config = load_cycles_config()

    assert config.digest_time == "16:30"
