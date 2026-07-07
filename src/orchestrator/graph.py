"""LangGraph orchestrator skeleton — see docs/features/F016-orchestrator-graph-skeleton.md.

Two layers, same pattern as the F008-F015 ingestion modules: pure, unit-testable
helper functions that take a `Session` directly (`.flush()` only, no `.commit()`),
and thin LangGraph node closures that open their own session per call (required for
thread-safety under `Send`-based parallel fanout — see F016 §2), commit, and close.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    AgentRunStatus,
    Cycle,
    MarketSession,
    Persona,
    Portfolio,
    ResearchItem,
)

_BOOTSTRAP_RESEARCH_SUMMARY = (
    "Platzhalter-Recherche-Item (F016-Orchestrator-Grundgerüst): die echte "
    "Recherche-Synthese aus den Ingestion-Tabellen (F008-F014) ist noch nicht "
    "implementiert. Dieses Item existiert, damit spätere Decisions bereits jetzt "
    "eine valide input_research_ids-Referenz haben."
)


class CycleState(TypedDict):
    trading_day: str  # ISO date — state must stay JSON-serializable for the checkpointer
    seq: int
    market_session: str
    cycle_id: str | None
    research_item_id: str | None


class PersonaTaskState(TypedDict):
    cycle_id: str
    portfolio_id: str
    persona_name: str


def create_cycle(
    session: Session, trading_day: datetime.date, seq: int, market_session: MarketSession
) -> Cycle:
    cycle = Cycle(
        trading_day=trading_day,
        seq=seq,
        started_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        market_session=market_session,
    )
    session.add(cycle)
    session.flush()
    return cycle


def create_bootstrap_research_item(session: Session, cycle_id: uuid.UUID) -> ResearchItem:
    item = ResearchItem(
        cycle_id=cycle_id,
        agent="orchestrator_bootstrap",
        source_type="placeholder",
        source_ref="f016-skeleton",
        summary=_BOOTSTRAP_RESEARCH_SUMMARY,
        instruments=[],
        raw={},
    )
    session.add(item)
    session.flush()
    return item


def create_persona_agent_run_placeholder(
    session: Session, cycle_id: uuid.UUID, portfolio_id: uuid.UUID
) -> AgentRun:
    run = AgentRun(
        cycle_id=cycle_id,
        portfolio_id=portfolio_id,
        agent="persona_analysis_placeholder",
        status=AgentRunStatus.SUCCEEDED,
    )
    session.add(run)
    session.flush()
    return run


def list_active_portfolios(session: Session) -> list[tuple[Portfolio, str]]:
    """Returns (portfolio, persona_name) pairs — models.py uses plain FK columns, no
    ORM relationships, so the persona name comes from an explicit join, not attribute
    access."""
    stmt = (
        select(Portfolio, Persona.name)
        .join(Persona, Portfolio.persona_id == Persona.id)
        .where(Persona.active.is_(True))
    )
    return [(portfolio, name) for portfolio, name in session.execute(stmt).all()]


def build_and_compile_graph(
    session_factory: Callable[[], Session],
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CompiledStateGraph[CycleState, None, CycleState, CycleState]:
    def _start_cycle_node(state: CycleState) -> dict[str, object]:
        with session_factory() as session:
            cycle = create_cycle(
                session,
                datetime.date.fromisoformat(state["trading_day"]),
                state["seq"],
                MarketSession(state["market_session"]),
            )
            session.commit()
            return {"cycle_id": str(cycle.id)}

    def _shared_research_node(state: CycleState) -> dict[str, object]:
        assert state["cycle_id"] is not None
        with session_factory() as session:
            item = create_bootstrap_research_item(session, uuid.UUID(state["cycle_id"]))
            session.commit()
            return {"research_item_id": str(item.id)}

    def _fanout_to_personas(state: CycleState) -> list[Send]:
        assert state["cycle_id"] is not None
        with session_factory() as session:
            portfolios = list_active_portfolios(session)
            return [
                Send(
                    "persona_placeholder",
                    PersonaTaskState(
                        cycle_id=state["cycle_id"],
                        portfolio_id=str(portfolio.id),
                        persona_name=persona_name,
                    ),
                )
                for portfolio, persona_name in portfolios
            ]

    def _persona_placeholder_node(state: PersonaTaskState) -> dict[str, object]:
        with session_factory() as session:
            create_persona_agent_run_placeholder(
                session, uuid.UUID(state["cycle_id"]), uuid.UUID(state["portfolio_id"])
            )
            session.commit()
            return {}

    builder = StateGraph(CycleState)
    builder.add_node("start_cycle", _start_cycle_node)
    builder.add_node("shared_research", _shared_research_node)
    builder.add_node("persona_placeholder", _persona_placeholder_node)

    builder.add_edge(START, "start_cycle")
    builder.add_edge("start_cycle", "shared_research")
    builder.add_conditional_edges("shared_research", _fanout_to_personas, ["persona_placeholder"])
    builder.add_edge("persona_placeholder", END)

    return builder.compile(checkpointer=checkpointer)
