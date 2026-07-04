import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import DataError, IntegrityError

from src.db.models import (
    AgentRun,
    AgentRunStatus,
    CostLedger,
    CostLedgerScope,
    PortfolioSnapshot,
    Review,
    ReviewVerdict,
)
from tests.db.factories import (
    make_agent_run,
    make_cost_ledger_entry,
    make_cycle,
    make_decision,
    make_persona,
    make_portfolio,
    make_portfolio_snapshot,
    make_position_snapshot,
    make_research_item,
    make_review,
)


def test_agent_run_allows_null_portfolio_for_shared_agents(session):
    cycle = make_cycle(session)

    run = make_agent_run(session, cycle, agent="market_research", portfolio_id=None)

    reloaded = session.get(AgentRun, run.id)
    assert reloaded.portfolio_id is None


def test_agent_run_requires_cycle_id(session):
    run = AgentRun(
        cycle_id=uuid.uuid4(), agent="market_research", status=AgentRunStatus.SUCCEEDED
    )
    session.add(run)
    with pytest.raises(IntegrityError, match="foreign key"):
        session.flush()


def test_agent_run_rejects_invalid_status(session):
    cycle = make_cycle(session)
    run = AgentRun(cycle_id=cycle.id, agent="market_research", status="not_a_status")
    session.add(run)
    with pytest.raises(DataError):
        session.flush()


def test_position_snapshot_requires_portfolio(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    snapshot = make_position_snapshot(session, portfolio)

    assert snapshot.market_value == Decimal("1550.00")


def test_portfolio_snapshot_allows_null_benchmark_value(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)

    snapshot = make_portfolio_snapshot(session, portfolio)

    reloaded = session.get(PortfolioSnapshot, snapshot.id)
    assert reloaded.benchmark_value is None


def test_review_requires_decision_id(session):
    review = Review(
        decision_id=uuid.uuid4(),
        reviewed_at=datetime.datetime(2026, 7, 11, 9, 0),
        expected={},
        actual={},
        verdict=ReviewVerdict.THESIS_CONFIRMED,
    )
    session.add(review)
    with pytest.raises(IntegrityError, match="foreign key"):
        session.flush()


def test_review_rejects_invalid_verdict(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research_item)

    review = Review(
        decision_id=decision.id,
        reviewed_at=datetime.datetime(2026, 7, 11, 9, 0),
        expected={},
        actual={},
        verdict="not_a_verdict",
    )
    session.add(review)
    with pytest.raises(DataError):
        session.flush()


def test_review_persists_with_valid_verdict(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research_item)

    review = make_review(session, decision)

    assert review.verdict.value == "thesis_confirmed"


def test_cost_ledger_allows_null_persona_for_system_scope(session):
    entry = make_cost_ledger_entry(session, scope=CostLedgerScope.SYSTEM, persona_id=None)

    reloaded = session.get(CostLedger, entry.id)
    assert reloaded.persona_id is None
    assert reloaded.scope == CostLedgerScope.SYSTEM


def test_cost_ledger_rejects_invalid_scope(session):
    entry = CostLedger(
        ts=datetime.datetime(2026, 7, 4, 9, 0),
        scope="not_a_scope",
        provider="anthropic",
        model="claude-sonnet-5",
        tokens_in=100,
        tokens_out=20,
        cost_usd=Decimal("0.01"),
    )
    session.add(entry)
    with pytest.raises(DataError):
        session.flush()
