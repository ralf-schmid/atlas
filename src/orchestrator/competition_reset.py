"""F090 competition reset — archive the pre-season portfolios and create fresh
5000-USD ones for the official 8-week competition (see
docs/features/F090-competition-reset-and-start.md).

Pure DB + ledger work, no LLM. Deterministic and idempotency-guarded: archiving
uses a timestamp derived from the competition start_date, so a second run for the
same start_date refuses instead of double-archiving.

The Alpaca side (deleting/creating paper accounts, rotating keys) is Ralf's manual
task (ADR-0009) — this only touches our DB and the internal ledger. It must run
AFTER the new .env keys are in place, so the 3 native personas' fresh portfolios
point at the new 5000-USD accounts.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.broker.ledger_store import LedgerState, LedgerStore
from src.db.models import Persona, Portfolio, PortfolioMode

_INTERNAL_LEDGER_MARKER = "internal_ledger"
_BASE_CCY = "USD"


class CompetitionAlreadyResetError(RuntimeError):
    """Raised when a reset for the given start_date has already run (idempotency
    guard) — refusing to archive the freshly created competition portfolios."""


@dataclass(frozen=True, slots=True)
class CompetitionResetResult:
    archived_count: int
    created_count: int
    ledger_reset_personas: list[str]


def reset_competition(
    session: Session,
    ledger_store: LedgerStore,
    *,
    start_date: datetime.date,
    start_capital_usd: int,
    native_account_ids: dict[str, str],
) -> CompetitionResetResult:
    """Archive every active-season portfolio and create a fresh one per persona at
    `start_capital_usd`, flat. `native_account_ids` maps persona name -> the new
    Alpaca paper account id for the 3 native personas; any persona not in the map
    is an internal-ledger persona and gets its JSON ledger reset to
    `start_capital_usd`.

    Does not commit — the caller owns the transaction. The ledger reset (a
    filesystem write, outside the DB transaction) is idempotent (cash=start,
    positions cleared), so a rollback after it is safe to retry.
    """
    # Deterministic archive marker: midnight of the competition start_date. Makes
    # the idempotency guard exact — a re-run for the same start_date sees rows
    # already archived at this timestamp and refuses.
    archive_ts = datetime.datetime.combine(start_date, datetime.time.min)

    already_archived = session.scalar(
        select(func.count()).select_from(Portfolio).where(Portfolio.archived_at == archive_ts)
    )
    if already_archived:
        raise CompetitionAlreadyResetError(
            f"{already_archived} portfolio(s) already archived at {archive_ts.isoformat()} — "
            f"the competition reset for start_date {start_date.isoformat()} has already run"
        )

    active_portfolios = list(
        session.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None))).all()
    )
    for portfolio in active_portfolios:
        portfolio.archived_at = archive_ts

    personas = list(session.scalars(select(Persona)).all())
    ledger_reset_personas: list[str] = []
    for persona in personas:
        broker_account_ref = native_account_ids.get(persona.name, _INTERNAL_LEDGER_MARKER)
        session.add(
            Portfolio(
                persona_id=persona.id,
                mode=PortfolioMode.PAPER,
                broker_account_ref=broker_account_ref,
                base_ccy=_BASE_CCY,
                start_value=start_capital_usd,
                archived_at=None,
            )
        )
        if broker_account_ref == _INTERNAL_LEDGER_MARKER:
            # Fresh ledger: cash back to start, no positions / stops / executed
            # decisions carried over from the pre-season.
            ledger_store.save(persona.name, LedgerState(cash=float(start_capital_usd)))
            ledger_reset_personas.append(persona.name)

    session.flush()
    return CompetitionResetResult(
        archived_count=len(active_portfolios),
        created_count=len(personas),
        ledger_reset_personas=ledger_reset_personas,
    )
