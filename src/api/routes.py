"""Portfolio-snapshot endpoint. Reads portfolio_snapshot + position_snapshot for the
persona's most recent snapshot timestamp — no other tables, no LLM, no broker access.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.api.schemas import PortfolioSnapshotOut, PositionOut
from src.db.base import get_session_factory
from src.db.models import Persona, Portfolio, PortfolioMode, PortfolioSnapshot, PositionSnapshot

router = APIRouter(prefix="/api")

# Lazy: building the engine at import time requires DATABASE_URL to be set just to
# import this module (breaks test collection and any tooling that imports the app).
_session_factory: sessionmaker[Session] | None = None


def get_session() -> Generator[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/personas/{name}/snapshot", response_model=PortfolioSnapshotOut)
def get_persona_snapshot(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> PortfolioSnapshotOut:
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
