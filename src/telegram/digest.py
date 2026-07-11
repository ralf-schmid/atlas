"""Daily digest — plain code over structured data, no LLM (ARCHITECTURE.md §6.4 Punkt 3)."""

from __future__ import annotations

import datetime
import locale
from dataclasses import dataclass

from jinja2 import Environment
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import (
    Decision,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
    PortfolioSnapshot,
    PositionSnapshot,
)
from src.llm.ledger import sum_persona_spend_today

# 1. Syntaxfehler behoben (Klammer zu)
locale.setlocale(locale.LC_ALL, "de_DE.UTF-8")

_TEMPLATE_SOURCE = """\
\U0001f4ca Tagesdigest {{ trading_day.strftime('%d.%m.%Y') }}

{% for p in personas -%}
{{ p.name }}: 
{{ p.trades_today }} Trades
Depotwert {{ format_currency(p.portfolio_value_usd) }}
Cash {{ format_currency(p.cash_usd) }}
{{ p.open_positions }} offene Positionen
LLM-Kosten {{ format_currency(p.llm_cost_usd) }}

{% endfor %}
Gesamt: {{ format_currency(total_portfolio_value_usd) }}
LLM-Kosten gesamt: {{ format_currency(total_llm_cost_usd) }}\
"""

_env = Environment(autoescape=False)
_template = _env.from_string(_TEMPLATE_SOURCE)


@dataclass(frozen=True, slots=True)
class PersonaDigest:
    name: str
    trades_today: int
    portfolio_value_usd: float
    cash_usd: float
    open_positions: int
    llm_cost_usd: float


@dataclass(frozen=True, slots=True)
class DigestData:
    trading_day: datetime.date
    personas: list[PersonaDigest]

    @property
    def total_portfolio_value_usd(self) -> float:
        return sum(p.portfolio_value_usd for p in self.personas)

    @property
    def total_llm_cost_usd(self) -> float:
        return sum(p.llm_cost_usd for p in self.personas)


def render_daily_digest(data: DigestData) -> str:
    def format_currency(val: float) -> str:
        return locale.currency(val, symbol=False, grouping=True).strip()

    return _template.render(
        trading_day=data.trading_day,
        personas=data.personas,
        total_portfolio_value_usd=data.total_portfolio_value_usd,
        total_llm_cost_usd=data.total_llm_cost_usd,
        format_currency=format_currency,
    )


def build_digest_data(session: Session, trading_day: datetime.date) -> DigestData:
    """Assembles one `DigestData` from `portfolio_snapshot`/`order_record`/
    `position_snapshot`/`cost_ledger` — the "Jinja-Template über Snapshot-Queries"
    ARCHITECTURE.md §6.4 Punkt 3 calls for, no LLM call. Only active personas
    (same `Persona.active` flag `/pause`/`/resume` and the cycle fan-out use), so a
    paused persona quietly drops out of the digest rather than showing stale
    numbers."""
    day_start = datetime.datetime.combine(trading_day, datetime.time.min)
    day_end = datetime.datetime.combine(trading_day, datetime.time.max)

    portfolios = session.execute(
        select(Portfolio, Persona.id, Persona.name)
        .join(Persona, Portfolio.persona_id == Persona.id)
        .where(Persona.active.is_(True))
        .order_by(Persona.name)
    ).all()

    personas = [
        PersonaDigest(
            name=persona_name,
            trades_today=_count_filled_trades_today(session, portfolio.id, day_start, day_end),
            portfolio_value_usd=float(_latest_snapshot_field(session, portfolio.id, "total_value")),
            cash_usd=float(_latest_snapshot_field(session, portfolio.id, "cash")),
            open_positions=_count_open_positions(session, portfolio.id),
            # Reuses the exact function the real cost-cap enforcement uses
            # (`src/llm/ledger.py::guarded_complete`) — same day-boundary
            # semantics as what actually gates further LLM calls, not a second,
            # independently-defined "today".
            llm_cost_usd=sum_persona_spend_today(session, persona_id, day_start),
        )
        for portfolio, persona_id, persona_name in portfolios
    ]
    return DigestData(trading_day=trading_day, personas=personas)


def _count_filled_trades_today(
    session: Session,
    portfolio_id: object,
    day_start: datetime.datetime,
    day_end: datetime.datetime,
) -> int:
    """ "Durchgeführte Trades" (ARCHITECTURE.md §6.4) = actually filled orders, not
    every order attempt — a rejected/canceled order isn't a trade that happened."""
    stmt = (
        select(func.count())
        .select_from(OrderRecord)
        .join(Decision, Decision.id == OrderRecord.decision_id)
        .where(
            Decision.portfolio_id == portfolio_id,
            OrderRecord.status == OrderRecordStatus.FILLED,
            OrderRecord.submitted_at >= day_start,
            OrderRecord.submitted_at <= day_end,
        )
    )
    return session.scalar(stmt) or 0


def _latest_snapshot_field(session: Session, portfolio_id: object, field: str) -> float:
    """Most recent `portfolio_snapshot` row regardless of exact date (not just
    today's) — a digest sent after a day with no fresh snapshot should still show
    the last known state, not silently zero it out."""
    stmt = (
        select(getattr(PortfolioSnapshot, field))
        .where(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    value = session.scalar(stmt)
    return float(value) if value is not None else 0.0


def _count_open_positions(session: Session, portfolio_id: object) -> int:
    latest_ts = session.scalar(
        select(func.max(PositionSnapshot.ts)).where(PositionSnapshot.portfolio_id == portfolio_id)
    )
    if latest_ts is None:
        return 0
    stmt = (
        select(func.count())
        .select_from(PositionSnapshot)
        .where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.ts == latest_ts,
            PositionSnapshot.qty != 0,
        )
    )
    return session.scalar(stmt) or 0
