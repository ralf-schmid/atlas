"""F121: the Endabrechnung — closed scoring window, closing valuation, winner."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.metrics.final_report import (
    build_final_report,
    render_final_report_markdown,
    render_final_report_telegram,
)
from src.orchestrator.competition_config import CompetitionConfig
from tests.db.factories import (
    make_persona,
    make_portfolio,
    make_portfolio_snapshot,
    make_position_snapshot,
)

_START = datetime.date(2026, 7, 27)
_END = datetime.date(2026, 9, 18)
_CLOSE = datetime.datetime(2026, 9, 18, 20, 35)  # after 16:00 ET


def _config(end_date: datetime.date | None = _END) -> CompetitionConfig:
    return CompetitionConfig(
        start_date=_START,
        end_date=end_date,
        start_capital_usd=5000,
        benchmark_enabled=True,
        benchmark_symbol="SPY",
    )


def _seed(
    session: Session,
    name: str,
    *,
    closing_value: str,
    closing_ts: datetime.datetime = _CLOSE,
    benchmark: str | None = None,
):
    portfolio = make_portfolio(session, make_persona(session, name=name))
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=datetime.datetime.combine(_START, datetime.time(20, 30)),
        total_value=Decimal("5000.00"),
        cash=Decimal("5000.00"),
        benchmark_value=Decimal("5000.00") if benchmark else None,
    )
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=closing_ts,
        total_value=Decimal(closing_value),
        cash=Decimal("1000.00"),
        benchmark_value=Decimal(benchmark) if benchmark else None,
    )
    return portfolio


def test_winner_is_the_rank_one_persona(session: Session) -> None:
    _seed(session, "CONTRA", closing_value="5400.00")
    _seed(session, "GUARDIAN", closing_value="4950.00")
    session.flush()

    report = build_final_report(session, _config())

    assert [w.persona for w in report.winners] == ["CONTRA"]
    assert report.score.personas[0].rank == 1
    assert report.trading_days == 2


def test_a_tie_is_reported_as_a_tie(session: Session) -> None:
    """`score_personas` ranks 1,1,3 — the report must not invent an order."""
    _seed(session, "HYPE", closing_value="5100.00")
    _seed(session, "CHARTIST", closing_value="5100.00")
    session.flush()

    report = build_final_report(session, _config())

    assert sorted(w.persona for w in report.winners) == ["CHARTIST", "HYPE"]
    assert "punktgleich" in render_final_report_telegram(report)


def test_the_window_ends_with_the_competition(session: Session) -> None:
    """The paper field keeps trading afterwards (§4.7); a later snapshot must not
    change the settled result."""
    portfolio = _seed(session, "VULTURE", closing_value="5200.00")
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=datetime.datetime(2026, 9, 25, 20, 30),
        total_value=Decimal("9999.00"),
        cash=Decimal("9999.00"),
    )
    session.flush()

    report = build_final_report(session, _config())

    settlement = report.settlements[0]
    assert settlement.total_value == Decimal("5200.00")
    assert settlement.snapshot_ts == _CLOSE
    assert report.trading_days == 2


def test_open_positions_are_valued_at_the_close(session: Session) -> None:
    """Ralf's ruling, 16.08.2026: open positions go into the settlement with their
    market value, they are not force-liquidated."""
    portfolio = _seed(session, "CRYPTOR", closing_value="5150.00")
    make_position_snapshot(session, portfolio, ts=_CLOSE, instrument="BTC/USD", qty=Decimal("0.05"))
    make_position_snapshot(session, portfolio, ts=_CLOSE, instrument="ETH/USD", qty=Decimal("0"))
    session.flush()

    report = build_final_report(session, _config())

    positions = report.settlements[0].positions
    assert [p.instrument for p in positions] == ["BTC/USD"]
    assert positions[0].market_value == Decimal("1550.00")
    assert report.missing_closing_valuation == []


def test_a_valuation_from_before_the_close_is_flagged(session: Session) -> None:
    """C4 runs at 15:15 ET — its snapshot is not a closing valuation, and the
    report has to say so instead of presenting it as one."""
    _seed(
        session,
        "GUARDIAN",
        closing_value="5010.00",
        closing_ts=datetime.datetime(2026, 9, 18, 19, 20),
    )
    session.flush()

    report = build_final_report(session, _config())

    assert report.missing_closing_valuation == ["GUARDIAN"]
    assert "⚠️" in render_final_report_markdown(report)


def test_benchmark_return_over_the_closed_window(session: Session) -> None:
    _seed(session, "HYPE", closing_value="5100.00", benchmark="5250.00")
    session.flush()

    report = build_final_report(session, _config())

    assert report.benchmark_symbol == "SPY"
    assert report.benchmark_return is not None
    assert round(report.benchmark_return, 4) == 0.05


def test_build_final_report_refuses_without_an_end_date(session: Session) -> None:
    with pytest.raises(ValueError, match="end_date"):
        build_final_report(session, _config(end_date=None))


def test_markdown_carries_the_facts_the_adr_needs(session: Session) -> None:
    _seed(session, "CONTRA", closing_value="5400.00")
    _seed(session, "GUARDIAN", closing_value="4950.00")
    session.flush()

    text = render_final_report_markdown(build_final_report(session, _config()))

    assert "Endabrechnung" in text
    assert "27.07.2026" in text and "18.09.2026" in text
    assert "CONTRA" in text and "GUARDIAN" in text
    # non-breaking thousands separator, German typography
    assert "5\u00a0400,00 $" in text  # closing valuation, not a rounded teaser
    assert "8 Wochen" in text  # §4.7 disclaimer stays in the artefact


def test_a_portfolio_without_any_snapshot_is_reported_as_a_gap(session: Session) -> None:
    """Not a zero — an unknown. The report must not present a missing valuation as
    a portfolio that happens to be worth nothing."""
    make_portfolio(session, make_persona(session, name="VULTURE"))
    session.flush()

    report = build_final_report(session, _config())

    (settlement,) = report.settlements
    assert settlement.total_value is None
    assert settlement.snapshot_ts is None
    assert report.missing_closing_valuation == ["VULTURE"]
    assert "–" in render_final_report_markdown(report)
