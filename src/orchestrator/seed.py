"""Seeds the 6 persona/portfolio rows the LangGraph orchestrator (F016+) fans out
over. See docs/features/F015-persona-portfolio-seed.md.

Native account IDs are the 3 real Alpaca paper accounts from
docs/adr/0001-alpaca-paper-account-limit.md §"Ergebnis" (VULTURE/GUARDIAN/CHARTIST).
Fixed here as a constant, not a config file — exactly 3 values, decided once via ADR,
no runtime configurability needed. The 3 virtual personas (HYPE/CONTRA/CRYPTOR) use
the internal ledger adapter (config/broker.yaml) and get the marker string
"internal_ledger" instead of a real broker account id.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import Persona, Portfolio, PortfolioMode

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PERSONAS_DIR = _REPO_ROOT / "config" / "personas"
_BROKER_CONFIG_PATH = _REPO_ROOT / "config" / "broker.yaml"

_NATIVE_ACCOUNT_IDS: dict[str, str] = {
    "VULTURE": "PA32N1PG3J5G",
    "GUARDIAN": "PA3NCUB9NOCJ",
    "CHARTIST": "PA3SLPCA9U5V",
}
_INTERNAL_LEDGER_MARKER = "internal_ledger"
_START_VALUE_USD = 5000
_BASE_CCY = "USD"


def seed_personas_and_portfolios(session: Session) -> int:
    """Idempotent: safe to re-run (e.g. after a persona YAML charter_version bump)."""
    broker_config = yaml.safe_load(_BROKER_CONFIG_PATH.read_text())
    persona_names: list[str] = list(broker_config["personas"].keys())

    count = 0
    for name in persona_names:
        persona_yaml = yaml.safe_load((_PERSONAS_DIR / f"{name.lower()}.yaml").read_text())
        persona = _upsert_persona(session, name, persona_yaml)
        _get_or_create_portfolio(session, persona, name)
        count += 1

    session.flush()
    return count


def _upsert_persona(session: Session, name: str, persona_yaml: dict[str, object]) -> Persona:
    insert_stmt = insert(Persona).values(
        name=name,
        charter_version=persona_yaml["charter_version"],
        model=persona_yaml["model"],
        config_ref=f"config/personas/{name.lower()}.yaml",
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={
            "charter_version": insert_stmt.excluded.charter_version,
            "model": insert_stmt.excluded.model,
            "config_ref": insert_stmt.excluded.config_ref,
        },
    ).returning(Persona.id)
    persona_id = session.execute(upsert_stmt).scalar_one()
    session.flush()
    return session.get(Persona, persona_id)  # type: ignore[return-value]


def _get_or_create_portfolio(session: Session, persona: Persona, name: str) -> Portfolio:
    existing = session.query(Portfolio).filter_by(persona_id=persona.id).one_or_none()
    if existing is not None:
        return existing

    broker_account_ref = _NATIVE_ACCOUNT_IDS.get(name, _INTERNAL_LEDGER_MARKER)
    portfolio = Portfolio(
        persona_id=persona.id,
        mode=PortfolioMode.PAPER,
        broker_account_ref=broker_account_ref,
        base_ccy=_BASE_CCY,
        start_value=_START_VALUE_USD,
    )
    session.add(portfolio)
    session.flush()
    return portfolio
