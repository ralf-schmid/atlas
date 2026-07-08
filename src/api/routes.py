"""Persona-facing read endpoints — portfolio snapshot (F007), profile/holdings/
transactions/decisions (F034). All read-only, no LLM, no broker access.
"""

from __future__ import annotations

import datetime
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.schemas import (
    DecisionOut,
    HoldingOut,
    PersonaProfileOut,
    PortfolioSnapshotOut,
    PositionOut,
    ResearchRefOut,
    TransactionOut,
)
from src.db.base import get_session_factory
from src.db.models import (
    Cycle,
    Decision,
    DecisionAction,
    OrderRecord,
    Persona,
    Portfolio,
    PortfolioMode,
    PortfolioSnapshot,
    PositionSnapshot,
    ResearchItem,
)
from src.orchestrator.persona_analysis import compute_age_days
from src.personas.charters import get_persona_profile

router = APIRouter(prefix="/api")

# Lazy: building the engine at import time requires DATABASE_URL to be set just to
# import this module (breaks test collection and any tooling that imports the app).
_session_factory: sessionmaker[Session] | None = None

_DEFAULT_DECISION_LIMIT = 50


def get_session() -> Generator[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def _get_persona_and_portfolio(
    session: Session, name: str, mode: PortfolioMode
) -> tuple[Persona, Portfolio]:
    """`mode` selects the portfolio once paper and live run in parallel (Phase 6+);
    default is paper — the only mode that exists before then."""
    persona = session.scalar(select(Persona).where(Persona.name == name.upper()))
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {name!r}")

    portfolio = session.scalar(
        select(Portfolio).where(Portfolio.persona_id == persona.id, Portfolio.mode == mode)
    )
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail=f"No {mode.value} portfolio for persona: {name!r}"
        )
    return persona, portfolio


@router.get("/personas/{name}/snapshot", response_model=PortfolioSnapshotOut)
def get_persona_snapshot(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> PortfolioSnapshotOut:
    persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    latest_snapshot = session.scalar(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    if latest_snapshot is None:
        raise HTTPException(status_code=404, detail=f"No snapshot yet for persona: {name!r}")

    positions = session.scalars(
        select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.ts == latest_snapshot.ts,
        )
    ).all()

    return PortfolioSnapshotOut(
        persona=persona.name,
        mode=portfolio.mode.value,
        ts=latest_snapshot.ts,
        total_value=float(latest_snapshot.total_value),
        cash=float(latest_snapshot.cash),
        pnl_realized=float(latest_snapshot.pnl_realized),
        pnl_unrealized=float(latest_snapshot.pnl_unrealized),
        positions=[
            PositionOut(
                instrument=p.instrument,
                qty=float(p.qty),
                avg_price=float(p.avg_price),
                market_value=float(p.market_value),
                pnl_unrealized=float(p.pnl_unrealized),
            )
            for p in positions
        ],
    )


@router.get("/personas/{name}/profile", response_model=PersonaProfileOut)
def get_persona_profile_route(
    name: str, session: Session = Depends(get_session)
) -> PersonaProfileOut:
    persona = session.scalar(select(Persona).where(Persona.name == name.upper()))
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {name!r}")

    profile = get_persona_profile(persona.name)
    return PersonaProfileOut(
        name=profile.name,
        display_name=profile.display_name,
        philosophy=profile.philosophy,
        universe=profile.universe,
        signals=profile.signals,
        holding_period=profile.holding_period,
        failure_mode=profile.failure_mode,
    )


@router.get("/personas/{name}/holdings", response_model=list[HoldingOut])
def get_persona_holdings(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> list[HoldingOut]:
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    latest_snapshot = session.scalar(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    if latest_snapshot is None:
        return []

    positions = session.scalars(
        select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.ts == latest_snapshot.ts,
        )
    ).all()

    # Best-effort "when was this instrument last bought" — the most recent filled
    # BUY order per instrument. Positions are broker/ledger-computed averages, not
    # FIFO lots, so this is a reference date, not a per-lot purchase history.
    last_buy_rows = session.execute(
        select(Decision.instrument, func.max(OrderRecord.filled_at))
        .join(OrderRecord, OrderRecord.decision_id == Decision.id)
        .where(
            Decision.portfolio_id == portfolio.id,
            Decision.action == DecisionAction.BUY,
            OrderRecord.filled_at.isnot(None),
        )
        .group_by(Decision.instrument)
    ).all()
    last_buys: dict[str, datetime.datetime | None] = {
        instrument: filled_at for instrument, filled_at in last_buy_rows
    }

    holdings = []
    for p in positions:
        qty = float(p.qty)
        avg_price = float(p.avg_price)
        market_value = float(p.market_value)
        pnl_unrealized = float(p.pnl_unrealized)
        cost_basis = avg_price * qty
        holdings.append(
            HoldingOut(
                instrument=p.instrument,
                qty=qty,
                avg_price=avg_price,
                current_price=market_value / qty if qty else avg_price,
                market_value=market_value,
                pnl_unrealized=pnl_unrealized,
                pnl_unrealized_pct=(pnl_unrealized / cost_basis * 100) if cost_basis else 0.0,
                last_buy_at=last_buys.get(p.instrument),
            )
        )
    return holdings


@router.get("/personas/{name}/transactions", response_model=list[TransactionOut])
def get_persona_transactions(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> list[TransactionOut]:
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    rows = session.execute(
        select(OrderRecord, Decision)
        .join(Decision, OrderRecord.decision_id == Decision.id)
        .where(Decision.portfolio_id == portfolio.id)
        .order_by(OrderRecord.submitted_at.desc())
    ).all()

    return [
        TransactionOut(
            decision_id=decision.id,
            instrument=decision.instrument,
            action=decision.action.value,
            quantity=float(decision.quantity) if decision.quantity is not None else None,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
            fill_price=float(order.fill_price) if order.fill_price is not None else None,
            status=order.status.value,
            thesis_text=decision.thesis_text,
        )
        for order, decision in rows
    ]


@router.get("/personas/{name}/decisions", response_model=list[DecisionOut])
def get_persona_decisions(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    limit: int = _DEFAULT_DECISION_LIMIT,
    session: Session = Depends(get_session),
) -> list[DecisionOut]:
    """The "processed impulses" view: every decision (buy/hold/reject_idea, any
    status) with the research items it actually cited, each tagged with the same
    age-at-decision-time signal the persona itself saw (F033)."""
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    rows = session.execute(
        select(Decision, Cycle)
        .join(Cycle, Decision.cycle_id == Cycle.id)
        .where(Decision.portfolio_id == portfolio.id)
        .order_by(Cycle.started_at.desc())
        .limit(limit)
    ).all()

    out = []
    for decision, cycle in rows:
        research_items = session.scalars(
            select(ResearchItem)
            .where(ResearchItem.id.in_(decision.input_research_ids))
            .order_by(ResearchItem.published_at.desc())
        ).all()
        out.append(
            DecisionOut(
                id=decision.id,
                ts=cycle.started_at,
                instrument=decision.instrument,
                action=decision.action.value,
                status=decision.status.value,
                conviction=decision.expected_outcome.get("conviction"),
                thesis_text=decision.thesis_text,
                rejection_reason=decision.rejection_reason,
                research_items=[
                    ResearchRefOut(
                        id=item.id,
                        source_type=item.source_type,
                        summary=item.summary,
                        published_at=item.published_at,
                        age_days=compute_age_days(item.published_at, cycle.started_at),
                        url=item.url,
                    )
                    for item in research_items
                ],
            )
        )
    return out
