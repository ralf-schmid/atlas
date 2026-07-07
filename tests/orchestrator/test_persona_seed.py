"""See docs/features/F015-persona-portfolio-seed.md §3."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Persona, Portfolio, PortfolioMode
from src.orchestrator.seed import seed_personas_and_portfolios

_EXPECTED_NAMES = {"VULTURE", "HYPE", "GUARDIAN", "CHARTIST", "CONTRA", "CRYPTOR"}
_NATIVE_ACCOUNT_IDS = {
    "VULTURE": "PA32N1PG3J5G",
    "GUARDIAN": "PA3NCUB9NOCJ",
    "CHARTIST": "PA3SLPCA9U5V",
}


def test_seed_creates_all_six_personas_and_portfolios(session: Session) -> None:
    count = seed_personas_and_portfolios(session)

    assert count == 6
    personas = session.scalars(select(Persona)).all()
    portfolios = session.scalars(select(Portfolio)).all()
    assert {p.name for p in personas} == _EXPECTED_NAMES
    assert len(portfolios) == 6


def test_seed_portfolios_are_paper_mode_with_start_value(session: Session) -> None:
    seed_personas_and_portfolios(session)

    for portfolio in session.scalars(select(Portfolio)).all():
        assert portfolio.mode == PortfolioMode.PAPER
        assert portfolio.start_value == Decimal("5000")


def test_seed_native_personas_get_real_alpaca_account_ids(session: Session) -> None:
    seed_personas_and_portfolios(session)

    for name, account_id in _NATIVE_ACCOUNT_IDS.items():
        persona = session.scalar(select(Persona).filter_by(name=name))
        assert persona is not None
        portfolio = session.scalar(select(Portfolio).filter_by(persona_id=persona.id))
        assert portfolio is not None
        assert portfolio.broker_account_ref == account_id


def test_seed_virtual_personas_get_internal_ledger_marker(session: Session) -> None:
    seed_personas_and_portfolios(session)

    for name in ("HYPE", "CONTRA", "CRYPTOR"):
        persona = session.scalar(select(Persona).filter_by(name=name))
        assert persona is not None
        portfolio = session.scalar(select(Portfolio).filter_by(persona_id=persona.id))
        assert portfolio is not None
        assert portfolio.broker_account_ref == "internal_ledger"


def test_seed_is_idempotent_on_rerun(session: Session) -> None:
    seed_personas_and_portfolios(session)
    count = seed_personas_and_portfolios(session)

    assert count == 6
    assert len(session.scalars(select(Persona)).all()) == 6
    assert len(session.scalars(select(Portfolio)).all()) == 6


def test_seed_rerun_updates_changed_charter_version(session: Session, monkeypatch) -> None:
    seed_personas_and_portfolios(session)

    import src.orchestrator.seed as seed_module

    original_loader = seed_module.yaml.safe_load

    def patched_load(text: str) -> dict[str, object]:
        data = original_loader(text)
        if isinstance(data, dict) and data.get("name") == "VULTURE":
            data["charter_version"] = 2
        return data

    monkeypatch.setattr(seed_module.yaml, "safe_load", lambda text: patched_load(text))

    seed_personas_and_portfolios(session)

    vulture = session.scalar(select(Persona).filter_by(name="VULTURE"))
    assert vulture is not None
    assert vulture.charter_version == 2
    assert len(session.scalars(select(Persona)).all()) == 6
