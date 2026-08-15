"""Artefact persistence and lineage — F111 §8, tests 22-23."""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.backtest.artifact import compute_lineage, save_run
from src.db.models import BacktestRun, BacktestRunStatus


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "spec_name": "chartist-proxy",
        "status": BacktestRunStatus.OK,
        "period_start": datetime.date(2026, 5, 13),
        "period_end": datetime.date(2026, 8, 15),
        "strategy_spec": {"name": "chartist-proxy", "entry": [{"signal": "rsi14"}]},
        "config": {"start_capital_usd": 5000, "conviction": 1.0},
        "data_fingerprint": {"sha256": "abc", "bars": 100, "symbols": 3},
        "metrics": {"return_net": 0.05, "sortino": 1.2},
        "caveats": ["Survivorship Bias"],
        "equity_curve": [["2026-05-13", 5000.0]],
        "trades": [{"symbol": "AAPL", "action": "buy"}],
    }
    payload.update(overrides)
    return payload


def test_a_run_persists_every_contract_field(db_session: Session) -> None:
    """Test 23a. The migration ran (test 22 implicitly — this suite is on head) and
    the row carries the whole F111 §4 contract."""
    run = save_run(db_session, _payload())
    db_session.flush()

    stored = db_session.scalar(select(BacktestRun).where(BacktestRun.id == run.id))
    assert stored is not None
    assert stored.spec_name == "chartist-proxy"
    assert stored.status is BacktestRunStatus.OK
    assert stored.data_fingerprint["sha256"] == "abc"
    assert stored.strategy_spec["name"] == "chartist-proxy"
    assert stored.caveats == ["Survivorship Bias"]
    assert stored.parent_run_id is None
    assert stored.lineage["changed"] == {}


def test_the_second_run_links_and_diffs_its_parent(db_session: Session) -> None:
    """Test 23b. "Was wurde gegenüber dem Vorlauf geändert" — without this a changed
    number cannot be attributed to a changed rule, a changed parameter or re-synced
    bars."""
    first = save_run(db_session, _payload())
    db_session.flush()

    second = save_run(
        db_session,
        _payload(
            strategy_spec={"name": "chartist-proxy", "entry": [{"signal": "macd_histogram"}]},
            data_fingerprint={"sha256": "def", "bars": 105, "symbols": 3},
            period_end=datetime.date(2026, 8, 22),
        ),
    )
    db_session.flush()

    assert second.parent_run_id == first.id
    changed = second.lineage["changed"]
    assert "strategy_spec" in changed
    assert changed["data_fingerprint"]["sha256"] == {"before": "abc", "after": "def"}
    assert changed["data_fingerprint"]["bars"] == {"before": 100, "after": 105}
    assert changed["period_end"] == {"before": "2026-08-15", "after": "2026-08-22"}


def test_an_unchanged_rerun_reports_no_change(db_session: Session) -> None:
    """The useful signal: identical spec, identical data, identical result — the
    lineage says so explicitly instead of leaving it to be inferred."""
    save_run(db_session, _payload())
    db_session.flush()
    second = save_run(db_session, _payload())
    db_session.flush()

    assert second.lineage["changed"] == {}
    assert second.parent_run_id is not None


def test_lineage_of_a_first_run_is_explicit() -> None:
    lineage = compute_lineage(None, _payload())
    assert lineage["parent_run_id"] is None
    assert "erster Lauf" in lineage["note"]


def test_runs_of_different_specs_do_not_chain(db_session: Session) -> None:
    """Lineage is per strategy: chaining chartist onto contra would claim a
    comparison that was never made."""
    save_run(db_session, _payload(spec_name="chartist-proxy"))
    db_session.flush()
    other = save_run(db_session, _payload(spec_name="contra-proxy"))
    db_session.flush()

    assert other.parent_run_id is None
