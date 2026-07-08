"""Minimal object builders for tests/db — not a general-purpose factory framework,
just enough to construct a valid lineage chain without repeating boilerplate."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    AgentRunStatus,
    CostLedger,
    CostLedgerScope,
    Cycle,
    Decision,
    DecisionAction,
    MarketSession,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
    PortfolioMode,
    PortfolioSnapshot,
    PositionSnapshot,
    ResearchItem,
    Review,
    ReviewVerdict,
)


def make_persona(session: Session, **overrides: object) -> Persona:
    persona = Persona(
        name=overrides.get("name", f"TEST_{uuid.uuid4().hex[:8]}"),
        charter_version=1,
        model="claude-sonnet-5",
        config_ref="config/personas/test.yaml",
    )
    session.add(persona)
    session.flush()
    return persona


def make_portfolio(session: Session, persona: Persona, **overrides: object) -> Portfolio:
    portfolio = Portfolio(
        persona_id=persona.id,
        mode=overrides.get("mode", PortfolioMode.PAPER),
        broker_account_ref="PA32N1PG3J5G",
        base_ccy="USD",
        start_value=Decimal("5000.00"),
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def make_cycle(session: Session, **overrides: object) -> Cycle:
    cycle = Cycle(
        trading_day=datetime.date(2026, 7, 4),
        seq=1,
        started_at=datetime.datetime(2026, 7, 4, 9, 0),
        market_session=overrides.get("market_session", MarketSession.US_EQUITY),
    )
    session.add(cycle)
    session.flush()
    return cycle


def make_research_item(session: Session, cycle: Cycle, **overrides: object) -> ResearchItem:
    item = ResearchItem(
        cycle_id=cycle.id,
        agent="market_research",
        source_type="market_data",
        source_ref="screener",
        summary="Test research summary",
        instruments=["AAPL"],
        raw={},
    )
    session.add(item)
    session.flush()
    return item


def make_decision(
    session: Session,
    cycle: Cycle,
    portfolio: Portfolio,
    research_item: ResearchItem,
    **overrides: object,
) -> Decision:
    decision = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument=overrides.get("instrument", "AAPL"),
        action=overrides.get("action", DecisionAction.BUY),
        quantity=overrides.get("quantity", Decimal("10")),
        thesis_text="Test thesis",
        rejection_reason=overrides.get("rejection_reason"),
        expected_outcome=overrides.get(
            "expected_outcome",
            {"target_price": 160.0, "horizon_days": 10, "stop_loss_price": 140.0},
        ),
        input_research_ids=overrides.get("input_research_ids", [research_item.id]),
    )
    session.add(decision)
    session.flush()
    return decision


def make_order_record(session: Session, decision: Decision, **overrides: object) -> OrderRecord:
    order = OrderRecord(
        decision_id=overrides.get("decision_id", decision.id),
        broker="alpaca_paper",
        broker_order_id="entry-123",
        mode=PortfolioMode.PAPER,
        submitted_at=overrides.get("submitted_at", datetime.datetime(2026, 7, 4, 9, 1)),
        filled_at=overrides.get("filled_at"),
        fill_price=overrides.get("fill_price"),
        status=overrides.get("status", OrderRecordStatus.FILLED),
        fees=Decimal("0"),
    )
    session.add(order)
    session.flush()
    return order


def make_agent_run(session: Session, cycle: Cycle, **overrides: object) -> AgentRun:
    run = AgentRun(
        cycle_id=cycle.id,
        portfolio_id=overrides.get("portfolio_id"),
        agent=overrides.get("agent", "market_research"),
        status=overrides.get("status", AgentRunStatus.SUCCEEDED),
        tokens_in=overrides.get("tokens_in", 1000),
        tokens_out=overrides.get("tokens_out", 200),
        cost_usd=overrides.get("cost_usd", Decimal("0.05")),
    )
    session.add(run)
    session.flush()
    return run


def make_position_snapshot(
    session: Session, portfolio: Portfolio, **overrides: object
) -> PositionSnapshot:
    snapshot = PositionSnapshot(
        ts=datetime.datetime(2026, 7, 4, 16, 0),
        portfolio_id=portfolio.id,
        instrument="AAPL",
        qty=Decimal("10"),
        avg_price=Decimal("150.00"),
        market_value=Decimal("1550.00"),
        pnl_unrealized=Decimal("50.00"),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def make_portfolio_snapshot(
    session: Session, portfolio: Portfolio, **overrides: object
) -> PortfolioSnapshot:
    snapshot = PortfolioSnapshot(
        ts=datetime.datetime(2026, 7, 4, 16, 0),
        portfolio_id=portfolio.id,
        total_value=Decimal("5050.00"),
        cash=Decimal("3500.00"),
        pnl_realized=Decimal("0.00"),
        pnl_unrealized=Decimal("50.00"),
        benchmark_value=overrides.get("benchmark_value"),
        max_drawdown=Decimal("0.0000"),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def make_review(session: Session, decision: Decision, **overrides: object) -> Review:
    review = Review(
        decision_id=decision.id,
        reviewed_at=datetime.datetime(2026, 7, 11, 9, 0),
        expected={"target_price": 160.0},
        actual={"price": 158.0},
        deviation=Decimal("-1.25"),
        slippage_malus=overrides.get("slippage_malus", Decimal("0.02")),
        verdict=overrides.get("verdict", ReviewVerdict.THESIS_CONFIRMED),
        lessons_text=overrides.get("lessons_text"),
    )
    session.add(review)
    session.flush()
    return review


def make_cost_ledger_entry(session: Session, **overrides: object) -> CostLedger:
    entry = CostLedger(
        ts=datetime.datetime(2026, 7, 4, 9, 0),
        scope=overrides.get("scope", CostLedgerScope.PERSONA),
        persona_id=overrides.get("persona_id"),
        provider="anthropic",
        model="claude-sonnet-5",
        tokens_in=1000,
        tokens_out=200,
        cost_usd=Decimal("0.05"),
    )
    session.add(entry)
    session.flush()
    return entry
