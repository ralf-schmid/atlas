"""See docs/features/F023-trading-agent.md §3, tests 1-3."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import OrderResult, OrderSide
from src.db.models import (
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketSession,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
    PortfolioMode,
    ResearchItem,
)
from src.orchestrator.graph import create_cycle
from src.orchestrator.trading import execute_decision


class _FakeAdapter:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[dict[str, object]] = []

    def place_order(self, **kwargs: object) -> OrderResult:
        self.calls.append(kwargs)
        if self.should_fail:
            raise RuntimeError("broker rejected the order")
        return OrderResult(
            entry_order_id="entry-123",
            stop_order_id="stop-456",
            symbol=str(kwargs["symbol"]),
            qty=float(kwargs["qty"]),  # type: ignore[arg-type]
            side=OrderSide.BUY,
            stop_loss_price=float(kwargs["stop_loss_price"]),  # type: ignore[arg-type]
        )

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    def get_positions(self) -> list[object]:
        raise NotImplementedError

    def get_account_balance(self) -> object:
        raise NotImplementedError


def _make_portfolio(session: Session) -> Portfolio:
    persona = Persona(
        name=f"TEST_{uuid.uuid4().hex[:8]}",
        charter_version=1,
        model="claude-sonnet-5",
        config_ref="config/personas/test.yaml",
    )
    session.add(persona)
    session.flush()
    portfolio = Portfolio(
        persona_id=persona.id,
        mode=PortfolioMode.PAPER,
        broker_account_ref="test-account",
        base_ccy="USD",
        start_value=Decimal("5000.00"),
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _make_approved_decision(
    session: Session, portfolio: Portfolio, **overrides: object
) -> Decision:
    cycle = create_cycle(session, datetime.date(2026, 7, 7), 1, MarketSession.US_EQUITY)
    item = ResearchItem(
        cycle_id=cycle.id,
        agent="market_research",
        source_type="screener_result",
        source_ref="AAPL",
        summary="test",
        instruments=["AAPL"],
        raw={},
    )
    session.add(item)
    session.flush()
    decision = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument="AAPL",
        action=DecisionAction.BUY,
        quantity=Decimal("2"),
        thesis_text="test",
        expected_outcome={"entry_price": 150.0, "stop_loss_price": 140.0, "conviction": 0.5},
        input_research_ids=[item.id],
        status=overrides.get("status", DecisionStatus.APPROVED),
    )
    session.add(decision)
    session.flush()
    return decision


def test_execute_decision_persists_order_record_and_marks_executed(session: Session) -> None:
    portfolio = _make_portfolio(session)
    decision = _make_approved_decision(session, portfolio)
    adapter = _FakeAdapter()

    order_record = execute_decision(session, decision, adapter, "alpaca_paper")

    assert order_record.decision_id == decision.id
    assert order_record.broker == "alpaca_paper"
    assert order_record.broker_order_id == "entry-123"
    assert order_record.mode == PortfolioMode.PAPER
    assert order_record.status == OrderRecordStatus.NEW
    assert order_record.raw is not None
    assert order_record.raw["stop_order_id"] == "stop-456"
    assert decision.status == DecisionStatus.EXECUTED


def test_execute_decision_rejects_non_approved_decision(session: Session) -> None:
    portfolio = _make_portfolio(session)
    decision = _make_approved_decision(session, portfolio, status=DecisionStatus.RISK_REJECTED)
    adapter = _FakeAdapter()

    try:
        execute_decision(session, decision, adapter, "alpaca_paper")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    assert adapter.calls == []
    assert session.scalars(select(OrderRecord)).all() == []


def test_execute_decision_broker_failure_leaves_decision_approved(session: Session) -> None:
    portfolio = _make_portfolio(session)
    decision = _make_approved_decision(session, portfolio)
    adapter = _FakeAdapter(should_fail=True)

    try:
        execute_decision(session, decision, adapter, "alpaca_paper")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass

    assert decision.status == DecisionStatus.APPROVED
    assert session.scalars(select(OrderRecord)).all() == []


def test_execute_decision_rejects_missing_stop_loss_price(session: Session) -> None:
    # Invariant #4 (mandatory stop-loss): an APPROVED decision that somehow lost
    # its stop_loss_price must never reach the broker without one.
    portfolio = _make_portfolio(session)
    decision = _make_approved_decision(session, portfolio)
    decision.expected_outcome = {"entry_price": 150.0, "conviction": 0.5}
    adapter = _FakeAdapter()

    try:
        execute_decision(session, decision, adapter, "alpaca_paper")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "stop_loss_price" in str(exc)

    assert adapter.calls == []
    assert session.scalars(select(OrderRecord)).all() == []


def test_execute_decision_rejects_missing_quantity(session: Session) -> None:
    portfolio = _make_portfolio(session)
    decision = _make_approved_decision(session, portfolio)
    decision.quantity = None
    adapter = _FakeAdapter()

    try:
        execute_decision(session, decision, adapter, "alpaca_paper")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "quantity" in str(exc)

    assert adapter.calls == []
    assert session.scalars(select(OrderRecord)).all() == []
