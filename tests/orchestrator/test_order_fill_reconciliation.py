"""See docs/features/F075-order-fill-reconciliation.md §3. Marked integration:
needs a real, independently-committing session_factory (`reconcile_order_fills`
opens+commits its own session per F016 §2 thread-safety convention), same reason
tests/orchestrator/test_stuck_decision_sweep.py can't use the rolled-back
`session` fixture.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus
from alpaca.trading.models import Order as AlpacaOrder
from sqlalchemy import select

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.db.base import get_session_factory
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
)
from src.orchestrator.graph import create_cycle
from src.orchestrator.scheduler import reconcile_order_fills
from src.orchestrator.seed import seed_personas_and_portfolios

pytestmark = pytest.mark.integration


def _seed_new_order(session_factory, *, persona_name: str) -> uuid.UUID:
    with session_factory() as session:
        seed_personas_and_portfolios(session)
        persona = session.scalar(select(Persona).filter_by(name=persona_name))
        assert persona is not None
        portfolio = session.scalar(select(Portfolio).filter_by(persona_id=persona.id))
        assert portfolio is not None
        cycle = create_cycle(session, datetime.date(2026, 7, 14), 1, MarketSession.US_EQUITY)

        decision = Decision(
            cycle_id=cycle.id,
            portfolio_id=portfolio.id,
            instrument="AAPL",
            action=DecisionAction.BUY,
            quantity=Decimal("2"),
            thesis_text="test",
            expected_outcome={"stop_loss_price": 140.0},
            input_research_ids=[uuid.uuid4()],
            status=DecisionStatus.EXECUTED,
        )
        session.add(decision)
        session.flush()

        order = OrderRecord(
            decision_id=decision.id,
            broker="alpaca_paper" if persona_name == "VULTURE" else "internal_ledger",
            broker_order_id="entry-123",
            mode=PortfolioMode.PAPER,
            submitted_at=datetime.datetime(2026, 7, 14, 9, 0),
            status=OrderRecordStatus.NEW,
            fees=Decimal("0"),
        )
        session.add(order)
        session.commit()
        return order.id


def _alpaca_adapter_returning(alpaca_order: AlpacaOrder) -> AlpacaPaperAdapter:
    with patch("src.broker.alpaca_paper.TradingClient") as mock_cls:
        adapter = AlpacaPaperAdapter(api_key="key", secret_key="secret")
        mock_cls.return_value.get_order_by_id.return_value = alpaca_order
    return adapter


def test_reconcile_updates_native_order_to_filled() -> None:
    session_factory = get_session_factory()
    order_id = _seed_new_order(session_factory, persona_name="VULTURE")
    filled_at = datetime.datetime(2026, 7, 14, 10, 0, tzinfo=datetime.UTC)
    fake_adapter = _alpaca_adapter_returning(
        AlpacaOrder.model_construct(
            status=AlpacaOrderStatus.FILLED, filled_at=filled_at, filled_avg_price="151.25"
        )
    )

    # >= 1, not == 1: other tests in this module share one DB (integration,
    # own committing sessions, see module docstring) and may leave their own
    # still-NEW rows behind — this call's contract is "my row gets reconciled",
    # not "no other row exists".
    count = reconcile_order_fills(session_factory, adapter_factory=lambda _persona: fake_adapter)

    assert count >= 1
    with session_factory() as session:
        order = session.get_one(OrderRecord, order_id)
        assert order.status == OrderRecordStatus.FILLED
        assert order.filled_at == datetime.datetime(2026, 7, 14, 10, 0)
        assert order.fill_price == Decimal("151.25")


def test_reconcile_leaves_still_open_orders_unchanged() -> None:
    session_factory = get_session_factory()
    order_id = _seed_new_order(session_factory, persona_name="VULTURE")
    fake_adapter = _alpaca_adapter_returning(
        AlpacaOrder.model_construct(
            status=AlpacaOrderStatus.NEW, filled_at=None, filled_avg_price=None
        )
    )

    reconcile_order_fills(session_factory, adapter_factory=lambda _persona: fake_adapter)

    with session_factory() as session:
        order = session.get_one(OrderRecord, order_id)
        assert order.status == OrderRecordStatus.NEW


def test_reconcile_skips_internal_ledger_personas() -> None:
    """Virtual personas' fills are recorded synchronously at execute_decision
    time (F075) — a NEW row for one of them means the order never went through,
    not that it's pending broker confirmation. Must not even attempt a poll."""
    session_factory = get_session_factory()
    order_id = _seed_new_order(session_factory, persona_name="HYPE")
    called_for: list[str] = []

    def _factory(persona_name: str) -> AlpacaPaperAdapter:
        called_for.append(persona_name)
        # Other tests in this module may have left still-NEW native-persona
        # rows behind (integration, shared DB) — only HYPE is actually under
        # test here, so any other persona just gets a real, working adapter.
        return _alpaca_adapter_returning(
            AlpacaOrder.model_construct(
                status=AlpacaOrderStatus.NEW, filled_at=None, filled_avg_price=None
            )
        )

    reconcile_order_fills(session_factory, adapter_factory=_factory)

    assert "HYPE" not in called_for
    with session_factory() as session:
        order = session.get_one(OrderRecord, order_id)
        assert order.status == OrderRecordStatus.NEW


def test_reconcile_continues_after_a_poll_failure() -> None:
    session_factory = get_session_factory()
    order_id = _seed_new_order(session_factory, persona_name="VULTURE")

    class _FailingAdapter:
        def get_order_status(self, order_id: str) -> None:
            raise RuntimeError("Alpaca unavailable")

    with patch("src.orchestrator.scheduler.AlpacaPaperAdapter", _FailingAdapter):
        reconcile_order_fills(session_factory, adapter_factory=lambda _persona: _FailingAdapter())

    with session_factory() as session:
        order = session.get_one(OrderRecord, order_id)
        assert order.status == OrderRecordStatus.NEW
