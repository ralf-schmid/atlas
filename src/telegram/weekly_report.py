"""Weekly §4.7 report — the five fixed selection criteria, weighted, as a Telegram
message. Plain code over `portfolio_snapshot`/`review`/`agent_run`/`order_record`
(F082/F084 data), no LLM anywhere in the path. See F089.

ARCHITECTURE.md §5.2 schedules this for Sunday, next to the review week-run.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from jinja2 import Environment
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Persona, Portfolio, PortfolioMode
from src.metrics.competition_score import (
    CRITERION_LABELS,
    CRITERION_WEIGHTS,
    CompetitionScore,
    PersonaCriteria,
    reliability_inputs,
    score_personas,
    thesis_quality,
)
from src.metrics.performance import (
    adjusted_return,
    daily_benchmark_values,
    daily_portfolio_values,
    daily_returns,
    max_drawdown,
    simple_return,
    slippage_malus_sum,
    sortino_ratio,
    spread_method_split,
    trade_count,
)
from src.orchestrator.competition_config import load_competition_config

_TEMPLATE_SOURCE = """\
\U0001f3c6 Wochenreport §4.7 — Stand {{ as_of.strftime('%d.%m.%Y') }}
Wettbewerb seit {{ score.since.strftime('%d.%m.%Y') }} ({{ trading_days }} Handelstage)

{% for p in score.personas -%}
{{ p.rank }}. {{ p.persona }} — Score {{ format_score(p.total_score) }}
Rendite n. Kosten {{ format_pct(p.criteria.adjusted_return) }} | Drawdown \
{{ format_plain(p.criteria.max_drawdown) }} | Trades {{ p.criteria.trades }}
Sortino {{ format_ratio(p.criteria.sortino) }} | Thesen \
{{ format_plain(p.criteria.thesis_quality) }} ({{ p.criteria.reviews_total }}) | Zuverl. \
{{ format_plain(p.criteria.reliability) }}

{% endfor -%}
{% if benchmark_return is not none -%}
Benchmark {{ benchmark_symbol }}: {{ format_pct(benchmark_return) }}
{% endif %}
Gewertet: {{ counted_labels }}
{% if score.skipped_criteria -%}
Nicht wertbar (Gewicht umverteilt): {{ skipped_labels }}
{% endif -%}
{% if mixed_spread_method -%}
ℹ️ Slippage-Malus aus zwei Methoden: {{ orders_measured }} von \
{{ orders_measured + orders_flat }} Orders mit am Ordermoment gemessenem Spread, \
der Rest mit der Pauschale (historische Quotes sind nicht rekonstruierbar). \
Der Schnitt verläuft zeitlich, nicht je Persona — die Rangfolge ist davon nicht \
verzerrt, die absolute Malus-Zahl aber nicht einheitlich gerechnet.
{% endif -%}

⚠️ 8 Wochen ≈ 40 Handelstage trennen Können nicht von Zufall (§4.7). \
Zwischenstand, kein Ergebnis.\
"""

_env = Environment(autoescape=False)  # noqa: S701  # nosec B701 — plain text, same contract as the daily digest
_template = _env.from_string(_TEMPLATE_SOURCE)


@dataclass(frozen=True, slots=True)
class WeeklyReportData:
    as_of: datetime.date
    trading_days: int
    score: CompetitionScore
    benchmark_symbol: str
    benchmark_return: float | None
    # F104 §2: only ever both non-zero while pre- and post-F104 orders share the
    # scoring window. Once the last flat-rate order ages out, the note disappears
    # on its own.
    orders_measured_spread: int = 0
    orders_flat_spread: int = 0


def _format_pct(value: float | None) -> str:
    """Signed — a return is only readable with its direction."""
    if value is None:
        return "–"
    return f"{value * 100:+.2f} %".replace(".", ",")


def _format_pct_plain(value: float | None) -> str:
    """Unsigned, for quantities that have no direction: a drawdown is always a
    loss, a reliability share is always positive. "+0,16 % Drawdown" reads like
    a gain."""
    if value is None:
        return "–"
    return f"{value * 100:.2f} %".replace(".", ",")


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:.2f}".replace(".", ",")


def _format_score(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def render_weekly_report(data: WeeklyReportData) -> str:
    return _template.render(
        as_of=data.as_of,
        trading_days=data.trading_days,
        score=data.score,
        benchmark_symbol=data.benchmark_symbol,
        benchmark_return=data.benchmark_return,
        counted_labels=", ".join(
            f"{CRITERION_LABELS[name]} {CRITERION_WEIGHTS[name] * 100:.0f} %"
            for name in data.score.counted_criteria
        )
        or "keine",
        skipped_labels=", ".join(CRITERION_LABELS[name] for name in data.score.skipped_criteria),
        mixed_spread_method=bool(data.orders_measured_spread and data.orders_flat_spread),
        orders_measured=data.orders_measured_spread,
        orders_flat=data.orders_flat_spread,
        format_pct=_format_pct,
        format_plain=_format_pct_plain,
        format_ratio=_format_ratio,
        format_score=_format_score,
    )


def build_weekly_report(
    session: Session, as_of: datetime.date, mode: PortfolioMode = PortfolioMode.PAPER
) -> WeeklyReportData:
    competition = load_competition_config()
    since = datetime.datetime.combine(competition.start_date, datetime.time.min)

    portfolios = session.execute(
        select(Portfolio, Persona.name)
        .join(Persona, Portfolio.persona_id == Persona.id)
        .where(
            Persona.active.is_(True),
            Portfolio.mode == mode,
            Portfolio.archived_at.is_(None),
        )
        .order_by(Persona.name)
    ).all()

    criteria: list[PersonaCriteria] = []
    trading_days = 0
    for portfolio, persona_name in portfolios:
        values = daily_portfolio_values(session, portfolio.id, since)
        trading_days = max(trading_days, len(values))
        raw = simple_return([Decimal(str(competition.start_capital_usd)), *values])
        share, reviews_total = thesis_quality(session, portfolio.id, since)
        reliability = reliability_inputs(session, portfolio.id, since)
        criteria.append(
            PersonaCriteria(
                persona=persona_name,
                sortino=sortino_ratio(daily_returns(values)),
                adjusted_return=adjusted_return(
                    raw,
                    slippage_malus_sum(session, portfolio.id, since),
                    competition.start_capital_usd,
                ),
                max_drawdown=max_drawdown(values),
                thesis_quality=share,
                reliability=reliability.score(),
                reliability_inputs=reliability,
                reviews_total=reviews_total,
                trades=trade_count(session, portfolio.id, since),
            )
        )

    benchmark_values = daily_benchmark_values(session, since)
    benchmark_return = (
        simple_return([Decimal(str(competition.start_capital_usd)), *benchmark_values])
        if benchmark_values
        else None
    )

    measured, flat = spread_method_split(session, since)

    return WeeklyReportData(
        as_of=as_of,
        trading_days=trading_days,
        score=score_personas(criteria, competition.start_date),
        benchmark_symbol=competition.benchmark_symbol,
        benchmark_return=benchmark_return,
        orders_measured_spread=measured,
        orders_flat_spread=flat,
    )
