"""Closing valuation on the competition's last day (F121).

Ralf's ruling (16.08.2026, docs/dod/phase-5.md §4): positions still open at the
end of the 8 weeks are **valued at that day's closing price**, not force-liquidated.
Nothing in the system did that yet — `portfolio_snapshot` rows are only written by
the cycles, and the last stock cycle of a day is C4 at 15:15 ET, 45 minutes *before*
the close. So the final standing would have been read off a mid-afternoon
valuation.

This module writes one extra snapshot per portfolio after the close of the last
competition day. It changes nothing about how the personas trade — the paper field
keeps running afterwards (ARCHITECTURE.md §4.7); this only fixes the number the
final report is read from.
"""

from __future__ import annotations

import datetime
import logging
import uuid
import zoneinfo
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter
from src.db.models import Persona, Portfolio, PortfolioMode, PortfolioSnapshot
from src.orchestrator.competition_config import CompetitionConfig, load_competition_config
from src.orchestrator.reporting import generate_portfolio_snapshot

logger = logging.getLogger(__name__)

_MARKET_TIMEZONE = "America/New_York"
_MARKET_CLOSE = datetime.time(16, 0)


@dataclass(frozen=True, slots=True)
class SettlementResult:
    settled_at: datetime.datetime
    personas: list[str]
    failed: list[str]


def market_close_utc(day: datetime.date) -> datetime.datetime:
    """16:00 ET on *day* as a naive UTC timestamp — the convention every `ts`
    column uses. Via zoneinfo rather than a fixed offset: the competition ends in
    September (EDT, UTC-4), but nothing here should silently be wrong if a future
    season ends after the DST switch."""
    local = datetime.datetime.combine(day, _MARKET_CLOSE, zoneinfo.ZoneInfo(_MARKET_TIMEZONE))
    return local.astimezone(datetime.UTC).replace(tzinfo=None)


def is_settlement_due(now: datetime.datetime, config: CompetitionConfig) -> bool:
    """True from the close of the last competition day onwards, on that day."""
    if config.end_date is None:
        return False
    return now.date() == config.end_date and now >= market_close_utc(config.end_date)


def run_final_settlement(
    session: Session,
    adapter_factory: Callable[[str], BrokerAdapter],
    now: datetime.datetime,
    mode: PortfolioMode = PortfolioMode.PAPER,
) -> SettlementResult:
    """One post-close `portfolio_snapshot` (plus its position rows) per active
    portfolio. Idempotent by consequence rather than by lock: the report always
    reads the *last* snapshot before the cutoff, so a second run just writes a
    second, equally valid closing valuation.

    A single failing portfolio is logged and skipped instead of aborting the run —
    five settled portfolios plus a named gap is a better outcome than none. The
    isolation is a SAVEPOINT per portfolio rather than a commit per portfolio, so
    the caller keeps control over the transaction (and the tests don't need a
    separately committing session factory, see F121 §4).
    """
    rows = session.execute(
        select(Portfolio, Persona.name)
        .join(Persona, Portfolio.persona_id == Persona.id)
        .where(
            Persona.active.is_(True),
            Portfolio.mode == mode,
            Portfolio.archived_at.is_(None),
        )
        .order_by(Persona.name)
    ).all()

    settled: list[str] = []
    failed: list[str] = []
    for portfolio, persona_name in rows:
        try:
            with session.begin_nested():
                generate_portfolio_snapshot(
                    session, portfolio.id, adapter_factory(persona_name), now
                )
            settled.append(persona_name)
        except Exception:
            failed.append(persona_name)
            logger.error(
                "F121: closing valuation failed",
                exc_info=True,
                extra={"portfolio_id": str(portfolio.id), "persona": persona_name},
            )
    logger.info(
        "F121: competition settlement written",
        extra={"settled": settled, "failed": failed, "ts": now.isoformat()},
    )
    return SettlementResult(settled_at=now, personas=settled, failed=failed)


def settlement_snapshot_id(
    session: Session, portfolio_id: uuid.UUID, config: CompetitionConfig | None = None
) -> uuid.UUID | None:
    """The snapshot the final report will read for this portfolio — exposed so the
    settlement can be verified before the report is generated."""
    cutoff = (config or load_competition_config()).settlement_cutoff()
    return session.scalar(
        select(PortfolioSnapshot.id)
        .where(PortfolioSnapshot.portfolio_id == portfolio_id, PortfolioSnapshot.ts <= cutoff)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
