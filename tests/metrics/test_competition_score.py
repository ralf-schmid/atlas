"""F089: the §4.7 scoring rules. Pure functions first, DB-backed inputs after."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.db.models import AgentRunStatus, DecisionAction, DecisionStatus, OrderRecordStatus
from src.metrics.competition_score import (
    CRITERION_WEIGHTS,
    PersonaCriteria,
    ReliabilityInputs,
    normalize_min_max,
    reliability_inputs,
    score_personas,
    thesis_quality,
)
from tests.db.factories import (
    make_agent_run,
    make_cycle,
    make_decision,
    make_order_record,
    make_persona,
    make_portfolio,
    make_research_item,
    make_review,
)

_SINCE = datetime.date(2026, 7, 27)
_SINCE_TS = datetime.datetime(2026, 7, 27)


def _criteria(
    persona: str,
    *,
    sortino: float | None = 1.0,
    adjusted_return: float = 0.0,
    max_drawdown: float = 0.0,
    thesis: float | None = 1.0,
    reliability: float | None = 1.0,
) -> PersonaCriteria:
    return PersonaCriteria(
        persona=persona,
        sortino=sortino,
        adjusted_return=adjusted_return,
        max_drawdown=max_drawdown,
        thesis_quality=thesis,
        reliability=reliability,
        reliability_inputs=ReliabilityInputs(None, None, None),
        reviews_total=0,
        trades=0,
    )


def test_weights_match_architecture_section_4_7() -> None:
    """These five numbers decide who goes live with real money — a silent edit
    here would rewrite the competition (CLAUDE.md)."""
    assert CRITERION_WEIGHTS == {
        "sortino": 0.40,
        "adjusted_return": 0.25,
        "max_drawdown": 0.15,
        "thesis_quality": 0.10,
        "reliability": 0.10,
    }
    assert sum(CRITERION_WEIGHTS.values()) == pytest.approx(1.0)


def test_normalize_min_max_maps_best_to_one_and_worst_to_zero() -> None:
    assert normalize_min_max({"a": 0.10, "b": 0.05, "c": 0.0}) == {"a": 1.0, "b": 0.5, "c": 0.0}


def test_normalize_min_max_inverts_when_lower_is_better() -> None:
    result = normalize_min_max({"a": 0.20, "b": 0.0}, higher_is_better=False)

    assert result == {"a": 0.0, "b": 1.0}


def test_normalize_min_max_gives_a_tied_field_the_neutral_half() -> None:
    """Week one has every persona at exactly 0.00 % — picking a winner out of
    that would be noise, not a result."""
    assert normalize_min_max({"a": 0.0, "b": 0.0, "c": 0.0}) == {"a": 0.5, "b": 0.5, "c": 0.5}


def test_score_personas_ranks_by_the_weighted_sum() -> None:
    best_return = _criteria("VULTURE", sortino=0.0, adjusted_return=0.10)
    best_risk = _criteria("GUARDIAN", sortino=2.0, adjusted_return=0.0)
    score = score_personas([best_return, best_risk], _SINCE)

    # Sortino (40 %) outweighs return (25 %), so the risk-adjusted persona wins.
    assert [p.persona for p in score.personas] == ["GUARDIAN", "VULTURE"]
    assert [p.rank for p in score.personas] == [1, 2]


def test_score_personas_counts_drawdown_inversely() -> None:
    shallow = _criteria("GUARDIAN", max_drawdown=0.01)
    deep = _criteria("VULTURE", max_drawdown=0.30)

    score = score_personas([shallow, deep], _SINCE)

    assert score.personas[0].persona == "GUARDIAN"
    assert score.personas[0].normalized["max_drawdown"] == 1.0
    assert score.personas[1].normalized["max_drawdown"] == 0.0


def test_score_personas_drops_criteria_nobody_can_report_yet() -> None:
    """Sortino needs 20 daily returns and reviews need closed positions — in week
    one both are None for everyone. Scoring them as 0 would be a measurement
    artefact, so they drop out and their weight is redistributed."""
    field = [
        _criteria("VULTURE", sortino=None, thesis=None, adjusted_return=0.10),
        _criteria("GUARDIAN", sortino=None, thesis=None, adjusted_return=0.0),
    ]

    score = score_personas(field, _SINCE)

    assert set(score.counted_criteria) == {"adjusted_return", "max_drawdown", "reliability"}
    assert set(score.skipped_criteria) == {"sortino", "thesis_quality"}
    assert sum(score.effective_weights.values()) == pytest.approx(1.0)
    # 0.25 / (0.25 + 0.15 + 0.10) = 0.5
    assert score.effective_weights["adjusted_return"] == pytest.approx(0.5)


def test_score_personas_skips_a_criterion_only_part_of_the_field_has() -> None:
    """One persona with a review and five without must not be ranked on a
    yardstick that does not apply to the others."""
    field = [_criteria("VULTURE", thesis=1.0), _criteria("GUARDIAN", thesis=None)]

    score = score_personas(field, _SINCE)

    assert "thesis_quality" in score.skipped_criteria


def test_reliability_score_averages_the_available_sub_signals() -> None:
    inputs = ReliabilityInputs(error_rate=0.0, risk_reject_rate=0.5, fill_rate=1.0)

    # (1.0 + 0.5 + 1.0) / 3
    assert inputs.score() == pytest.approx(0.8333, abs=1e-4)


def test_reliability_score_is_none_without_any_signal() -> None:
    assert ReliabilityInputs(None, None, None).score() is None


def test_reliability_score_ignores_a_missing_fill_rate() -> None:
    """A persona that has not traded yet has no fill plausibility — that must not
    drag its reliability down."""
    inputs = ReliabilityInputs(error_rate=0.0, risk_reject_rate=0.0, fill_rate=None)

    assert inputs.score() == pytest.approx(1.0)


def test_thesis_quality_is_the_confirmed_share(session: Session) -> None:
    portfolio = make_portfolio(session, make_persona(session, name="VULTURE"))
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    from src.db.models import ReviewVerdict

    for verdict in (
        ReviewVerdict.THESIS_CONFIRMED,
        ReviewVerdict.THESIS_CONFIRMED,
        ReviewVerdict.THESIS_FAILED,
        ReviewVerdict.INCONCLUSIVE,
    ):
        make_review(
            session,
            make_decision(session, cycle, portfolio, item),
            verdict=verdict,
            reviewed_at=_SINCE_TS + datetime.timedelta(days=1),
        )
    session.flush()

    share, total = thesis_quality(session, portfolio.id, _SINCE_TS)

    assert total == 4
    assert share == pytest.approx(0.5)


def test_thesis_quality_is_none_without_reviews(session: Session) -> None:
    portfolio = make_portfolio(session, make_persona(session, name="HYPE"))
    session.flush()

    assert thesis_quality(session, portfolio.id, _SINCE_TS) == (None, 0)


def test_reliability_inputs_read_error_reject_and_fill_rates(session: Session) -> None:
    persona = make_persona(session, name="CHARTIST")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    make_agent_run(session, cycle, portfolio_id=portfolio.id, status=AgentRunStatus.SUCCEEDED)
    make_agent_run(session, cycle, portfolio_id=portfolio.id, status=AgentRunStatus.SUCCEEDED)
    make_agent_run(session, cycle, portfolio_id=portfolio.id, status=AgentRunStatus.SUCCEEDED)
    make_agent_run(session, cycle, portfolio_id=portfolio.id, status=AgentRunStatus.FAILED)

    approved = make_decision(
        session,
        cycle,
        portfolio,
        item,
        action=DecisionAction.BUY,
        status=DecisionStatus.EXECUTED,
        risk_check={"approved": True},
    )
    make_decision(
        session,
        cycle,
        portfolio,
        item,
        action=DecisionAction.BUY,
        status=DecisionStatus.RISK_REJECTED,
        risk_check={"approved": False},
    )
    # hold decisions never reach the gate and must not dilute the reject rate.
    # Note they carry risk_check=None, which JSONB stores as JSON `null` — an
    # `IS NOT NULL` filter would count them (F089 §3).
    make_decision(
        session, cycle, portfolio, item, action=DecisionAction.HOLD, status=DecisionStatus.RECORDED
    )

    make_order_record(
        session,
        approved,
        status=OrderRecordStatus.FILLED,
        submitted_at=_SINCE_TS + datetime.timedelta(days=1),
        fill_price=Decimal("10.00"),
    )
    make_order_record(
        session,
        approved,
        status=OrderRecordStatus.REJECTED,
        submitted_at=_SINCE_TS + datetime.timedelta(days=1),
    )
    session.flush()

    inputs = reliability_inputs(session, portfolio.id, _SINCE_TS)

    assert inputs.error_rate == pytest.approx(0.25)
    assert inputs.risk_reject_rate == pytest.approx(0.5)
    assert inputs.fill_rate == pytest.approx(0.5)


def test_reliability_inputs_ignore_still_open_orders(session: Session) -> None:
    """A NEW order placed after the close has no outcome yet — counting it as a
    non-fill would punish a persona for trading late (live case 02.08.2026)."""
    portfolio = make_portfolio(session, make_persona(session, name="CONTRA"))
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, item, action=DecisionAction.BUY)
    make_order_record(
        session,
        decision,
        status=OrderRecordStatus.NEW,
        submitted_at=_SINCE_TS + datetime.timedelta(days=1),
    )
    session.flush()

    assert reliability_inputs(session, portfolio.id, _SINCE_TS).fill_rate is None


def test_score_personas_shares_the_rank_on_identical_scores() -> None:
    """Three personas on identical numbers is the normal state in week one —
    printing them as 1st, 2nd and 3rd would imply an order the data lacks."""
    field = [
        _criteria("CRYPTOR", sortino=None, thesis=None),
        _criteria("GUARDIAN", sortino=None, thesis=None),
        _criteria("HYPE", sortino=None, thesis=None),
        _criteria("CONTRA", sortino=None, thesis=None, adjusted_return=-0.05),
    ]

    score = score_personas(field, _SINCE)

    assert [(p.rank, p.persona) for p in score.personas] == [
        (1, "CRYPTOR"),
        (1, "GUARDIAN"),
        (1, "HYPE"),
        (4, "CONTRA"),
    ]
