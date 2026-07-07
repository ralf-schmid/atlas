"""See docs/features/F024-reporting-agent.md §3, tests 1-6."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import AccountBalance, OrderSide, Position
from src.db.models import Persona, Portfolio, PortfolioMode, PortfolioSnapshot, PositionSnapshot
from src.orchestrator.reporting import generate_portfolio_snapshot

_NOW = datetime.datetime(2026, 7, 7, 16, 0)


class _FakeAdapter:
    def __init__(self, balance: AccountBalance, positions: list[Position] | None = None) -> None:
        self._balance = balance
        self._positions = positions or []

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


def test_snapshot_persists_total_value_cash_and_unrealized_pnl(session: Session) -> None:
    portfolio = _make_portfolio(session)
    positions = [
        Position(
            symbol="AAPL",
            qty=10,
            side=OrderSide.BUY,
            avg_entry_price=150.0,
            market_value=1600.0,
            unrealized_pl=100.0,
        ),
        Position(
            symbol="MSFT",
            qty=5,
            side=OrderSide.BUY,
            avg_entry_price=300.0,
            market_value=1550.0,
            unrealized_pl=-50.0,
        ),
    ]
    adapter = _FakeAdapter(
        AccountBalance(cash=1000.0, equity=5200.0, buying_power=1000.0), positions
    )

    snapshot = generate_portfolio_snapshot(session, portfolio.id, adapter, _NOW)

    assert snapshot.total_value == Decimal("5200.00")
    assert snapshot.cash == Decimal("1000.00")
    assert snapshot.pnl_unrealized == Decimal("50.00")


def test_snapshot_persists_one_position_snapshot_per_position(session: Session) -> None:
    portfolio = _make_portfolio(session)
    positions = [
        Position(
            symbol="AAPL",
            qty=10,
            side=OrderSide.BUY,
            avg_entry_price=150.0,
            market_value=1600.0,
            unrealized_pl=100.0,
        )
    ]
    adapter = _FakeAdapter(
        AccountBalance(cash=1000.0, equity=2600.0, buying_power=1000.0), positions
    )

    generate_portfolio_snapshot(session, portfolio.id, adapter, _NOW)

    rows = session.scalars(
        select(PositionSnapshot).where(PositionSnapshot.portfolio_id == portfolio.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].instrument == "AAPL"
    assert rows[0].qty == Decimal("10")
    assert rows[0].avg_price == Decimal("150")
    assert rows[0].market_value == Decimal("1600")
    assert rows[0].pnl_unrealized == Decimal("100")


def test_snapshot_with_no_positions_has_zero_unrealized_pnl(session: Session) -> None:
    portfolio = _make_portfolio(session)
    adapter = _FakeAdapter(AccountBalance(cash=5000.0, equity=5000.0, buying_power=5000.0))

    snapshot = generate_portfolio_snapshot(session, portfolio.id, adapter, _NOW)

    assert snapshot.pnl_unrealized == Decimal("0")
    rows = session.scalars(
        select(PositionSnapshot).where(PositionSnapshot.portfolio_id == portfolio.id)
    ).all()
    assert rows == []


def test_max_drawdown_zero_without_history(session: Session) -> None:
    portfolio = _make_portfolio(session)
    adapter = _FakeAdapter(AccountBalance(cash=5000.0, equity=5000.0, buying_power=5000.0))

    snapshot = generate_portfolio_snapshot(session, portfolio.id, adapter, _NOW)

    assert snapshot.max_drawdown == Decimal("0")


def test_max_drawdown_uses_historical_peak(session: Session) -> None:
    portfolio = _make_portfolio(session)
    session.add(
        PortfolioSnapshot(
            ts=_NOW - datetime.timedelta(days=1),
            portfolio_id=portfolio.id,
            total_value=Decimal("6000.00"),
            cash=Decimal("1000.00"),
            pnl_realized=Decimal("0"),
            pnl_unrealized=Decimal("0"),
            max_drawdown=Decimal("0"),
        )
    )
    session.flush()
    adapter = _FakeAdapter(AccountBalance(cash=1000.0, equity=5000.0, buying_power=1000.0))

    snapshot = generate_portfolio_snapshot(session, portfolio.id, adapter, _NOW)

    # (6000 - 5000) / 6000 = 0.1667
    assert snapshot.max_drawdown == Decimal("0.16666666666666666")


def test_pnl_realized_and_benchmark_are_documented_non_scope_defaults(session: Session) -> None:
    portfolio = _make_portfolio(session)
    adapter = _FakeAdapter(AccountBalance(cash=5000.0, equity=5000.0, buying_power=5000.0))

    snapshot = generate_portfolio_snapshot(session, portfolio.id, adapter, _NOW)

    assert snapshot.pnl_realized == Decimal("0")
    assert snapshot.benchmark_value is None
