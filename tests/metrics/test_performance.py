"""See docs/features/F082-kennzahlen-modul.md §3, tests 1-7."""

from __future__ import annotations

import datetime
import math
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.db.models import (
    Cycle,
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
from src.metrics.performance import (
    daily_returns,
    max_drawdown,
    simple_return,
    sortino_ratio,
    trade_count,
)


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


def _make_cycle(session: Session) -> Cycle:
    cycle = Cycle(
        trading_day=datetime.date(2026, 8, 3),
        seq=0,
        started_at=datetime.datetime(2026, 8, 3, 6, 0),
        market_session=MarketSession.US_EQUITY,
    )
    session.add(cycle)
    session.flush()
    return cycle


def _make_decision(
    session: Session,
    portfolio_id: uuid.UUID,
    cycle_id: uuid.UUID | None = None,
) -> Decision:
    d = Decision(
        cycle_id=cycle_id or _make_cycle(session).id,
        portfolio_id=portfolio_id,
        instrument="SPY",
        action=DecisionAction.BUY,
        thesis_text="test",
        expected_outcome={},
        input_research_ids=[uuid.uuid4()],
        status=DecisionStatus.APPROVED,
    )
    session.add(d)
    session.flush()
    return d


class TestSimpleReturn:
    """Test 1 from F082 §3."""

    def test_basic(self) -> None:
        assert simple_return([Decimal("5000"), Decimal("5250")]) == pytest.approx(0.05)

    def test_single_element(self) -> None:
        assert simple_return([Decimal("5000")]) == 0.0


class TestDailyReturns:
    """Test 2 from F082 §3."""

    def test_basic(self) -> None:
        result = daily_returns([Decimal("100"), Decimal("102"), Decimal("105")])
        assert len(result) == 2
        assert result[0] == pytest.approx(0.02)
        assert result[1] == pytest.approx(0.0294, abs=1e-3)


class TestSortinoRatio:
    """Test 3 from F082 §3."""

    def test_basic(self) -> None:
        # 20+ data points: base pattern + repeat with negative skew
        returns = [0.01, -0.02, 0.015, -0.005, 0.02] * 4  # 20 elements
        # downside residuals: [-0.02, -0.005] × 4 = 8 negatives
        # total sum of sq: 8 * (0.0004 + 0.000025) / 20 ... simpler:
        downside_sq_sum = sum(min(r, 0.0) ** 2 for r in returns)
        downside_dev = math.sqrt(downside_sq_sum / len(returns))
        mean = sum(returns) / len(returns)
        expected = mean / downside_dev * math.sqrt(252)
        result = sortino_ratio(returns, target=0.0)
        assert result is not None
        assert result == pytest.approx(expected)

    def test_min_n(self) -> None:
        """N < 20 → None."""
        assert sortino_ratio([0.01, -0.02, 0.015], target=0.0) is None

    def test_no_negative_returns(self) -> None:
        """No downside → None (not ∞)."""
        returns = [0.01, 0.02, 0.03] * 7  # 21 elements, all positive
        assert sortino_ratio(returns, target=0.0) is None


class TestMaxDrawdown:
    """Test 4 from F082 §3."""

    def test_basic(self) -> None:
        values = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110"), Decimal("80")]
        # Peak 120, trough 80 → (120-80)/120 ≈ 0.3333
        assert max_drawdown(values) == pytest.approx(0.3333, abs=1e-3)

    def test_monotonic_increasing(self) -> None:
        assert max_drawdown([Decimal("100"), Decimal("110"), Decimal("120")]) == 0.0

    def test_drawdown_then_recovery(self) -> None:
        """100→90 is a 10 % drawdown even though 120 comes after."""
        assert max_drawdown([Decimal("100"), Decimal("90"), Decimal("120")]) == pytest.approx(0.1)

    def test_single_value(self) -> None:
        assert max_drawdown([Decimal("100")]) == 0.0


class TestTradeCount:
    """Test 5 from F082 §3."""

    def test_only_filled_since_stichtag(self, session: Session) -> None:
        portfolio = _make_portfolio(session)
        stichtag = datetime.datetime(2026, 8, 3)

        # 3 FILLED decisions after stichtag
        for i in range(3):
            dec = _make_decision(session, portfolio.id)
            session.add(
                OrderRecord(
                    decision_id=dec.id,
                    broker="alpaca",
                    mode=PortfolioMode.PAPER,
                    submitted_at=stichtag + datetime.timedelta(days=i + 1),
                    status=OrderRecordStatus.FILLED,
                )
            )

        # 1 CANCELED after stichtag — should NOT count
        dec = _make_decision(session, portfolio.id)
        session.add(
            OrderRecord(
                decision_id=dec.id,
                broker="alpaca",
                mode=PortfolioMode.PAPER,
                submitted_at=stichtag + datetime.timedelta(days=1),
                status=OrderRecordStatus.CANCELED,
            )
        )

        # 1 FILLED before stichtag — should NOT count
        dec = _make_decision(session, portfolio.id)
        session.add(
            OrderRecord(
                decision_id=dec.id,
                broker="alpaca",
                mode=PortfolioMode.PAPER,
                submitted_at=stichtag - datetime.timedelta(days=1),
                status=OrderRecordStatus.FILLED,
            )
        )

        session.flush()
        assert trade_count(session, portfolio.id, stichtag) == 3
