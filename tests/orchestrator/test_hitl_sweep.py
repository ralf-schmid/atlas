"""See docs/features/F030-hitl-timeout-sweep.md §3. Marked integration: needs a
real, independently-committing session_factory (`sweep_expired_hitl_decisions`
opens+commits its own session per F016 §2 thread-safety convention) — same reason
tests/orchestrator/test_graph.py can't use the rolled-back `session` fixture.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from langgraph.types import Command
from sqlalchemy import select

from src.db.base import get_session_factory
from src.db.models import (
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketSession,
    Persona,
    Portfolio,
)
from src.orchestrator.graph import create_cycle
from src.orchestrator.scheduler import sweep_expired_hitl_decisions
from src.orchestrator.seed import seed_personas_and_portfolios

pytestmark = pytest.mark.integration


class _FakeGraph:
    def __init__(self) -> None:
        self.invoke_calls: list[tuple[Command, dict[str, object]]] = []

    def invoke(self, command: Command, config: dict[str, object]) -> dict[str, object]:
        self.invoke_calls.append((command, config))
        return {}


def _seed_hitl_pending_decision(
    session_factory,
    *,
    requested_at: datetime.datetime,
    thread_id: str | None = "tid-1",
    interrupt_id: str | None = "int-1",
) -> uuid.UUID:
    with session_factory() as session:
        seed_personas_and_portfolios(session)
        persona = session.scalar(select(Persona).filter_by(name="VULTURE"))
        assert persona is not None
        portfolio = session.scalar(select(Portfolio).filter_by(persona_id=persona.id))
        assert portfolio is not None
        cycle = create_cycle(session, datetime.date(2026, 7, 7), 1, MarketSession.US_EQUITY)

        hitl: dict[str, object] = {"requested_at": requested_at.isoformat(), "amount_usd": 500.0}
        if thread_id is not None:
            hitl["thread_id"] = thread_id
        if interrupt_id is not None:
            hitl["interrupt_id"] = interrupt_id

        decision = Decision(
            cycle_id=cycle.id,
            portfolio_id=portfolio.id,
            instrument="AAPL",
            action=DecisionAction.BUY,
            quantity=Decimal("10"),
            thesis_text="test thesis",
            expected_outcome={"stop_loss_price": 140.0},
            input_research_ids=[uuid.uuid4()],
            status=DecisionStatus.HITL_PENDING,
            hitl=hitl,
        )
        session.add(decision)
        session.commit()
        return decision.id


def test_sweep_rejects_expired_decision_and_resumes_graph() -> None:
    session_factory = get_session_factory()
    now = datetime.datetime.now(datetime.UTC)
    decision_id = _seed_hitl_pending_decision(
        session_factory, requested_at=now - datetime.timedelta(minutes=31)
    )
    fake_graph = _FakeGraph()

    count = sweep_expired_hitl_decisions(fake_graph, session_factory, now=now)  # type: ignore[arg-type]

    assert count == 1
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.status == DecisionStatus.HITL_REJECTED
        assert decision.hitl is not None
        assert decision.hitl["decided_by"] == "timeout"

    (call,) = fake_graph.invoke_calls
    command, config = call
    assert command.resume == {"int-1": "rejected"}
    assert config == {"configurable": {"thread_id": "tid-1"}}


def test_sweep_leaves_non_expired_decision_pending() -> None:
    session_factory = get_session_factory()
    now = datetime.datetime.now(datetime.UTC)
    decision_id = _seed_hitl_pending_decision(
        session_factory, requested_at=now - datetime.timedelta(minutes=5)
    )
    fake_graph = _FakeGraph()

    count = sweep_expired_hitl_decisions(fake_graph, session_factory, now=now)  # type: ignore[arg-type]

    assert count == 0
    assert fake_graph.invoke_calls == []
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.status == DecisionStatus.HITL_PENDING


def test_sweep_skips_graph_resume_when_thread_or_interrupt_id_missing() -> None:
    session_factory = get_session_factory()
    now = datetime.datetime.now(datetime.UTC)
    decision_id = _seed_hitl_pending_decision(
        session_factory,
        requested_at=now - datetime.timedelta(minutes=31),
        thread_id=None,
        interrupt_id=None,
    )
    fake_graph = _FakeGraph()

    count = sweep_expired_hitl_decisions(fake_graph, session_factory, now=now)  # type: ignore[arg-type]

    assert count == 1  # still rejected in the DB
    assert fake_graph.invoke_calls == []  # but nothing to resume
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.status == DecisionStatus.HITL_REJECTED
