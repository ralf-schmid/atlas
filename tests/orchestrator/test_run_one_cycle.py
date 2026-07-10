"""`run_one_cycle` and `notify_pending_hitl_decisions` (src/orchestrator/scheduler.py)
had zero test coverage before F062 — every existing test mocks `run_one_cycle`
out entirely, and nothing exercised `notify_pending_hitl_decisions` at all. That
second function is the one that stores `thread_id`/`interrupt_id` on the decision
*and* sends the Telegram approval message (`send_hitl_approval_request`) — a bug
here means a HITL-pending decision never gets a message a human could even click,
exactly the class of failure Ralf flagged as unacceptable.

Marked integration: needs a real, independently-committing session_factory, same
reason tests/orchestrator/test_hitl_sweep.py can't use the rolled-back `session`
fixture.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from langgraph.types import Interrupt
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
from src.orchestrator.scheduler import notify_pending_hitl_decisions, run_one_cycle
from src.orchestrator.seed import seed_personas_and_portfolios
from src.telegram.config import TelegramConfig

pytestmark = pytest.mark.integration


class _FakeGraph:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.invoke_calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def invoke(self, state: dict[str, object], config: dict[str, object]) -> dict[str, object]:
        self.invoke_calls.append((state, config))
        return self.result


def _seed_hitl_pending_decision(session_factory) -> uuid.UUID:
    with session_factory() as session:
        seed_personas_and_portfolios(session)
        persona = session.scalar(select(Persona).filter_by(name="VULTURE"))
        assert persona is not None
        portfolio = session.scalar(select(Portfolio).filter_by(persona_id=persona.id))
        assert portfolio is not None
        cycle = create_cycle(session, datetime.date(2026, 7, 10), 1, MarketSession.US_EQUITY)

        decision = Decision(
            cycle_id=cycle.id,
            portfolio_id=portfolio.id,
            instrument="AAPL",
            action=DecisionAction.BUY,
            quantity=Decimal("1"),
            thesis_text="test",
            expected_outcome={"stop_loss_price": 140.0},
            input_research_ids=[uuid.uuid4()],
            status=DecisionStatus.HITL_PENDING,
            hitl={"amount_usd": 275.0},
        )
        session.add(decision)
        session.commit()
        return decision.id


def test_notify_pending_hitl_decisions_stores_ids_and_sends_message(monkeypatch) -> None:
    session_factory = get_session_factory()
    decision_id = _seed_hitl_pending_decision(session_factory)
    interrupt = Interrupt(
        value={
            "decision_id": str(decision_id),
            "persona_name": "VULTURE",
            "instrument": "AAPL",
            "thesis_text": "momentum",
            "amount_usd": 275.0,
            "stop_loss_price": 140.0,
        },
        id="interrupt-abc",
    )
    monkeypatch.setattr(
        "src.orchestrator.scheduler.load_telegram_config",
        lambda: TelegramConfig(bot_token="test-token", allowed_chat_id=1),
    )
    sent_requests = []

    async def _fake_send(_config, request):
        sent_requests.append(request)

    monkeypatch.setattr("src.telegram.alerts.send_hitl_approval_request", _fake_send)

    notify_pending_hitl_decisions(session_factory, "2026-07-10-1-us_equity", [interrupt])

    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.hitl is not None
        assert decision.hitl["thread_id"] == "2026-07-10-1-us_equity"
        assert decision.hitl["interrupt_id"] == "interrupt-abc"

    (request,) = sent_requests
    assert request.decision_id == decision_id
    assert request.persona_name == "VULTURE"
    assert request.instrument == "AAPL"
    assert request.amount_usd == 275.0
    assert request.stop_loss_price == 140.0


def test_notify_pending_hitl_decisions_sends_one_message_per_interrupt(monkeypatch) -> None:
    session_factory = get_session_factory()
    decision_id_1 = _seed_hitl_pending_decision(session_factory)
    decision_id_2 = _seed_hitl_pending_decision(session_factory)
    interrupts = [
        Interrupt(
            value={
                "decision_id": str(decision_id_1),
                "persona_name": "VULTURE",
                "instrument": "AAPL",
                "thesis_text": "x",
                "amount_usd": 275.0,
                "stop_loss_price": 140.0,
            },
            id="interrupt-1",
        ),
        Interrupt(
            value={
                "decision_id": str(decision_id_2),
                "persona_name": "VULTURE",
                "instrument": "ALDX",
                "thesis_text": "y",
                "amount_usd": 60.0,
                "stop_loss_price": 1.7,
            },
            id="interrupt-2",
        ),
    ]
    monkeypatch.setattr(
        "src.orchestrator.scheduler.load_telegram_config",
        lambda: TelegramConfig(bot_token="test-token", allowed_chat_id=1),
    )
    sent_requests = []

    async def _fake_send(_config, request):
        sent_requests.append(request)

    monkeypatch.setattr("src.telegram.alerts.send_hitl_approval_request", _fake_send)

    notify_pending_hitl_decisions(session_factory, "thread-1", interrupts)

    assert len(sent_requests) == 2
    assert {r.decision_id for r in sent_requests} == {decision_id_1, decision_id_2}


def test_run_one_cycle_notifies_when_graph_interrupts(monkeypatch) -> None:
    session_factory = get_session_factory()
    fake_graph = _FakeGraph({"__interrupt__": [Interrupt(value={"decision_id": "x"}, id="i1")]})
    notified: list[tuple[str, list[Interrupt]]] = []
    monkeypatch.setattr(
        "src.orchestrator.scheduler.notify_pending_hitl_decisions",
        lambda _sf, thread_id, interrupts: notified.append((thread_id, interrupts)),
    )

    result = run_one_cycle(
        fake_graph,  # type: ignore[arg-type]
        session_factory,
        datetime.date(2026, 7, 10),
        1,
        MarketSession.US_EQUITY,
    )

    assert result == fake_graph.result
    assert len(fake_graph.invoke_calls) == 1
    state, config = fake_graph.invoke_calls[0]
    assert state["trading_day"] == "2026-07-10"
    assert state["seq"] == 1
    assert state["market_session"] == "us_equity"
    assert config == {"configurable": {"thread_id": "2026-07-10-1-us_equity"}}
    assert len(notified) == 1
    thread_id, interrupts = notified[0]
    assert thread_id == "2026-07-10-1-us_equity"
    assert len(interrupts) == 1


def test_run_one_cycle_skips_notification_without_interrupt(monkeypatch) -> None:
    session_factory = get_session_factory()
    fake_graph = _FakeGraph({"cycle_id": "abc"})
    notified: list[object] = []
    monkeypatch.setattr(
        "src.orchestrator.scheduler.notify_pending_hitl_decisions",
        lambda *a, **k: notified.append(a),
    )

    result = run_one_cycle(
        fake_graph,  # type: ignore[arg-type]
        session_factory,
        datetime.date(2026, 7, 10),
        2,
        MarketSession.CRYPTO,
    )

    assert result == fake_graph.result
    assert notified == []
