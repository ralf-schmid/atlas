"""Full compiled-graph run — see docs/features/F016-orchestrator-graph-skeleton.md §3
test 6. Marked integration: exercises real `Send`-based fanout end-to-end against a
real (local) Postgres via `get_session_factory()` — each node opens its own,
independently-committed session (see F016 §2, thread-safety), so this can't run
inside the standard rolled-back `session` fixture like tests/orchestrator/
test_graph_nodes.py. `max_concurrency=1` keeps the run deterministic for assertions;
production concurrency is unaffected (each node already uses its own session).
"""

from __future__ import annotations

import datetime
import os

import pytest
from sqlalchemy import select

from src.db.base import get_session_factory
from src.db.models import AgentRun, Cycle, MarketSession, ResearchItem
from src.orchestrator.graph import CycleState, build_and_compile_graph, list_active_portfolios
from src.orchestrator.seed import seed_personas_and_portfolios

pytestmark = pytest.mark.integration


def test_full_cycle_run_fans_out_to_all_six_portfolios() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — needs a real local Postgres, see F016 §5")

    session_factory = get_session_factory()
    with session_factory() as seed_session:
        seed_personas_and_portfolios(seed_session)
        seed_session.commit()

    graph = build_and_compile_graph(session_factory)
    trading_day = datetime.date.today()
    initial_state = CycleState(
        trading_day=trading_day.isoformat(),
        seq=1,
        market_session=MarketSession.US_EQUITY.value,
        cycle_id=None,
        research_item_id=None,
    )

    final_state = graph.invoke(initial_state, config={"max_concurrency": 1})

    with session_factory() as session:
        cycle_id = final_state["cycle_id"]
        assert cycle_id is not None
        cycles = session.scalars(
            select(Cycle).where(Cycle.trading_day == trading_day, Cycle.seq == 1)
        ).all()
        assert len(cycles) == 1

        research_items = session.scalars(
            select(ResearchItem).where(ResearchItem.cycle_id == cycle_id)
        ).all()
        assert len(research_items) == 1
        assert research_items[0].agent == "orchestrator_bootstrap"

        agent_runs = session.scalars(select(AgentRun).where(AgentRun.cycle_id == cycle_id)).all()
        expected_portfolio_ids = {str(p.id) for p, _name in list_active_portfolios(session)}
        assert len(agent_runs) == 6
        assert {str(run.portfolio_id) for run in agent_runs} == expected_portfolio_ids
