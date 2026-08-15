"""F089: the Sunday §4.7 report — assembly from the DB and Telegram rendering."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import OrderRecordStatus
from src.orchestrator.competition_config import load_competition_config
from src.telegram.weekly_report import build_weekly_report, render_weekly_report
from tests.db.factories import (
    make_cycle,
    make_decision,
    make_order_record,
    make_persona,
    make_portfolio,
    make_portfolio_snapshot,
    make_research_item,
)

_AS_OF = datetime.date(2026, 8, 2)


def _start() -> datetime.datetime:
    return datetime.datetime.combine(load_competition_config().start_date, datetime.time.min)


def _seed(session: Session, name: str, values: list[str], benchmark: str | None = None) -> None:
    portfolio = make_portfolio(session, make_persona(session, name=name))
    for index, value in enumerate(values):
        make_portfolio_snapshot(
            session,
            portfolio,
            ts=_start() + datetime.timedelta(days=index, hours=16),
            total_value=Decimal(value),
            cash=Decimal(value),
            benchmark_value=Decimal(benchmark) if benchmark else None,
        )


def test_build_weekly_report_ranks_the_field(session: Session) -> None:
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    _seed(session, "GUARDIAN", ["5000.00", "4900.00"])
    session.flush()

    data = build_weekly_report(session, _AS_OF)

    assert data.trading_days == 2
    assert [p.persona for p in data.score.personas] == ["VULTURE", "GUARDIAN"]
    assert data.score.personas[0].rank == 1


def test_build_weekly_report_skips_criteria_without_data(session: Session) -> None:
    """Week one: no Sortino (needs 20 daily returns), no reviews."""
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    _seed(session, "GUARDIAN", ["5000.00", "4900.00"])
    session.flush()

    data = build_weekly_report(session, _AS_OF)

    assert "sortino" in data.score.skipped_criteria
    assert "thesis_quality" in data.score.skipped_criteria
    assert "adjusted_return" in data.score.counted_criteria


def test_build_weekly_report_reads_the_benchmark(session: Session) -> None:
    _seed(session, "VULTURE", ["5000.00"], benchmark="5100.00")
    session.flush()

    data = build_weekly_report(session, _AS_OF)

    assert data.benchmark_symbol == "SPY"
    assert data.benchmark_return is not None
    assert round(data.benchmark_return, 4) == 0.02


def test_build_weekly_report_excludes_archived_portfolios(session: Session) -> None:
    persona = make_persona(session, name="HYPE")
    archived = make_portfolio(session, persona)
    archived.archived_at = _start()
    make_portfolio_snapshot(session, archived, ts=_start() + datetime.timedelta(hours=16))
    session.flush()

    assert build_weekly_report(session, _AS_OF).score.personas == []


def test_render_weekly_report_shows_ranking_weights_and_disclaimer(session: Session) -> None:
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    _seed(session, "GUARDIAN", ["5000.00", "4900.00"])
    session.flush()

    text = render_weekly_report(build_weekly_report(session, _AS_OF))

    assert "Wochenreport §4.7" in text
    assert "1. VULTURE" in text
    assert "2. GUARDIAN" in text
    assert "+4,00 %" in text  # VULTURE's return after costs
    assert "Rendite nach Kosten 25 %" in text  # weights are named, not implied
    assert "Nicht wertbar" in text  # Sortino/thesis quality are missing in week one
    assert "trennen Können nicht von Zufall" in text  # §4.7 disclaimer
    # a drawdown has no direction — "+0,00 %" would read like a gain
    assert "Drawdown 0,00 %" in text


def test_render_weekly_report_marks_unmeasurable_values_with_a_dash(session: Session) -> None:
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    session.flush()

    text = render_weekly_report(build_weekly_report(session, _AS_OF))

    assert "Sortino –" in text


# --- F104 §2: der Methodenbruch beim Slippage-Malus wird ausgewiesen


def _seed_orders_with_spreads(session: Session, spreads: list[Decimal | None]) -> None:
    persona = make_persona(session, name="CONTRA")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research_item)
    for spread in spreads:
        order = make_order_record(
            session,
            decision,
            status=OrderRecordStatus.FILLED,
            submitted_at=_start() + datetime.timedelta(days=1),
        )
        order.spread_bps = spread
    session.flush()


def test_weekly_report_notes_the_mixed_spread_method(session: Session) -> None:
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    _seed_orders_with_spreads(session, [Decimal("12.5"), None, None])

    data = build_weekly_report(session, _AS_OF)
    text = render_weekly_report(data)

    assert (data.orders_measured_spread, data.orders_flat_spread) == (1, 2)
    assert "Slippage-Malus aus zwei Methoden" in text
    assert "1 von 3 Orders" in text
    assert "zeitlich, nicht je Persona" in text


def test_weekly_report_stays_silent_once_every_order_is_measured(session: Session) -> None:
    """Der Hinweis verschwindet von selbst, sobald die letzte Pauschal-Order aus
    dem Wertungsfenster gelaufen ist — kein Aufräum-Commit nötig."""
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    _seed_orders_with_spreads(session, [Decimal("12.5"), Decimal("9.0")])

    text = render_weekly_report(build_weekly_report(session, _AS_OF))

    assert "Slippage-Malus aus zwei Methoden" not in text


def test_weekly_report_stays_silent_before_the_first_measured_order(session: Session) -> None:
    """Heutiger Zustand: alle Orders sind pauschal — es gibt noch keinen Bruch."""
    _seed(session, "VULTURE", ["5000.00", "5200.00"])
    _seed_orders_with_spreads(session, [None, None])

    text = render_weekly_report(build_weekly_report(session, _AS_OF))

    assert "Slippage-Malus aus zwei Methoden" not in text
