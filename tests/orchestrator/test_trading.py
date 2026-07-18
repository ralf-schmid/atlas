"""See docs/features/F023-trading-agent.md §3, tests 1-3."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import ClosePositionResult, OrderResult, OrderSide
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
    def __init__(
        self,
        *,
        should_fail: bool = False,
        filled_at: datetime.datetime | None = None,
        fill_price: float | None = None,
    ) -> None:
        self.should_fail = should_fail
        self.filled_at = filled_at
        self.fill_price = fill_price
        self.calls: list[dict[str, object]] = []
        self.close_calls: list[dict[str, object]] = []

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
            filled_at=self.filled_at,
            fill_price=self.fill_price,
        )

    def close_position(self, **kwargs: object) -> ClosePositionResult:
        self.close_calls.append(kwargs)
        if self.should_fail:
            raise RuntimeError("broker rejected the order")
        return ClosePositionResult(
            order_id="close-789",
            symbol=str(kwargs["symbol"]),
            qty=float(kwargs["qty"]),  # type: ignore[arg-type]
            side=OrderSide.SELL,
            filled_at=self.filled_at,
            fill_price=self.fill_price,
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


def test_execute_decision_marks_filled_when_adapter_reports_synchronous_fill(
    session: Session,
) -> None:
    """F075: InternalLedgerAdapter knows the fill synchronously at placement
    time (unlike AlpacaPaperAdapter/`_FakeAdapter` above, which leave
    filled_at/fill_price unset) — execute_decision must record it immediately
    instead of leaving the row NEW forever."""
    portfolio = _make_portfolio(session)
    decision = _make_approved_decision(session, portfolio)
    filled_at = datetime.datetime(2026, 7, 14, 10, 0)
    adapter = _FakeAdapter(filled_at=filled_at, fill_price=151.25)

    order_record = execute_decision(session, decision, adapter, "internal_ledger")

    assert order_record.status == OrderRecordStatus.FILLED
    assert order_record.filled_at == filled_at
    assert order_record.fill_price == Decimal("151.25")


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


# F077: close-decision tests.


def _make_filled_buy_order_record(
    session: Session, portfolio: Portfolio, *, instrument: str, stop_order_id: str
) -> OrderRecord:
    """A previously executed BUY tranche on `instrument`, with the GTC stop-loss
    order id a real `execute_decision` buy call would have stored in `raw`."""
    buy_decision = _make_approved_decision(session, portfolio)
    buy_decision.instrument = instrument
    buy_decision.status = DecisionStatus.EXECUTED
    session.flush()
    order_record = OrderRecord(
        decision_id=buy_decision.id,
        broker="alpaca_paper",
        broker_order_id="entry-old",
        mode=PortfolioMode.PAPER,
        submitted_at=datetime.datetime(2026, 7, 10, 9, 0),
        status=OrderRecordStatus.FILLED,
        raw={"stop_order_id": stop_order_id, "qty": 2.0, "side": "buy", "stop_loss_price": 140.0},
    )
    session.add(order_record)
    session.flush()
    return order_record


def _make_approved_close_decision(session: Session, portfolio: Portfolio) -> Decision:
    cycle = create_cycle(session, datetime.date(2026, 7, 7), 2, MarketSession.US_EQUITY)
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
        action=DecisionAction.CLOSE,
        quantity=Decimal("2"),
        thesis_text="test",
        expected_outcome={"entry_price": 150.0, "exit_price_estimate": 160.0},
        input_research_ids=[item.id],
        status=DecisionStatus.APPROVED,
    )
    session.add(decision)
    session.flush()
    return decision


def test_execute_decision_close_collects_stop_order_id_from_prior_buy(session: Session) -> None:
    portfolio = _make_portfolio(session)
    _make_filled_buy_order_record(session, portfolio, instrument="AAPL", stop_order_id="stop-456")
    decision = _make_approved_close_decision(session, portfolio)
    adapter = _FakeAdapter()

    order_record = execute_decision(session, decision, adapter, "alpaca_paper")

    assert adapter.close_calls == [
        {
            "decision_id": decision.id,
            "symbol": "AAPL",
            "qty": 2.0,
            "stop_order_ids": ["stop-456"],
        }
    ]
    assert order_record.broker_order_id == "close-789"
    assert order_record.raw == {"qty": 2.0, "side": "sell", "closed": True}
    assert decision.status == DecisionStatus.EXECUTED


def test_execute_decision_close_collects_stop_order_ids_from_two_buy_tranches(
    session: Session,
) -> None:
    portfolio = _make_portfolio(session)
    _make_filled_buy_order_record(session, portfolio, instrument="AAPL", stop_order_id="stop-1")
    _make_filled_buy_order_record(session, portfolio, instrument="AAPL", stop_order_id="stop-2")
    decision = _make_approved_close_decision(session, portfolio)
    adapter = _FakeAdapter()

    execute_decision(session, decision, adapter, "alpaca_paper")

    (call,) = adapter.close_calls
    assert sorted(call["stop_order_ids"]) == ["stop-1", "stop-2"]  # type: ignore[arg-type]


def test_execute_decision_close_ignores_buy_records_from_other_instruments(
    session: Session,
) -> None:
    portfolio = _make_portfolio(session)
    _make_filled_buy_order_record(session, portfolio, instrument="MSFT", stop_order_id="stop-msft")
    decision = _make_approved_close_decision(session, portfolio)
    adapter = _FakeAdapter()

    execute_decision(session, decision, adapter, "alpaca_paper")

    (call,) = adapter.close_calls
    assert call["stop_order_ids"] == []


def test_execute_decision_close_rejects_missing_quantity(session: Session) -> None:
    portfolio = _make_portfolio(session)
    decision = _make_approved_close_decision(session, portfolio)
    decision.quantity = None
    adapter = _FakeAdapter()

    try:
        execute_decision(session, decision, adapter, "alpaca_paper")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "quantity" in str(exc)

    assert adapter.close_calls == []
    assert session.scalars(select(OrderRecord)).all() == []
