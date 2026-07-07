"""See docs/features/F020-portfolio-risk-inputs.md §3."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from src.broker.protocol import AccountBalance, OrderSide, Position
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
    PortfolioSnapshot,
    ResearchItem,
)
from src.orchestrator.graph import create_cycle
from src.orchestrator.risk_inputs import read_portfolio_risk_state

_NOW = datetime.datetime(2026, 7, 7, 10, 0)


def _current_cycle_id(session: Session, market_session: MarketSession = MarketSession.US_EQUITY):
    """A fresh 'current' cycle whose `trading_day` (2026-07-07) is what
    `read_portfolio_risk_state` treats as "today" — separate from any cycle rows
    `_make_decision_with_order`/`_make_reject_idea_decision` create for historical
    order records, which represent *when* a past decision happened, not "now"."""
    return create_cycle(session, _NOW.date(), 99, market_session).id


class _FakeAdapter:
    def __init__(self, balance: AccountBalance, positions: list[Position]) -> None:
        self._balance = balance
        self._positions = positions

    def place_order(self, **kwargs: object) -> object:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    def get_positions(self) -> list[Position]:
        return self._positions

    def get_account_balance(self) -> AccountBalance:
        return self._balance


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


def test_reads_equity_and_cash_from_adapter(session: Session) -> None:
    portfolio = _make_portfolio(session)
    adapter = _FakeAdapter(AccountBalance(cash=1000.0, equity=5200.0, buying_power=1000.0), [])

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.equity_usd == 5200.0
    assert state.cash_usd == 1000.0


def test_open_positions_count_matches_adapter_positions(session: Session) -> None:
    portfolio = _make_portfolio(session)
    positions = [
        Position(
            symbol="AAPL",
            qty=10,
            side=OrderSide.BUY,
            avg_entry_price=150.0,
            market_value=1550.0,
            unrealized_pl=50.0,
        ),
        Position(
            symbol="MSFT",
            qty=5,
            side=OrderSide.BUY,
            avg_entry_price=300.0,
            market_value=1600.0,
            unrealized_pl=100.0,
        ),
    ]
    adapter = _FakeAdapter(AccountBalance(cash=0.0, equity=5000.0, buying_power=0.0), positions)

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.open_positions_count == 2


def test_peak_equity_falls_back_to_current_equity_without_history(session: Session) -> None:
    portfolio = _make_portfolio(session)
    adapter = _FakeAdapter(AccountBalance(cash=1000.0, equity=5000.0, buying_power=1000.0), [])

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.peak_equity_usd == 5000.0


def test_peak_equity_uses_higher_historical_snapshot(session: Session) -> None:
    portfolio = _make_portfolio(session)
    session.add(
        PortfolioSnapshot(
            ts=datetime.datetime(2026, 7, 1, 16, 0),
            portfolio_id=portfolio.id,
            total_value=Decimal("6000.00"),
            cash=Decimal("1000.00"),
            pnl_realized=Decimal("0"),
            pnl_unrealized=Decimal("0"),
            max_drawdown=Decimal("0"),
        )
    )
    session.flush()
    adapter = _FakeAdapter(AccountBalance(cash=1000.0, equity=5000.0, buying_power=1000.0), [])

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.peak_equity_usd == 6000.0


def _make_decision_with_order(
    session: Session, portfolio: Portfolio, submitted_at: datetime.datetime
) -> None:
    cycle = create_cycle(session, submitted_at.date(), 1, MarketSession.US_EQUITY)
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
        quantity=Decimal("1"),
        thesis_text="test",
        expected_outcome={},
        input_research_ids=[item.id],
        status=DecisionStatus.EXECUTED,
    )
    session.add(decision)
    session.flush()
    session.add(
        OrderRecord(
            decision_id=decision.id,
            broker="alpaca_paper",
            mode=PortfolioMode.PAPER,
            submitted_at=submitted_at,
            status=OrderRecordStatus.FILLED,
        )
    )
    session.flush()


def _make_reject_idea_decision(session: Session, portfolio: Portfolio) -> None:
    cycle = create_cycle(session, _NOW.date(), 2, MarketSession.US_EQUITY)
    item = ResearchItem(
        cycle_id=cycle.id,
        agent="market_research",
        source_type="screener_result",
        source_ref="MSFT",
        summary="test",
        instruments=["MSFT"],
        raw={},
    )
    session.add(item)
    session.flush()
    session.add(
        Decision(
            cycle_id=cycle.id,
            portfolio_id=portfolio.id,
            instrument="MSFT",
            action=DecisionAction.REJECT_IDEA,
            thesis_text="test",
            rejection_reason="not worth it",
            expected_outcome={},
            input_research_ids=[item.id],
            status=DecisionStatus.RECORDED,
        )
    )
    session.flush()


def test_trades_today_counts_only_todays_order_records_for_this_portfolio(
    session: Session,
) -> None:
    portfolio = _make_portfolio(session)
    other_portfolio = _make_portfolio(session)
    _make_decision_with_order(session, portfolio, datetime.datetime(2026, 7, 7, 9, 30))
    _make_decision_with_order(session, portfolio, datetime.datetime(2026, 7, 6, 9, 30))
    _make_decision_with_order(session, other_portfolio, datetime.datetime(2026, 7, 7, 9, 30))
    adapter = _FakeAdapter(AccountBalance(cash=0.0, equity=5000.0, buying_power=0.0), [])

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.trades_today_count == 1


def test_trades_today_uses_market_timezone_not_utc_calendar_day(session: Session) -> None:
    """security-audit P7: an order submitted late in the US trading day (still
    2026-07-07 in America/New_York, EDT = UTC-4 in July) but past UTC midnight
    (2026-07-08 02:00 UTC) must still count for the 2026-07-07 trading_day cycle —
    the old UTC-calendar-day slicing would have missed it."""
    portfolio = _make_portfolio(session)
    _make_decision_with_order(session, portfolio, datetime.datetime(2026, 7, 8, 2, 0))
    adapter = _FakeAdapter(AccountBalance(cash=0.0, equity=5000.0, buying_power=0.0), [])

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.trades_today_count == 1


def test_reject_idea_without_order_record_does_not_count_as_trade(session: Session) -> None:
    portfolio = _make_portfolio(session)
    _make_reject_idea_decision(session, portfolio)
    adapter = _FakeAdapter(AccountBalance(cash=0.0, equity=5000.0, buying_power=0.0), [])

    state = read_portfolio_risk_state(session, adapter, portfolio.id, _current_cycle_id(session))

    assert state.trades_today_count == 0
