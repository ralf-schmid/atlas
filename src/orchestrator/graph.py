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

from src.broker.registry import get_adapter
from src.db.models import Cycle, MarketSession, Persona, Portfolio
from src.llm.client import LiteLLMClient
from src.llm.config import LlmConfig
from src.orchestrator.persona_analysis import analyze_persona_cycle
from src.orchestrator.research_synthesis import synthesize_research_items


class CycleState(TypedDict):
    trading_day: str  # ISO date — state must stay JSON-serializable for the checkpointer
    seq: int
    market_session: str
    cycle_id: str | None
    research_item_ids: list[str]


class PersonaTaskState(TypedDict):
    cycle_id: str
    portfolio_id: str
    persona_id: str
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
    llm_client: LiteLLMClient,
    llm_config: LlmConfig,
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
            cycle = session.get_one(Cycle, uuid.UUID(state["cycle_id"]))
            items = synthesize_research_items(session, cycle)
            session.commit()
            return {"research_item_ids": [str(item.id) for item in items]}

    def _fanout_to_personas(state: CycleState) -> list[Send]:
        assert state["cycle_id"] is not None
        with session_factory() as session:
            portfolios = list_active_portfolios(session)
            return [
                Send(
                    "persona_analysis",
                    PersonaTaskState(
                        cycle_id=state["cycle_id"],
                        portfolio_id=str(portfolio.id),
                        persona_id=str(portfolio.persona_id),
                        persona_name=persona_name,
                    ),
                )
                for portfolio, persona_name in portfolios
            ]

    def _persona_analysis_node(state: PersonaTaskState) -> dict[str, object]:
        with session_factory() as session:
            broker_adapter = get_adapter(state["persona_name"])
            analyze_persona_cycle(
                session,
                llm_client,
                llm_config,
                uuid.UUID(state["cycle_id"]),
                uuid.UUID(state["portfolio_id"]),
                uuid.UUID(state["persona_id"]),
                state["persona_name"],
                broker_adapter,
            )
            session.commit()
            return {}

    builder = StateGraph(CycleState)
    builder.add_node("start_cycle", _start_cycle_node)
    builder.add_node("shared_research", _shared_research_node)
    builder.add_node("persona_analysis", _persona_analysis_node)

    builder.add_edge(START, "start_cycle")
    builder.add_edge("start_cycle", "shared_research")
    builder.add_conditional_edges("shared_research", _fanout_to_personas, ["persona_analysis"])
    builder.add_edge("persona_analysis", END)

    return builder.compile(checkpointer=checkpointer)
