"""CLI entrypoint — F111 §5.2 and §10.

`python -m src.backtest.run` is the *only* way to start a backtest, so its
argument handling and its refusal paths are load-bearing rather than cosmetic.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy.orm import Session

from src.backtest.run import (
    _date,
    _json_default,
    _select,
    _symbols_for,
    build_parser,
    load_settings,
    main,
)
from src.backtest.spec import DEFAULT_STRATEGY_DIR, load_all_strategies
from src.db.models import BacktestRun, BacktestRunStatus, MarketBar, MarketBarTimeframe

_ALL = load_all_strategies(DEFAULT_STRATEGY_DIR)


def test_settings_come_from_config_not_from_code():
    """Every number that shapes a run has to be in `config/backtest/engine.yaml`,
    because the artefact stores it and a reader must be able to reproduce it."""
    settings = load_settings()

    assert settings.engine.start_capital_usd == 5000
    assert settings.engine.conviction == 1.0
    assert settings.warmup_bars == 60
    assert settings.thresholds.min_trading_days == 60
    assert settings.thresholds.min_trades == 10
    assert settings.reference_symbol == "SPY"
    assert settings.engine.slippage["enabled"] is True


def test_parser_defaults_are_conservative():
    args = build_parser().parse_args([])

    assert args.strategy == []
    assert args.all is False
    assert args.no_save is False
    assert args.start is None and args.end is None


def test_parser_accepts_repeated_strategies_and_dates():
    args = build_parser().parse_args(
        ["--strategy", "a", "--strategy", "b", "--from", "2026-05-13", "--to", "2026-08-15"]
    )

    assert args.strategy == ["a", "b"]
    assert args.start == datetime.date(2026, 5, 13)
    assert args.end == datetime.date(2026, 8, 15)


def test_select_all_returns_every_spec():
    assert _select(_ALL, [], True) == _ALL


def test_select_by_name():
    selected = _select(_ALL, ["contra-proxy"], False)

    assert [spec.name for spec in selected] == ["contra-proxy"]


def test_unknown_strategy_is_skipped_with_a_message(capsys):
    """A typo must not silently run the wrong field — it names what it knows."""
    selected = _select(_ALL, ["contra-proxy", "does-not-exist"], False)

    assert [spec.name for spec in selected] == ["contra-proxy"]
    assert "does-not-exist" in capsys.readouterr().err


def test_symbols_none_when_any_spec_needs_the_full_universe():
    """Loading a subset for one spec while another needs everything would fragment
    the shared data fingerprint."""
    equities = next(spec for spec in _ALL if spec.universe.symbols is None)
    crypto = next(spec for spec in _ALL if spec.universe.symbols is not None)

    assert _symbols_for([equities, crypto]) is None


def test_symbols_are_the_union_of_explicit_lists():
    crypto = next(spec for spec in _ALL if spec.universe.symbols is not None)

    symbols = _symbols_for([crypto])

    assert symbols == sorted(crypto.universe.symbols or [])


def test_list_prints_the_strategies_and_exits_cleanly(capsys):
    code = main(["--list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "contra-proxy" in out
    assert "Nicht backtestbar" in out
    assert "GUARDIAN" in out


def test_no_strategy_selected_is_an_error(capsys):
    """Exit code 2, not a silent no-op: a scripted call must be able to notice."""
    code = main([])

    assert code == 2
    assert "Keine Strategie" in capsys.readouterr().err


def test_date_parsing_rejects_nonsense():
    assert _date("2026-08-15") == datetime.date(2026, 8, 15)
    with pytest.raises(ValueError):
        _date("15.08.2026")


def test_json_default_serialises_dates_and_enums():
    assert _json_default(datetime.date(2026, 8, 15)) == "2026-08-15"
    assert _json_default(BacktestRunStatus.OK) == "ok"


def _seed(session: Session, symbol: str, days: int = 130) -> None:
    start = datetime.datetime(2026, 1, 5)
    offset = 0
    added = 0
    while added < days:
        current = start + datetime.timedelta(days=offset)
        offset += 1
        if current.weekday() >= 5:
            continue
        close = 100 + (added % 7)
        session.add(
            MarketBar(
                symbol=symbol,
                timeframe=MarketBarTimeframe.DAY,
                ts=current,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=5_000_000,
            )
        )
        added += 1
    session.flush()


def test_end_to_end_run_without_saving(db_session: Session, monkeypatch, capsys, tmp_path):
    """The whole path: config -> universe -> engine -> artefact -> markdown, driven
    exactly as the documented command drives it."""
    _seed(db_session, "AAA")
    _seed(db_session, "SPY")
    monkeypatch.setattr("src.backtest.run.get_session_factory", lambda: lambda: db_session)
    json_path = tmp_path / "artefacts.json"

    code = main(["--strategy", "contra-proxy", "--no-save", "--json", str(json_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "# ATLAS-Backtest" in out
    assert "contra-proxy" in out
    # --no-save means exactly that.
    assert db_session.query(BacktestRun).count() == 0
    payload = json.loads(json_path.read_text())
    assert payload[0]["spec_name"] == "contra-proxy"
    assert payload[0]["data_fingerprint"]["sha256"]


def test_run_saves_when_asked(db_session: Session, monkeypatch, capsys):
    _seed(db_session, "AAA")
    monkeypatch.setattr("src.backtest.run.get_session_factory", lambda: lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    code = main(["--strategy", "contra-proxy"])

    assert code == 0
    assert db_session.query(BacktestRun).count() == 1


def test_insufficient_history_aborts_with_a_message(db_session: Session, monkeypatch, capsys):
    """Too little data is an outcome, not a crash — and it says why."""
    _seed(db_session, "AAA", days=5)
    monkeypatch.setattr("src.backtest.run.get_session_factory", lambda: lambda: db_session)

    code = main(["--strategy", "contra-proxy", "--no-save"])

    assert code == 1
    assert "Abbruch" in capsys.readouterr().err
