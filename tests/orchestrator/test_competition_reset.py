"""F090 competition reset — see docs/features/F090-competition-reset-and-start.md §6.

Uses the rolled-back `session` fixture (tests/conftest.py): reset_competition does
not commit (the caller owns the transaction), so unlike retry_stuck_decisions these
tests get full isolation and can't archive another test's portfolios. The internal
ledger is redirected to a tmp dir so no real data/ledger file is touched.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.routes import _get_persona_and_portfolio
from src.broker.ledger_store import JSONLedgerStore, LedgerState, PositionState
from src.broker.protocol import OrderSide
from src.db.models import Persona, Portfolio, PortfolioMode, PortfolioSnapshot
from src.orchestrator.competition_reset import (
    CompetitionAlreadyResetError,
    reset_competition,
)
from src.orchestrator.graph import list_active_portfolios
from src.orchestrator.seed import seed_personas_and_portfolios

_START_DATE = datetime.date(2026, 8, 3)
_ARCHIVE_TS = datetime.datetime.combine(_START_DATE, datetime.time.min)


def _new_native_ids() -> dict[str, str]:
    return {"VULTURE": "NEW-PA-V", "GUARDIAN": "NEW-PA-G", "CHARTIST": "NEW-PA-C"}


def _reset(session: Session, store: JSONLedgerStore):
    result = reset_competition(
        session,
        store,
        start_date=_START_DATE,
        start_capital_usd=5000,
        native_account_ids=_new_native_ids(),
    )
    session.flush()
    return result


def test_migration_leaves_existing_portfolios_active(session: Session) -> None:
    """F090 test 1: the additive archived_at column defaults to NULL — every
    seeded portfolio starts active."""
    seed_personas_and_portfolios(session)
    session.flush()
    portfolios = list(session.scalars(select(Portfolio)).all())
    assert len(portfolios) == 6
    assert all(p.archived_at is None for p in portfolios)


def test_reset_archives_preseason_and_creates_fresh(session: Session, tmp_path) -> None:
    """F090 test 2: the 6 old portfolios are archived (not deleted) and 6 fresh
    5000-USD ones created; pre-season snapshots stay reachable via the archived id."""
    seed_personas_and_portfolios(session)
    session.flush()
    old_ids = {p.id for p in session.scalars(select(Portfolio)).all()}

    a_portfolio = next(iter(session.scalars(select(Portfolio)).all()))
    snapshot = PortfolioSnapshot(
        ts=datetime.datetime(2026, 7, 20, 12, 0),
        portfolio_id=a_portfolio.id,
        total_value=Decimal("5123.45"),
        cash=Decimal("1000.00"),
        pnl_realized=Decimal("0"),
        pnl_unrealized=Decimal("123.45"),
        max_drawdown=Decimal("0.0100"),
    )
    session.add(snapshot)
    session.flush()

    result = _reset(session, JSONLedgerStore(base_dir=tmp_path))

    assert result.archived_count == 6
    assert result.created_count == 6
    archived = list(
        session.scalars(select(Portfolio).where(Portfolio.archived_at.is_not(None))).all()
    )
    active = list(session.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None))).all())
    assert {p.id for p in archived} == old_ids  # old rows archived, not deleted
    assert all(p.archived_at == _ARCHIVE_TS for p in archived)
    assert len(active) == 6
    assert all(p.start_value == 5000 for p in active)
    # Pre-season snapshot survives and still points at the (now archived) portfolio.
    kept = session.get(PortfolioSnapshot, snapshot.id)
    assert kept is not None
    assert kept.portfolio_id in old_ids


def test_list_active_portfolios_returns_only_fresh_after_reset(session: Session, tmp_path) -> None:
    """F090 test 3: the orchestrator fan-out sees the 6 fresh portfolios, not 12."""
    seed_personas_and_portfolios(session)
    session.flush()
    _reset(session, JSONLedgerStore(base_dir=tmp_path))

    active = list_active_portfolios(session)
    assert len(active) == 6
    assert all(portfolio.archived_at is None for portfolio, _name in active)


def test_api_selection_returns_active_not_archived(session: Session, tmp_path) -> None:
    """F090 test 4: the API resolves each persona to its active portfolio, never the
    archived one, and stays single-valued."""
    seed_personas_and_portfolios(session)
    session.flush()
    _reset(session, JSONLedgerStore(base_dir=tmp_path))

    _persona, portfolio = _get_persona_and_portfolio(session, "VULTURE", PortfolioMode.PAPER)
    assert portfolio.archived_at is None
    assert portfolio.broker_account_ref == "NEW-PA-V"


def test_ledger_reset_for_virtual_personas(session: Session, tmp_path) -> None:
    """F090 test 5: the 3 internal-ledger personas are reset to 5000 flat."""
    seed_personas_and_portfolios(session)
    session.flush()
    store = JSONLedgerStore(base_dir=tmp_path)
    # Pre-season ledger state that must be wiped.
    store.save(
        "HYPE",
        LedgerState(
            cash=1234.0,
            positions={"AAPL": PositionState(qty=5.0, side=OrderSide.BUY, avg_entry_price=100.0)},
        ),
    )

    result = _reset(session, store)

    assert set(result.ledger_reset_personas) == {"HYPE", "CONTRA", "CRYPTOR"}
    hype = store.load("HYPE", default_cash=999.0)
    assert hype.cash == 5000.0
    assert hype.positions == {}


def test_second_reset_same_start_date_refuses(session: Session, tmp_path) -> None:
    """F090 test 6: idempotency guard — a re-run for the same start_date refuses
    instead of archiving the freshly created portfolios."""
    seed_personas_and_portfolios(session)
    session.flush()
    store = JSONLedgerStore(base_dir=tmp_path)
    _reset(session, store)

    with pytest.raises(CompetitionAlreadyResetError):
        reset_competition(
            session,
            store,
            start_date=_START_DATE,
            start_capital_usd=5000,
            native_account_ids=_new_native_ids(),
        )


def test_reset_is_fair_5000_and_charters_unchanged(session: Session, tmp_path) -> None:
    """F090 test 7: all 6 fresh portfolios start at 5000; no silent charter bump."""
    seed_personas_and_portfolios(session)
    session.flush()
    charters_before = {p.name: p.charter_version for p in session.scalars(select(Persona)).all()}

    _reset(session, JSONLedgerStore(base_dir=tmp_path))

    active = list(session.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None))).all())
    assert len(active) == 6
    assert all(p.start_value == 5000 for p in active)
    charters_after = {p.name: p.charter_version for p in session.scalars(select(Persona)).all()}
    assert charters_after == charters_before
