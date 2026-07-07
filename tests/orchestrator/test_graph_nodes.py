"""See docs/features/F016-orchestrator-graph-skeleton.md §3, tests 1-5."""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import MarketSession, Persona
from src.orchestrator.graph import create_cycle, list_active_portfolios
from src.orchestrator.seed import seed_personas_and_portfolios


def test_create_cycle_persists_fields(session: Session) -> None:
    cycle = create_cycle(session, datetime.date(2026, 7, 7), 2, MarketSession.US_EQUITY)

    assert cycle.id is not None
    assert cycle.trading_day == datetime.date(2026, 7, 7)
    assert cycle.seq == 2
    assert cycle.market_session == MarketSession.US_EQUITY


def test_list_active_portfolios_returns_all_six_after_seed(session: Session) -> None:
    seed_personas_and_portfolios(session)

    portfolios = list_active_portfolios(session)

    assert len(portfolios) == 6
    assert {name for _portfolio, name in portfolios} == {
        "VULTURE",
        "HYPE",
        "GUARDIAN",
        "CHARTIST",
        "CONTRA",
        "CRYPTOR",
    }


def test_list_active_portfolios_excludes_inactive_persona(session: Session) -> None:
    seed_personas_and_portfolios(session)
    vulture = session.scalar(select(Persona).filter_by(name="VULTURE"))
    assert vulture is not None
    vulture.active = False
    session.flush()

    portfolios = list_active_portfolios(session)

    assert len(portfolios) == 5
    assert "VULTURE" not in {name for _portfolio, name in portfolios}
