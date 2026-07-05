"""Portfolio-snapshot endpoint. Reads portfolio_snapshot + position_snapshot for the
persona's most recent snapshot timestamp — no other tables, no LLM, no broker access.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import PortfolioSnapshotOut, PositionOut
from src.db.base import get_session_factory
from src.db.models import Persona, Portfolio, PortfolioSnapshot, PositionSnapshot

router = APIRouter(prefix="/api")

_session_factory = get_session_factory()


def get_session() -> Generator[Session]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/personas/{name}/snapshot", response_model=PortfolioSnapshotOut)
def get_persona_snapshot(
    name: str, session: Session = Depends(get_session)
) -> PortfolioSnapshotOut:
    persona = session.scalar(select(Persona).where(Persona.name == name.upper()))
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {name!r}")

    portfolio = session.scalar(select(Portfolio).where(Portfolio.persona_id == persona.id))
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"No portfolio for persona: {name!r}")

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
