"""Endabrechnung — the §4.7 report that decides the competition (F121).

Same five criteria, same weights and the same code path as the weekly standings
(`collect_persona_criteria`); the two differences are what make it a *final*
report:

* **The window is closed on both ends.** [start_date, end_date] instead of
  "since the start, up to now" — the paper field keeps trading after the last
  competition day (ARCHITECTURE.md §4.7), so an open-ended report re-run in
  October would decide a different season than the one that ended.
* **The valuation is the closing one.** Positions still open on the last day are
  valued at that day's close (Ralf, 16.08.2026) — the closing snapshot written by
  `src/orchestrator/competition_settlement.py`. The report says out loud when that
  snapshot is missing rather than quietly reporting a 15:15 ET valuation as the
  final one.

No LLM anywhere in this path: the winner falls out of arithmetic over
`portfolio_snapshot`, `order_record`, `review` and `agent_run`.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

from jinja2 import Environment
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import PortfolioMode, PortfolioSnapshot, PositionSnapshot
from src.metrics.competition_score import (
    CRITERION_LABELS,
    CRITERION_WEIGHTS,
    CompetitionScore,
    ScoredPersona,
    collect_persona_criteria,
    score_personas,
)
from src.metrics.performance import daily_benchmark_values, simple_return
from src.orchestrator.competition_config import CompetitionConfig, load_competition_config
from src.orchestrator.competition_settlement import market_close_utc


@dataclass(frozen=True, slots=True)
class ClosingPosition:
    instrument: str
    qty: Decimal
    market_value: Decimal
    pnl_unrealized: Decimal


@dataclass(frozen=True, slots=True)
class PersonaSettlement:
    """What the portfolio was worth when the competition ended."""

    persona: str
    portfolio_id: uuid.UUID
    snapshot_ts: datetime.datetime | None
    total_value: Decimal | None
    cash: Decimal | None
    pnl_realized: Decimal | None
    positions: list[ClosingPosition]
    #: Whether this really is a *closing* valuation, i.e. a snapshot written at
    #: or after 16:00 ET on the last day. False means the settlement run
    #: (F121) did not happen or did not reach this portfolio.
    after_close: bool = False


@dataclass(frozen=True, slots=True)
class FinalReport:
    start_date: datetime.date
    end_date: datetime.date
    cutoff: datetime.datetime
    trading_days: int
    start_capital_usd: int
    score: CompetitionScore
    settlements: list[PersonaSettlement]
    benchmark_symbol: str
    benchmark_return: float | None
    #: Personas sharing rank 1 — a list, because §4.7 scoring can tie
    #: (`score_personas` ranks 1,1,1,4,…) and a tie is a result, not a bug.
    winners: list[ScoredPersona]
    #: Personas whose closing valuation is not from after the last day's close.
    missing_closing_valuation: list[str]


def build_final_report(
    session: Session,
    config: CompetitionConfig | None = None,
    mode: PortfolioMode = PortfolioMode.PAPER,
) -> FinalReport:
    competition = config or load_competition_config()
    if competition.end_date is None:
        raise ValueError("config/competition.yaml has no competition.end_date — see F121")

    since = datetime.datetime.combine(competition.start_date, datetime.time.min)
    cutoff = competition.settlement_cutoff()
    close = market_close_utc(competition.end_date)

    collected = collect_persona_criteria(
        session, since, competition.start_capital_usd, until=cutoff, mode=mode
    )
    score = score_personas([entry.criteria for entry in collected], competition.start_date)

    settlements = [
        _settlement(session, entry.persona, entry.portfolio_id, cutoff, close)
        for entry in collected
    ]

    benchmark_values = daily_benchmark_values(session, since, cutoff)
    benchmark_return = (
        simple_return([Decimal(str(competition.start_capital_usd)), *benchmark_values])
        if benchmark_values
        else None
    )

    return FinalReport(
        start_date=competition.start_date,
        end_date=competition.end_date,
        cutoff=cutoff,
        trading_days=max((len(entry.daily_values) for entry in collected), default=0),
        start_capital_usd=competition.start_capital_usd,
        score=score,
        settlements=settlements,
        benchmark_symbol=competition.benchmark_symbol,
        benchmark_return=benchmark_return,
        winners=[persona for persona in score.personas if persona.rank == 1],
        missing_closing_valuation=[s.persona for s in settlements if not s.after_close],
    )


def _settlement(
    session: Session,
    persona: str,
    portfolio_id: uuid.UUID,
    cutoff: datetime.datetime,
    close: datetime.datetime,
) -> PersonaSettlement:
    snapshot = session.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio_id, PortfolioSnapshot.ts <= cutoff)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    ).first()
    if snapshot is None:
        return PersonaSettlement(
            persona=persona,
            portfolio_id=portfolio_id,
            snapshot_ts=None,
            total_value=None,
            cash=None,
            pnl_realized=None,
            positions=[],
        )

    rows = session.scalars(
        select(PositionSnapshot)
        .where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.ts == snapshot.ts,
            PositionSnapshot.qty != 0,
        )
        .order_by(PositionSnapshot.instrument)
    ).all()

    return PersonaSettlement(
        persona=persona,
        portfolio_id=portfolio_id,
        snapshot_ts=snapshot.ts,
        total_value=snapshot.total_value,
        cash=snapshot.cash,
        pnl_realized=snapshot.pnl_realized,
        positions=[
            ClosingPosition(
                instrument=row.instrument,
                qty=row.qty,
                market_value=row.market_value,
                pnl_unrealized=row.pnl_unrealized,
            )
            for row in rows
        ],
        after_close=snapshot.ts >= close,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_MARKDOWN_TEMPLATE = """\
# Endabrechnung — ATLAS-Wettbewerb {{ fmt_date(report.start_date) }} bis \
{{ fmt_date(report.end_date) }}

Erzeugt aus der Wettbewerbs-DB, ohne LLM: `src/metrics/final_report.py` (F121).
Grundlage der Gewinner-Entscheidung nach ARCHITECTURE.md §4.7 — der ADR zur
Entscheidung referenziert diesen Report.

| | |
|---|---|
| Wertungsfenster | {{ fmt_date(report.start_date) }} – {{ fmt_date(report.end_date) }} \
({{ report.trading_days }} Tage mit Snapshot) |
| Bewertungsschnitt | {{ report.cutoff.strftime('%d.%m.%Y %H:%M') }} UTC |
| Startkapital je Persona | {{ fmt_int(report.start_capital_usd) }} USD |
| Gewertete Kriterien | {{ counted }} |
{% if report.score.skipped_criteria %}\
| Nicht wertbar (Gewicht umverteilt) | {{ skipped }} |
{% endif %}\
| Sieger nach §4.7 | {{ winner_line }} |

## 1. Rangliste (§4.7, gewichtet)

| Rang | Persona | Score | Sortino | Rendite n. Kosten | Max DD | Thesen | Zuverl. | Trades |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
{% for p in report.score.personas -%}
| {{ p.rank }} | {{ p.persona }} | {{ fmt_score(p.total_score) }} | \
{{ fmt_ratio(p.criteria.sortino) }} | {{ fmt_pct(p.criteria.adjusted_return) }} | \
{{ fmt_plain(p.criteria.max_drawdown) }} | {{ fmt_plain(p.criteria.thesis_quality) }} \
({{ p.criteria.reviews_total }}) | {{ fmt_plain(p.criteria.reliability) }} | \
{{ p.criteria.trades }} |
{% endfor %}
Gewichte laut §4.7: {{ weights }}.

## 2. Schlussbewertung zum Stichtag

Offene Positionen gehen mit ihrem Marktwert zum Stichtag ein und werden nicht
zwangsliquidiert (Ralfs Entscheidung, 16.08.2026).

| Persona | Depotwert | davon Cash | offene Positionen | Bewertung (UTC) |
|---|---:|---:|---:|---|
{% for s in report.settlements -%}
| {{ s.persona }} | {{ fmt_usd(s.total_value) }} | {{ fmt_usd(s.cash) }} | \
{{ s.positions | length }} | {{ fmt_ts(s.snapshot_ts) }}{{ '' if s.after_close else ' ⚠️' }} |
{% endfor %}
{% if report.missing_closing_valuation %}\
⚠️ **Keine Bewertung nach dem Schlusskurs** für: \
{{ report.missing_closing_valuation | join(', ') }}. Für diese Personas stammt die
Zahl aus dem letzten Zyklus-Snapshot des Stichtags (Aktien-Zyklus C4, 15:15 ET) —
die Endabrechnung ist damit keine Schlusskurs-Bewertung. Ursache prüfen
(`src/orchestrator/competition_settlement.py`), Settlement nachholen, Report neu
erzeugen.
{% endif %}\
{% for s in report.settlements %}{% if s.positions %}
**{{ s.persona }} — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
{% for pos in s.positions -%}
| {{ pos.instrument }} | {{ fmt_qty(pos.qty) }} | {{ fmt_usd(pos.market_value) }} | \
{{ fmt_usd(pos.pnl_unrealized) }} |
{% endfor %}{% endif %}{% endfor %}
## 3. Benchmark

{% if report.benchmark_return is not none -%}
{{ report.benchmark_symbol }} Buy-and-Hold über dasselbe Fenster: \
{{ fmt_pct(report.benchmark_return) }}.
{%- else -%}
Keine Benchmark-Werte im Fenster — `portfolio_snapshot.benchmark_value` ist leer (F081 prüfen).
{%- endif %}

## 4. Vorbehalt (§4.7, unverändert)

8 Wochen ≈ 40 Handelstage reichen nicht für eine signifikante
Strategie-Unterscheidung — der Sieger ist mit hoher Wahrscheinlichkeit Regime- und
Rausch-Glück. Das Paper-Feld läuft nach der Kür weiter, die Live-Persona wird
quartalsweise gegen das Feld re-evaluiert.
"""

_TELEGRAM_TEMPLATE = """\
\U0001f3c1 Endabrechnung §4.7 — {{ fmt_date(report.start_date) }} bis \
{{ fmt_date(report.end_date) }} ({{ report.trading_days }} Tage)

Sieger: {{ winner_line }}

{% for p in report.score.personas -%}
{{ p.rank }}. {{ p.persona }} — Score {{ fmt_score(p.total_score) }} | \
{{ fmt_usd(settlement_value(p.persona)) }} | Rendite n. Kosten \
{{ fmt_pct(p.criteria.adjusted_return) }}
{% endfor %}
{% if report.benchmark_return is not none -%}
Benchmark {{ report.benchmark_symbol }}: {{ fmt_pct(report.benchmark_return) }}
{% endif -%}
Gewertet: {{ counted }}
{% if report.missing_closing_valuation -%}
⚠️ Ohne Schlusskurs-Bewertung: {{ report.missing_closing_valuation | join(', ') }}
{% endif -%}
⚠️ 8 Wochen trennen Können nicht von Zufall (§4.7). Der Report ist die \
Grundlage der Entscheidung, nicht die Entscheidung.
"""

_env = Environment(autoescape=False)  # noqa: S701  # nosec B701 — plain text/markdown, same contract as the weekly report


def _fmt_date(value: datetime.date) -> str:
    return value.strftime("%d.%m.%Y")


def _fmt_ts(value: datetime.datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value is not None else "–"


def _fmt_pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:+.2f} %".replace(".", ",")


def _fmt_plain(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.2f} %".replace(".", ",")


def _fmt_ratio(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}".replace(".", ",")


def _fmt_score(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def _fmt_usd(value: Decimal | None) -> str:
    return "–" if value is None else f"{value:,.2f} $".replace(",", " ").replace(".", ",")


def _fmt_int(value: int) -> str:
    return f"{value:,.0f}".replace(",", "\u00a0")


def _fmt_qty(value: Decimal) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _winner_line(report: FinalReport) -> str:
    if not report.winners:
        return "–"
    names = ", ".join(winner.persona for winner in report.winners)
    score = _fmt_score(report.winners[0].total_score)
    if len(report.winners) > 1:
        return f"{names} (punktgleich, Score {score})"
    return f"{names} (Score {score})"


def _context(report: FinalReport) -> dict[str, object]:
    by_persona = {s.persona: s.total_value for s in report.settlements}
    return {
        "report": report,
        "counted": ", ".join(
            f"{CRITERION_LABELS[name]} {CRITERION_WEIGHTS[name] * 100:.0f} %"
            for name in report.score.counted_criteria
        )
        or "keine",
        "skipped": ", ".join(CRITERION_LABELS[name] for name in report.score.skipped_criteria),
        "weights": ", ".join(
            f"{CRITERION_LABELS[name]} {weight * 100:.0f} %"
            for name, weight in CRITERION_WEIGHTS.items()
        ),
        "winner_line": _winner_line(report),
        "settlement_value": by_persona.get,
        "fmt_date": _fmt_date,
        "fmt_ts": _fmt_ts,
        "fmt_pct": _fmt_pct,
        "fmt_plain": _fmt_plain,
        "fmt_ratio": _fmt_ratio,
        "fmt_score": _fmt_score,
        "fmt_usd": _fmt_usd,
        "fmt_int": _fmt_int,
        "fmt_qty": _fmt_qty,
    }


def render_final_report_markdown(report: FinalReport) -> str:
    """The artefact the winner ADR references — full criteria table, closing
    valuations and every open position at the cutoff."""
    return _env.from_string(_MARKDOWN_TEMPLATE).render(**_context(report))


def render_final_report_telegram(report: FinalReport) -> str:
    """Short version for the Telegram push on the evening of the last day."""
    return _env.from_string(_TELEGRAM_TEMPLATE).render(**_context(report))
