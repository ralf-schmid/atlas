"""Markdown rendering — F111 §5.3.

The report is what Ralf actually reads, so the things that must never silently
disappear from it (disclaimer, caveats, the insufficient-data marking, the "this
is not a portfolio" note on the reference line) are asserted here rather than
trusted.
"""

from __future__ import annotations

import datetime

import pytest

from src.backtest.artifact import DISCLAIMER, Thresholds, attach_scores, build_result
from src.backtest.engine import run_backtest
from src.backtest.report import render_report, render_strategy_list
from src.db.models import BacktestRunStatus
from src.risk.config import load_system_guardrails
from tests.backtest.conftest import bar, day, engine_config, make_universe, simple_spec

SYSTEM = load_system_guardrails()
LENIENT = Thresholds(min_trading_days=1, min_trades=0)
STRICT = Thresholds(min_trading_days=60, min_trades=10)

_ENTRY = [{"signal": "close", "op": "gt", "value": 100}]


def _result(tmp_path, name: str, thresholds: Thresholds = LENIENT):
    spec = simple_spec(tmp_path, entry=_ENTRY, max_position_pct=0.05, name=name)
    universe = make_universe(
        {"AAA": [bar(offset, 105.0, open_=100.0) for offset in range(6)]}, first_day=day(1)
    )
    engine_result = run_backtest(spec, universe, engine_config(), SYSTEM)
    return build_result(spec, universe, engine_result, engine_config(), thresholds), universe


def test_report_carries_the_numbers_and_the_disclaimer(tmp_path):
    result, universe = _result(tmp_path, "alpha")

    text = render_report([result], universe, engine_config(), None, "SPY", 0.0458)

    assert "# ATLAS-Backtest" in text
    assert "alpha" in text
    assert f"{universe.start} bis {universe.end}" in text
    assert str(universe.fingerprint["sha256"])[:16] in text
    assert DISCLAIMER in text
    # Every caveat travels with the numbers, not in a separate document.
    for caveat in result.caveats:
        assert caveat in text


def test_reference_line_is_marked_as_not_a_portfolio(tmp_path):
    """F111 §6.4 — the SPY line must never read like a competing strategy."""
    result, universe = _result(tmp_path, "alpha")

    text = render_report([result], universe, engine_config(), None, "SPY", 0.0458)

    assert "+4.58 %" in text
    assert "kein simuliertes Portfolio" in text
    assert "kein Risk-Gate" in text


def test_reference_line_is_omitted_when_unavailable(tmp_path):
    result, universe = _result(tmp_path, "alpha")

    text = render_report([result], universe, engine_config(), None, "SPY", None)

    assert "Referenzlinie" not in text


def test_insufficient_data_is_visually_marked(tmp_path):
    """A thin run must not look like a normal one at a glance."""
    result, universe = _result(tmp_path, "alpha", STRICT)

    text = render_report([result], universe, engine_config(), None, "SPY", None)

    assert result.status is BacktestRunStatus.INSUFFICIENT_DATA
    assert "**insufficient_data**" in text
    # Sortino is withheld below the threshold and renders as a dash, not as 0.00.
    assert "| — |" in text


def test_score_section_names_the_counted_criteria(tmp_path):
    first, universe = _result(tmp_path, "alpha")
    second, _ = _result(tmp_path, "beta")
    for index, result in enumerate((first, second)):
        result.metrics["sortino"] = 1.0 + index
        result.metrics["return_net"] = 0.05 * (index + 1)
        result.metrics["max_drawdown"] = 0.10 * (index + 1)
    score = attach_scores([first, second])

    text = render_report([first, second], universe, engine_config(), score, "SPY", None)

    assert "## §4.7-Score" in text
    assert "Risiko-adj. Rendite (Sortino)" in text
    assert "Gezählte Kriterien" in text


def test_no_score_section_without_a_score(tmp_path):
    result, universe = _result(tmp_path, "alpha")

    text = render_report([result], universe, engine_config(), None, "SPY", None)

    # The heading, not the phrase: one of the fixed caveats mentions the score too.
    assert "## §4.7-Score" not in text


def test_risk_gate_rejections_are_reported_when_present(tmp_path):
    result, universe = _result(tmp_path, "alpha")
    result.metrics["risk_gate_rejections"] = {"min_cash_pct_violated": 7}

    text = render_report([result], universe, engine_config(), None, "SPY", None)

    assert "## Risk-Gate-Ablehnungen" in text
    assert "min_cash_pct_violated: 7" in text


def test_rejection_section_is_omitted_when_empty(tmp_path):
    result, universe = _result(tmp_path, "alpha")
    result.metrics["risk_gate_rejections"] = {}

    text = render_report([result], universe, engine_config(), None, "SPY", None)

    assert "## Risk-Gate-Ablehnungen" not in text


def test_strategies_are_listed_in_a_stable_order(tmp_path):
    """Two runs of the same field must produce byte-identical reports, or a diff
    between two artefacts is unreadable."""
    first, universe = _result(tmp_path, "zeta")
    second, _ = _result(tmp_path, "alpha")

    text = render_report([first, second], universe, engine_config(), None, "SPY", None)
    reversed_text = render_report([second, first], universe, engine_config(), None, "SPY", None)

    assert text == reversed_text
    assert text.index("| alpha ") < text.index("| zeta ")


def test_strategy_list_names_the_not_backtestable_personas():
    text = render_strategy_list(
        [("chartist-proxy", "  SMA-Crossover  ")],
        {"HYPE": "Zeitschriften-Tipps", "GUARDIAN": "Fundamentaldaten"},
    )

    assert "chartist-proxy" in text
    assert "SMA-Crossover" in text
    assert "Nicht backtestbar" in text
    assert "GUARDIAN: Fundamentaldaten" in text
    assert text.index("GUARDIAN") < text.index("HYPE")  # sorted, deterministic


def test_strategy_list_without_exclusions():
    text = render_strategy_list([("only-one", "beschreibung")], {})

    assert "Nicht backtestbar" not in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "—"), (0.0, "+0.00 %"), (-0.1234, "-12.34 %"), (0.05, "+5.00 %")],
)
def test_percentage_formatting(value, expected, tmp_path):
    """A missing number renders as a dash — never as 0.00 %, which would read as a
    measured zero."""
    from src.backtest.report import _pct

    assert _pct(value) == expected


def test_period_and_universe_counts_are_shown(tmp_path):
    result, universe = _result(tmp_path, "alpha")

    text = render_report([result], universe, engine_config(), None, "SPY", None)

    assert f"{len(universe.series)} Symbole" in text
    assert isinstance(universe.start, datetime.date)
