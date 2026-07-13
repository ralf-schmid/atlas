"""See docs/features/F050-stop-loss-tick-rounding.md §3. Marked integration: needs
a real, independently-committing session_factory (`retry_stuck_decisions` opens+
commits its own session per F016 §2 thread-safety convention), same reason
tests/orchestrator/test_hitl_sweep.py can't use the rolled-back `session` fixture.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.broker.protocol import AccountBalance, OrderResult, OrderSide, Position
from src.db.base import get_session_factory
from src.db.models import (
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketSession,
    OrderRecord,
    Persona,
    Portfolio,
    PortfolioSnapshot,
)
from src.orchestrator.graph import create_cycle
from src.orchestrator.scheduler import retry_stuck_decisions
from src.orchestrator.seed import seed_personas_and_portfolios

pytestmark = pytest.mark.integration


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

    def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol="AAPL",
                qty=2.0,
                side=OrderSide.BUY,
                avg_entry_price=150.0,
                market_value=310.0,
                unrealized_pl=10.0,
            )
        ]

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(cash=4700.0, equity=5010.0, buying_power=4700.0)


def _seed_approved_decision(
    session_factory, *, stop_loss_price: float = 140.0, with_order_record: bool = False
) -> uuid.UUID:
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
            quantity=Decimal("2"),
            thesis_text="test",
            expected_outcome={
                "entry_price": 150.0,
                "stop_loss_price": stop_loss_price,
                "conviction": 0.5,
            },
            input_research_ids=[uuid.uuid4()],
            status=DecisionStatus.APPROVED,
        )
        session.add(decision)
        session.flush()

        if with_order_record:
            session.add(
                OrderRecord(
                    decision_id=decision.id,
                    broker="alpaca_paper",
                    broker_order_id="already-placed",
                    mode=portfolio.mode,
                    submitted_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                    fees=Decimal("0"),
                )
            )

        session.commit()
        return decision.id


def test_retry_executes_orphaned_approved_decision() -> None:
    session_factory = get_session_factory()
    decision_id = _seed_approved_decision(session_factory, stop_loss_price=290.8672)
    fake_adapter = _FakeAdapter()

    count = retry_stuck_decisions(session_factory, adapter_factory=lambda _persona: fake_adapter)

    assert count == 1
    # F050: the stale, unrounded stop from before the fix must still reach the
    # broker rounded, not as the raw 290.8672 that Alpaca originally rejected.
    (call,) = fake_adapter.calls
    assert call["stop_loss_price"] == 290.87
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.status == DecisionStatus.EXECUTED
        order_record = session.scalar(
            select(OrderRecord).where(OrderRecord.decision_id == decision_id)
        )
        assert order_record is not None
        # F059: without a fresh snapshot right here, the new position stays
        # invisible in the dashboard/Grafana until whatever cycle next runs for
        # this portfolio.
        snapshot = session.scalar(
            select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == decision.portfolio_id)
        )
        assert snapshot is not None


def test_retry_sends_a_telegram_trade_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    """F072: a decision executed via the stuck-decision retry sweep is just as much
    "a persona traded" as one executed inline during the cycle — same notification."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    session_factory = get_session_factory()
    _seed_approved_decision(session_factory, stop_loss_price=140.0)
    fake_adapter = _FakeAdapter()

    with patch("src.telegram.alerts.Bot") as mock_bot_cls:
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        count = retry_stuck_decisions(
            session_factory, adapter_factory=lambda _persona: fake_adapter
        )

    assert count == 1
    mock_bot.send_message.assert_called_once()
    call = mock_bot.send_message.call_args
    assert call.kwargs["chat_id"] == 42
    assert "AAPL" in call.kwargs["text"]


def test_retry_skips_decision_that_already_has_an_order_record() -> None:
    session_factory = get_session_factory()
    _seed_approved_decision(session_factory, with_order_record=True)
    fake_adapter = _FakeAdapter()

    count = retry_stuck_decisions(session_factory, adapter_factory=lambda _persona: fake_adapter)

    assert count == 0
    assert fake_adapter.calls == []


def test_retry_leaves_decision_approved_on_repeated_broker_failure() -> None:
    session_factory = get_session_factory()
    decision_id = _seed_approved_decision(session_factory)
    fake_adapter = _FakeAdapter(should_fail=True)
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        snapshot_count_before = len(
            session.scalars(
                select(PortfolioSnapshot).where(
                    PortfolioSnapshot.portfolio_id == decision.portfolio_id
                )
            ).all()
        )

    count = retry_stuck_decisions(session_factory, adapter_factory=lambda _persona: fake_adapter)

    assert count == 0
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.status == DecisionStatus.APPROVED
        assert (
            session.scalar(select(OrderRecord).where(OrderRecord.decision_id == decision_id))
            is None
        )
        # F059: a failed execute_decision must not create a snapshot either — the
        # broker-side state didn't actually change.
        snapshot_count_after = len(
            session.scalars(
                select(PortfolioSnapshot).where(
                    PortfolioSnapshot.portfolio_id == decision.portfolio_id
                )
            ).all()
        )
        assert snapshot_count_after == snapshot_count_before


def test_retry_keeps_the_order_when_the_post_trade_snapshot_fails() -> None:
    # F063: execute_decision succeeding and then generate_portfolio_snapshot
    # failing must not roll back the order that already went through — the two
    # are committed as separate transactions specifically so a snapshot hiccup
    # can't undo a real trade.
    class _SnapshotFailingAdapter(_FakeAdapter):
        def get_positions(self) -> list[Position]:
            raise RuntimeError("broker timeout building snapshot")

    session_factory = get_session_factory()
    decision_id = _seed_approved_decision(session_factory)
    fake_adapter = _SnapshotFailingAdapter()

    count = retry_stuck_decisions(session_factory, adapter_factory=lambda _persona: fake_adapter)

    # >= 1, not ==: other decisions sharing this module's VULTURE portfolio
    # (e.g. one permanently stuck by test_retry_leaves_decision_approved_on_
    # repeated_broker_failure above) may also get swept in the same call —
    # this test only asserts on its own decision's outcome.
    assert count >= 1
    with session_factory() as session:
        decision = session.get_one(Decision, decision_id)
        assert decision.status == DecisionStatus.EXECUTED
        order_record = session.scalar(
            select(OrderRecord).where(OrderRecord.decision_id == decision_id)
        )
        assert order_record is not None
