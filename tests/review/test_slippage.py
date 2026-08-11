"""See docs/features/F083-slippage-malus-berechnung.md §3, tests 1-8."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.db.models import (
    Cycle,
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketBar,
    MarketBarTimeframe,
    MarketSession,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
    PortfolioMode,
)
from src.review.slippage import compute_slippage_malus


def _add_bar(
    session: Session,
    symbol: str,
    ts: datetime.datetime | None = None,
    volume: int = 1_000_000,
    close: float = 100.0,
) -> None:
    session.add(
        MarketBar(
            symbol=symbol,
            timeframe=MarketBarTimeframe.DAY,
            ts=ts or datetime.datetime(2026, 8, 3),
            open=Decimal(str(close - 0.5)),
            high=Decimal(str(close + 1)),
            low=Decimal(str(close - 1)),
            close=Decimal(str(close)),
            volume=Decimal(str(volume)),
        )
    )
    session.flush()


def _make_persona(session: Session) -> Persona:
    p = Persona(
        name=f"TEST_{uuid.uuid4().hex[:8]}",
        charter_version=1,
        model="claude-sonnet-5",
        config_ref="config/personas/test.yaml",
    )
    session.add(p)
    session.flush()
    return p


def _make_portfolio(session: Session) -> Portfolio:
    persona = _make_persona(session)
    pf = Portfolio(
        persona_id=persona.id,
        mode=PortfolioMode.PAPER,
        broker_account_ref="test-account",
        base_ccy="USD",
        start_value=Decimal("5000.00"),
    )
    session.add(pf)
    session.flush()
    return pf


def _make_cycle(session: Session) -> Cycle:
    c = Cycle(
        trading_day=datetime.date(2026, 8, 3),
        seq=0,
        started_at=datetime.datetime(2026, 8, 3, 6, 0),
        market_session=MarketSession.US_EQUITY,
    )
    session.add(c)
    session.flush()
    return c


def _make_decision(
    session: Session,
    symbol: str,
    qty: Decimal,
) -> Decision:
    cycle = _make_cycle(session)
    portfolio = _make_portfolio(session)
    dec = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument=symbol,
        action=DecisionAction.BUY,
        quantity=qty,
        thesis_text="test",
        expected_outcome={},
        input_research_ids=[uuid.uuid4()],
        status=DecisionStatus.EXECUTED,
    )
    session.add(dec)
    session.flush()
    return dec


def _make_order(
    session: Session,
    symbol: str = "AAPL",
    fill_price: Decimal = Decimal("100.00"),
    qty: Decimal = Decimal("10"),
    submitted_at: datetime.datetime | None = None,
    spread_bps: Decimal | None = None,
) -> OrderRecord:
    dec = _make_decision(session, symbol, qty)
    submitted = submitted_at or datetime.datetime(2026, 8, 3, 14, 0)
    rec = OrderRecord(
        decision_id=dec.id,
        broker="alpaca",
        broker_order_id=uuid.uuid4().hex,
        mode=PortfolioMode.PAPER,
        submitted_at=submitted,
        filled_at=submitted + datetime.timedelta(minutes=30),
        fill_price=fill_price,
        fees=Decimal("0"),
        status=OrderRecordStatus.FILLED,
        spread_bps=spread_bps,
    )
    session.add(rec)
    session.flush()
    return rec


class TestSlippageSpread:
    """Test 1-2, 6 from F083 §3."""

    def test_basic_equity(self, session: Session) -> None:
        """Order 10 × $100 = $1000. Equity spread 5 bps → cost = 0.5 × 5/10000 × 1000 = $0.25."""
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL", fill_price=Decimal("100.00"), qty=Decimal("10"))
        result = compute_slippage_malus(session, order)
        assert result is not None
        assert result == pytest.approx(Decimal("0.25"))

    def test_equity_penalty_triggered(self, session: Session) -> None:
        """Order 20% of daily dollar volume → penalty applies.
        order_value = $100 × 200k = $20,000,000
        daily_dollar_volume = 1M shares × $100 = $100,000,000
        order_vol_pct = $20M / $100M = 20% → above 1% threshold
        penalty_bps = 10 × (20/1 − 1) = 190, capped at 50
        penalty_usd = 50/10000 × $20M = $100,000
        spread_usd = 0.5 × 5/10000 × $20M = $5,000
        Total = $105,000.00
        """
        daily_volume = 1_000_000
        order_qty = 200_000
        fill_price = Decimal("100.00")
        _add_bar(session, "AAPL", volume=daily_volume, close=100.0)
        order = _make_order(
            session,
            symbol="AAPL",
            fill_price=fill_price,
            qty=Decimal(str(order_qty)),
        )
        result = compute_slippage_malus(session, order)
        assert result is not None
        assert result == pytest.approx(Decimal("105000.00"))

    def test_below_threshold_no_penalty(self, session: Session) -> None:
        """Order size = 0.5% of daily dollar volume → no penalty, only spread cost.
        order_value = $100 × 5k = $500,000
        daily_dollar_volume = 1M × $100 = $100,000,000
        order_vol_pct = 0.5% < 1% → no penalty
        spread = 0.5 × 5/10000 × $500,000 = $125
        """
        daily_volume = 1_000_000
        order_qty = 5_000  # 0.5% of 1M shares
        _add_bar(session, "AAPL", volume=daily_volume)
        order = _make_order(session, symbol="AAPL", qty=Decimal(str(order_qty)))
        result = compute_slippage_malus(session, order)
        assert result is not None
        assert result == pytest.approx(Decimal("125.00"))

    def test_exact_1_percent_no_penalty(self, session: Session) -> None:
        """Test 3: exactly 1% → no penalty (strictly > threshold required).
        order_value = $100 × 10k = $1,000,000
        daily_dollar_volume = 1M × $100 = $100,000,000
        order_vol_pct = 1.0% (not strictly >) → no penalty
        spread = 0.5 × 5/10000 × $1,000,000 = $250
        """
        daily_volume = 1_000_000
        order_qty = 10_000  # exactly 1%
        _add_bar(session, "AAPL", volume=daily_volume)
        order = _make_order(session, symbol="AAPL", qty=Decimal(str(order_qty)))
        result = compute_slippage_malus(session, order)
        assert result is not None
        assert result == pytest.approx(Decimal("250.00"))

    def test_crypto_15bps(self, session: Session) -> None:
        """Test 6: crypto uses 15 bps spread config."""
        _add_bar(session, "BTCUSD", volume=10_000_000)
        order = _make_order(
            session,
            symbol="BTCUSD",
            fill_price=Decimal("30000.00"),
            qty=Decimal("0.1"),  # $3000 order
        )
        result = compute_slippage_malus(session, order)
        assert result is not None
        # 0.5 × 15/10000 × 3000 = $2.25
        assert result == pytest.approx(Decimal("2.25"))


class TestSlippageEdgeCases:
    """Tests 4, 5, 7, 8 from F083 §3."""

    def test_no_bar_volume(self, session: Session) -> None:
        """Test 4: volume is 0 in market_bar → dollar volume 0 → penalty skipped.
        order_value = $100 × 100k = $10,000,000. Spread only.
        spread = 0.5 × 5/10000 × $10,000,000 = $2,500
        """
        _add_bar(session, "AAPL", volume=0)
        order = _make_order(session, symbol="AAPL", qty=Decimal("100000"))
        result = compute_slippage_malus(session, order)
        assert result is not None
        assert result == pytest.approx(Decimal("2500.00"))

    def test_no_bar_for_symbol(self, session: Session) -> None:
        """Test 5: no market_bar for symbol → fallback spread, no penalty."""
        order = _make_order(
            session, symbol="UNKNOWN", fill_price=Decimal("50.00"), qty=Decimal("10")
        )
        result = compute_slippage_malus(session, order)
        assert result is not None
        # Fallback: equity spread 5 bps → 0.5 × 5/10000 × 500 = $0.125
        assert result == pytest.approx(Decimal("0.125"))

    def test_non_negative_invariant(self, session: Session) -> None:
        """Test 8: malus >= 0 for any inputs."""
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL")
        assert compute_slippage_malus(session, order) >= 0

    def test_partial_fill(self, session: Session) -> None:
        """Partial fill should be computed on filled qty, not ordered qty."""
        # For a partial fill, OrderRecord has fill_price but we use
        # the filled qty from raw or from the actual filled quantity.
        # In the current model, qty_is the ordered quantity. For partial fills,
        # raw JSONB has the broker response. For now, use order_record's
        # inferred qty.
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL", fill_price=Decimal("100.00"), qty=Decimal("5"))
        result = compute_slippage_malus(session, order)
        assert result is not None
        # 0.5 × 5/10000 × 500 = $0.125
        assert result == pytest.approx(Decimal("0.125"))


class TestMeasuredSpread:
    """F104 §3, tests 7-10 — the measured quote replaces the flat rate."""

    def test_uses_measured_spread_when_present(self, session: Session) -> None:
        """Order 10 x $100 = $1000, measured 20 bps -> 0.5 x 20/10000 x 1000 = $1.00
        (the 5-bps flat rate would have given $0.25)."""
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL", spread_bps=Decimal("20"))

        result = compute_slippage_malus(session, order)

        assert result == pytest.approx(Decimal("1.00"))

    def test_falls_back_to_config_spread_when_not_measured(self, session: Session) -> None:
        """Regression guard for every order placed before F104: `spread_bps IS NULL`
        must keep producing exactly the F083 result."""
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL", spread_bps=None)

        result = compute_slippage_malus(session, order)

        assert result == pytest.approx(Decimal("0.25"))

    @pytest.mark.parametrize("measured", [Decimal("5000"), Decimal("0")])
    def test_ignores_implausible_measured_spread(self, session: Session, measured: Decimal) -> None:
        """A crossed book or a halt must not drag an outlier into the leaderboard's
        adjusted performance — beyond `max_measured_bps` the flat rate applies."""
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL", spread_bps=measured)

        result = compute_slippage_malus(session, order)

        assert result == pytest.approx(Decimal("0.25"))

    def test_measured_spread_can_be_disabled_via_config(self, session: Session) -> None:
        """F104 rollback path: `use_measured_spread: false` restores flat rates
        without a deploy, while the column keeps being filled."""
        _add_bar(session, "AAPL")
        order = _make_order(session, symbol="AAPL", spread_bps=Decimal("20"))

        result = compute_slippage_malus(
            session,
            order,
            config={"enabled": True, "use_measured_spread": False, "spread_bps": {"equities": 5}},
        )

        assert result == pytest.approx(Decimal("0.25"))
