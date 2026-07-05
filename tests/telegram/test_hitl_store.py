import datetime
import uuid

import pytest

from src.db.models import DecisionStatus
from src.telegram.hitl import process_callback
from src.telegram.hitl_store import (
    apply_hitl_outcome,
    decision_to_hitl_request,
    load_pending_decision,
    mark_hitl_pending,
)
from tests.db.factories import (
    make_cycle,
    make_decision,
    make_persona,
    make_portfolio,
    make_research_item,
)

pytestmark = pytest.mark.usefixtures("_migrated_schema")

_REQUESTED_AT = datetime.datetime(2026, 7, 5, 12, 0, tzinfo=datetime.UTC)


def test_mark_hitl_pending_and_load(session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research)

    mark_hitl_pending(session, decision, amount_usd=1500.0, requested_at=_REQUESTED_AT)
    session.flush()

    loaded = load_pending_decision(session, decision.id)
    assert loaded is not None
    loaded_decision, loaded_cycle = loaded
    assert loaded_decision.id == decision.id
    assert loaded_decision.status == DecisionStatus.HITL_PENDING
    assert loaded_cycle.id == cycle.id


def test_load_pending_decision_returns_none_for_wrong_status(session):
    persona = make_persona(session, name="HYPE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research)

    assert load_pending_decision(session, decision.id) is None


def test_decision_to_hitl_request_uses_hitl_metadata(session):
    persona = make_persona(session, name="GUARDIAN")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research)
    mark_hitl_pending(session, decision, amount_usd=1500.0, requested_at=_REQUESTED_AT)

    request = decision_to_hitl_request(decision, cycle)

    assert request.decision_id == decision.id
    assert request.instrument == "AAPL"
    assert request.amount_usd == 1500.0
    assert request.stop_loss_price == 140.0
    assert request.created_at == _REQUESTED_AT


def test_apply_hitl_outcome_persists_approve(session):
    persona = make_persona(session, name="CHARTIST")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research)
    mark_hitl_pending(session, decision, amount_usd=900.0, requested_at=_REQUESTED_AT)
    request = decision_to_hitl_request(decision, cycle)
    now = _REQUESTED_AT + datetime.timedelta(minutes=5)
    outcome = process_callback(request, f"hitl:approve:{decision.id}", now)

    apply_hitl_outcome(session, decision, outcome, now)
    session.flush()

    assert decision.status == DecisionStatus.APPROVED
    assert decision.hitl is not None
    assert decision.hitl["decided_by"] == "user"
    assert load_pending_decision(session, decision.id) is None


def test_apply_hitl_outcome_persists_timeout_reject(session):
    persona = make_persona(session, name="CONTRA")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research)
    mark_hitl_pending(session, decision, amount_usd=900.0, requested_at=_REQUESTED_AT)
    request = decision_to_hitl_request(decision, cycle)
    now = _REQUESTED_AT + datetime.timedelta(minutes=31)
    outcome = process_callback(request, f"hitl:approve:{decision.id}", now)

    apply_hitl_outcome(session, decision, outcome, now)
    session.flush()

    assert decision.status == DecisionStatus.HITL_REJECTED
    assert decision.hitl is not None
    assert decision.hitl["decided_by"] == "timeout"


def test_load_pending_decision_returns_none_for_unknown_id(session):
    assert load_pending_decision(session, uuid.uuid4()) is None
