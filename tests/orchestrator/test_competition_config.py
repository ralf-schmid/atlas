"""load_competition_config must handle YAML's date auto-parsing — regression for
the F090 bug where an unquoted `start_date: 2026-07-27` is parsed by yaml.safe_load
into a datetime.date, which date.fromisoformat() then rejected."""

from __future__ import annotations

import datetime
from pathlib import Path

from src.orchestrator.competition_config import load_competition_config


def test_loads_the_real_committed_config() -> None:
    """The shipped config/competition.yaml must load without crashing (it uses an
    unquoted ISO date → a date object)."""
    config = load_competition_config()
    assert isinstance(config.start_date, datetime.date)
    assert config.start_capital_usd == 5000


def test_unquoted_date_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "competition.yaml"
    path.write_text("competition:\n  start_date: 2026-07-27\n  start_capital_usd: 5000\n")
    config = load_competition_config(path)
    assert config.start_date == datetime.date(2026, 7, 27)


def test_quoted_string_date_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "competition.yaml"
    path.write_text('competition:\n  start_date: "2026-07-27"\n  start_capital_usd: 5000\n')
    config = load_competition_config(path)
    assert config.start_date == datetime.date(2026, 7, 27)
