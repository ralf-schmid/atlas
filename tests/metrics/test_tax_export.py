"""F123: FIFO matching and the CSV for the Steuer-Export (P6 DoD)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import DecisionAction, Portfolio
from src.metrics.tax_export import build_tax_export, render_tax_csv
from tests.db.factories import (
    make_cycle,
    make_decision,
    make_order_record,
    make_persona,
    make_portfolio,
    make_research_item,
)


def _trade(
    session: Session,
    portfolio: Portfolio,
    *,
    action: DecisionAction,
    instrument: str,
    qty: str,
    price: str,
    when: datetime.datetime,
    fees: str = "0",
) -> None:
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    decision = make_decision(
        session,
        cycle,
        portfolio,
        item,
        action=action,
        instrument=instrument,
        quantity=Decimal(qty),
    )
    order = make_order_record(
        session, decision, submitted_at=when, filled_at=when, fill_price=Decimal(price)
    )
    order.fees = Decimal(fees)
    session.flush()


def _portfolio(session: Session, name: str = "CONTRA") -> Portfolio:
    return make_portfolio(session, make_persona(session, name=name))


def test_fifo_matches_the_oldest_lot_first(session: Session) -> None:
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="AAPL",
        qty="10",
        price="100",
        when=datetime.datetime(2026, 3, 2, 15, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="AAPL",
        qty="10",
        price="120",
        when=datetime.datetime(2026, 5, 4, 15, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.SELL,
        instrument="AAPL",
        qty="15",
        price="130",
        when=datetime.datetime(2026, 8, 3, 15, 0),
    )

    export = build_tax_export(session, portfolio.id)

    assert [(t.qty, t.buy_price) for t in export.trades] == [
        (Decimal("10"), Decimal("100")),
        (Decimal("5"), Decimal("120")),
    ]
    assert export.result_sum == Decimal("350")  # 10*(130-100) + 5*(130-120)
    assert export.unmatched == []


def test_close_realises_like_a_sell_and_carries_its_fees(session: Session) -> None:
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="ADSK",
        qty="4",
        price="200",
        when=datetime.datetime(2026, 6, 1, 15, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.CLOSE,
        instrument="ADSK",
        qty="4",
        price="250",
        when=datetime.datetime(2026, 6, 20, 15, 0),
        fees="1.50",
    )

    (trade,) = build_tax_export(session, portfolio.id).trades

    assert trade.proceeds == Decimal("1000")
    assert trade.cost == Decimal("800")
    assert trade.fees == Decimal("1.500000")
    assert trade.result == Decimal("198.500000")
    assert trade.holding_days == 19


def test_open_positions_are_not_realised(session: Session) -> None:
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="AAPL",
        qty="3",
        price="100",
        when=datetime.datetime(2026, 6, 1, 15, 0),
    )

    assert build_tax_export(session, portfolio.id).trades == []


def test_a_sell_without_a_recorded_buy_is_named_not_swallowed(session: Session) -> None:
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.SELL,
        instrument="LUNG",
        qty="5",
        price="9",
        when=datetime.datetime(2026, 7, 1, 15, 0),
    )

    export = build_tax_export(session, portfolio.id)

    assert export.trades == []
    assert export.unmatched == ["LUNG"]


def test_crypto_inside_the_year_is_flagged_for_paragraph_23(session: Session) -> None:
    portfolio = _portfolio(session, name="CRYPTOR")
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="BTC/USD",
        qty="0.5",
        price="60000",
        when=datetime.datetime(2026, 1, 5, 12, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.SELL,
        instrument="BTC/USD",
        qty="0.5",
        price="64000",
        when=datetime.datetime(2026, 9, 5, 12, 0),
    )

    (trade,) = build_tax_export(session, portfolio.id).trades

    assert trade.asset_class == "crypto"
    assert trade.paragraph_23 is True
    assert trade.holding_days == 243


def test_the_export_window_bounds_the_disposal_not_the_acquisition(session: Session) -> None:
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="AAPL",
        qty="2",
        price="100",
        when=datetime.datetime(2025, 11, 3, 15, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.SELL,
        instrument="AAPL",
        qty="2",
        price="150",
        when=datetime.datetime(2026, 2, 9, 15, 0),
    )

    export = build_tax_export(
        session,
        portfolio.id,
        since=datetime.datetime(2026, 1, 1),
        until=datetime.datetime(2026, 12, 31, 23, 59, 59),
    )

    (trade,) = export.trades
    assert trade.buy_date.year == 2025  # reported with its original acquisition


def test_csv_uses_german_separators_and_names_the_currency(session: Session) -> None:
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="AAPL",
        qty="2",
        price="100",
        when=datetime.datetime(2026, 2, 2, 15, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.SELL,
        instrument="AAPL",
        qty="2",
        price="150",
        when=datetime.datetime(2026, 3, 2, 15, 0),
    )

    csv_text = render_tax_csv(build_tax_export(session, portfolio.id))

    header, row = csv_text.strip().split("\n")
    assert header.split(";")[:4] == ["verkauf_datum", "kauf_datum", "instrument", "assetklasse"]
    assert row.startswith("2026-03-02;2026-02-02;AAPL;stock;")
    assert ";USD;" in row
    assert "100,00" in row  # result 2*(150-100), decimal comma


def test_holds_and_incomplete_orders_are_ignored(session: Session) -> None:
    """A hold never realises anything, and a filled order without a quantity is a
    data defect — neither may end up in a tax document."""
    portfolio = _portfolio(session)
    _trade(
        session,
        portfolio,
        action=DecisionAction.BUY,
        instrument="AAPL",
        qty="5",
        price="100",
        when=datetime.datetime(2026, 4, 1, 15, 0),
    )
    _trade(
        session,
        portfolio,
        action=DecisionAction.HOLD,
        instrument="AAPL",
        qty="5",
        price="110",
        when=datetime.datetime(2026, 4, 15, 15, 0),
    )
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    broken = make_decision(
        session,
        cycle,
        portfolio,
        item,
        action=DecisionAction.SELL,
        instrument="AAPL",
        quantity=None,
    )
    make_order_record(
        session,
        broken,
        submitted_at=datetime.datetime(2026, 5, 2, 15, 0),
        filled_at=datetime.datetime(2026, 5, 2, 15, 0),
        fill_price=Decimal("120"),
    )
    session.flush()

    export = build_tax_export(session, portfolio.id)

    assert export.trades == []
    assert export.unmatched == []
