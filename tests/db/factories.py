"""Minimal object builders for tests/db — not a general-purpose factory framework,
just enough to construct a valid lineage chain without repeating boilerplate."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import (
    Cycle,
    Decision,
    DecisionAction,
    MarketSession,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
    PortfolioMode,
    ResearchItem,
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
        expected_outcome={"target_price": 160.0, "horizon_days": 10, "stop_loss": 140.0},
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
        submitted_at=datetime.datetime(2026, 7, 4, 9, 1),
        status=OrderRecordStatus.FILLED,
        fees=Decimal("0"),
    )
    session.add(order)
    session.flush()
    return order
