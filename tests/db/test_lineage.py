import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError

from src.db.models import (
    Cycle,
    Decision,
    DecisionAction,
    OrderRecord,
    Persona,
    Portfolio,
    PortfolioMode,
)
from src.db.validation import validate_research_ids_exist
from tests.db.factories import (
    make_cycle,
    make_decision,
    make_order_record,
    make_persona,
    make_portfolio,
    make_research_item,
)


def test_order_record_requires_decision_id(session):
    order = OrderRecord(
        decision_id=None,
        broker="alpaca_paper",
        mode=PortfolioMode.PAPER,
        submitted_at=datetime.datetime(2026, 7, 4, 9, 0),
    )
    session.add(order)
    with pytest.raises(IntegrityError, match="not-null|null value"):
        session.flush()


def test_order_record_decision_id_must_reference_existing_decision(session):
    order = OrderRecord(
        decision_id=uuid.uuid4(),
        broker="alpaca_paper",
        mode=PortfolioMode.PAPER,
        submitted_at=datetime.datetime(2026, 7, 4, 9, 0),
    )
    session.add(order)
    with pytest.raises(IntegrityError, match="foreign key"):
        session.flush()


def test_decision_rejects_empty_input_research_ids(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)

    decision = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument="AAPL",
        action=DecisionAction.HOLD,
        thesis_text="No input research",
        expected_outcome={},
        input_research_ids=[],
    )
    session.add(decision)
    with pytest.raises(IntegrityError, match="ck_decision_input_research_ids_not_empty"):
        session.flush()


def test_decision_rejects_null_input_research_ids(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)

    decision = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument="AAPL",
        action=DecisionAction.HOLD,
        thesis_text="Null input research",
        expected_outcome={},
        input_research_ids=None,
    )
    session.add(decision)
    with pytest.raises(IntegrityError, match="not-null|null value"):
        session.flush()


def test_validate_research_ids_exist_rejects_unknown_id(session):
    cycle = make_cycle(session)
    known = make_research_item(session, cycle)

    with pytest.raises(ValueError, match="Unknown research_item"):
        validate_research_ids_exist(session, [known.id, uuid.uuid4()])


def test_validate_research_ids_exist_accepts_known_ids(session):
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)

    validate_research_ids_exist(session, [item.id])  # must not raise


def test_validate_research_ids_exist_rejects_empty_list(session):
    with pytest.raises(ValueError, match="must not be empty"):
        validate_research_ids_exist(session, [])


def test_full_lineage_chain_is_traceable(session):
    persona = make_persona(session, name="VULTURE_TEST")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research_item)
    order = make_order_record(session, decision)

    # Lineage query: source -> research_item -> decision -> order_record.
    row = session.execute(
        select(Persona.name, Decision.instrument, OrderRecord.broker_order_id)
        .join(Portfolio, Portfolio.persona_id == Persona.id)
        .join(Decision, Decision.portfolio_id == Portfolio.id)
        .join(OrderRecord, OrderRecord.decision_id == Decision.id)
        .where(OrderRecord.id == order.id)
    ).one()

    assert row.name == "VULTURE_TEST"
    assert row.instrument == "AAPL"
    assert row.broker_order_id == "entry-123"
    assert research_item.id in decision.input_research_ids


def test_reject_idea_decision_persists_without_order_record(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)

    decision = make_decision(
        session,
        cycle,
        portfolio,
        research_item,
        action=DecisionAction.REJECT_IDEA,
        quantity=None,
        rejection_reason="Thesis already priced in",
    )

    reloaded = session.get(Decision, decision.id)
    assert reloaded.action == DecisionAction.REJECT_IDEA
    assert reloaded.rejection_reason == "Thesis already priced in"

    order_count = session.execute(
        select(OrderRecord).where(OrderRecord.decision_id == decision.id)
    ).first()
    assert order_count is None


def test_portfolio_mode_rejects_invalid_value(session):
    persona = make_persona(session)
    portfolio = Portfolio(
        persona_id=persona.id,
        mode="not_a_mode",
        broker_account_ref="x",
        base_ccy="USD",
        start_value=Decimal("1"),
    )
    session.add(portfolio)
    with pytest.raises(DataError):
        session.flush()


def test_cycle_market_session_rejects_invalid_value(session):
    cycle = Cycle(
        trading_day=datetime.date(2026, 7, 4),
        seq=1,
        started_at=datetime.datetime(2026, 7, 4, 9, 0),
        market_session="not_a_session",
    )
    session.add(cycle)
    with pytest.raises(DataError):
        session.flush()


def test_decision_action_rejects_invalid_value(session):
    persona = make_persona(session)
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)

    decision = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument="AAPL",
        action="not_an_action",
        thesis_text="x",
        expected_outcome={},
        input_research_ids=[research_item.id],
    )
    session.add(decision)
    with pytest.raises(DataError):
        session.flush()
