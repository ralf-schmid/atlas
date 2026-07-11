import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import CostLedgerScope, OrderRecordStatus
from src.telegram.digest import (
    DigestData,
    PersonaDigest,
    _format_cost_de,
    _format_currency_de,
    build_digest_data,
    render_daily_digest,
)
from tests.db.factories import (
    make_cost_ledger_entry,
    make_cycle,
    make_decision,
    make_order_record,
    make_persona,
    make_portfolio,
    make_portfolio_snapshot,
    make_position_snapshot,
    make_research_item,
)


def test_render_daily_digest_contains_all_required_fields():
    data = DigestData(
        trading_day=datetime.date(2026, 7, 5),
        personas=[
            PersonaDigest(
                name="VULTURE",
                trades_today=4,
                portfolio_value_usd=5200.0,
                cash_usd=1200.0,
                open_positions=8,
                llm_cost_usd=0.35,
            ),
            PersonaDigest(
                name="GUARDIAN",
                trades_today=0,
                portfolio_value_usd=4980.0,
                cash_usd=1500.0,
                open_positions=2,
                llm_cost_usd=0.10,
            ),
        ],
    )

    digest = render_daily_digest(data)

    assert "05.07.2026" in digest
    assert "VULTURE:\n4 Trades" in digest
    assert "Depotwert $5.200,00" in digest
    assert "LLM-Kosten $0,3500" in digest
    assert "GUARDIAN:\n0 Trades" in digest
    assert "Gesamt: $10.180,00" in digest
    assert "LLM-Kosten gesamt: $0,4500" in digest


def test_format_currency_de_uses_period_thousands_and_comma_decimal():
    assert _format_currency_de(1234567.89) == "1.234.567,89"
    assert _format_currency_de(0.05) == "0,05"
    assert _format_currency_de(-50.5) == "-50,50"
    assert _format_currency_de(1000.0) == "1.000,00"


def test_format_cost_de_uses_four_decimal_places():
    assert _format_cost_de(0.0405) == "0,0405"
    assert _format_cost_de(1234.5) == "1.234,5000"


def test_digest_totals_are_computed_properties():
    data = DigestData(
        trading_day=datetime.date(2026, 7, 5),
        personas=[
            PersonaDigest(
                name="VULTURE",
                trades_today=1,
                portfolio_value_usd=100.0,
                cash_usd=10.0,
                open_positions=1,
                llm_cost_usd=0.01,
            ),
        ],
    )

    assert data.total_portfolio_value_usd == 100.0
    assert data.total_llm_cost_usd == 0.01


def test_build_digest_data_excludes_inactive_personas(session: Session) -> None:
    active = make_persona(session, name="VULTURE")
    inactive = make_persona(session, name="GUARDIAN")
    inactive.active = False
    session.flush()
    make_portfolio(session, active)
    make_portfolio(session, inactive)

    data = build_digest_data(session, datetime.date(2026, 7, 4))

    assert [p.name for p in data.personas] == ["VULTURE"]


def test_build_digest_data_counts_only_filled_orders_within_the_day(session: Session) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research_item)
    make_order_record(
        session,
        decision,
        status=OrderRecordStatus.FILLED,
        submitted_at=datetime.datetime(2026, 7, 4, 9, 1),
    )
    # not filled -> doesn't count as a trade that happened
    make_order_record(
        session,
        decision,
        status=OrderRecordStatus.CANCELED,
        submitted_at=datetime.datetime(2026, 7, 4, 10, 0),
    )
    # filled, but a different day -> doesn't count for 2026-07-04
    make_order_record(
        session,
        decision,
        status=OrderRecordStatus.FILLED,
        submitted_at=datetime.datetime(2026, 7, 3, 9, 1),
    )

    data = build_digest_data(session, datetime.date(2026, 7, 4))

    assert data.personas[0].trades_today == 1


def test_build_digest_data_uses_latest_portfolio_snapshot_regardless_of_date(
    session: Session,
) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=datetime.datetime(2026, 7, 3, 16, 0),
        total_value=Decimal("4900.00"),
        cash=Decimal("3000.00"),
    )
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=datetime.datetime(2026, 7, 4, 16, 0),
        total_value=Decimal("5100.00"),
        cash=Decimal("3200.00"),
    )

    data = build_digest_data(session, datetime.date(2026, 7, 4))

    assert data.personas[0].portfolio_value_usd == 5100.00
    assert data.personas[0].cash_usd == 3200.00


def test_build_digest_data_counts_only_nonzero_positions_at_the_latest_snapshot(
    session: Session,
) -> None:
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    # stale snapshot from an earlier ts -> must not be counted
    make_position_snapshot(
        session, portfolio, ts=datetime.datetime(2026, 7, 3, 16, 0), instrument="OLD"
    )
    make_position_snapshot(
        session, portfolio, ts=datetime.datetime(2026, 7, 4, 16, 0), instrument="AAPL"
    )
    make_position_snapshot(
        session,
        portfolio,
        ts=datetime.datetime(2026, 7, 4, 16, 0),
        instrument="MSFT",
        qty=Decimal("0"),
    )

    data = build_digest_data(session, datetime.date(2026, 7, 4))

    assert data.personas[0].open_positions == 1


def test_build_digest_data_sums_persona_scope_cost_for_the_day(session: Session) -> None:
    persona = make_persona(session, name="VULTURE")
    make_portfolio(session, persona)
    make_cost_ledger_entry(
        session,
        persona_id=persona.id,
        ts=datetime.datetime(2026, 7, 4, 9, 0),
        cost_usd=Decimal("0.10"),
    )
    make_cost_ledger_entry(
        session,
        persona_id=persona.id,
        ts=datetime.datetime(2026, 7, 4, 14, 0),
        cost_usd=Decimal("0.05"),
    )
    # system-scope cost must not be attributed to a persona
    make_cost_ledger_entry(
        session,
        persona_id=None,
        scope=CostLedgerScope.SYSTEM,
        ts=datetime.datetime(2026, 7, 4, 9, 0),
        cost_usd=Decimal("1.00"),
    )
    # a different day must not count towards 2026-07-04
    make_cost_ledger_entry(
        session,
        persona_id=persona.id,
        ts=datetime.datetime(2026, 7, 3, 9, 0),
        cost_usd=Decimal("0.50"),
    )

    data = build_digest_data(session, datetime.date(2026, 7, 4))

    assert data.personas[0].llm_cost_usd == 0.15


def test_build_digest_data_empty_when_no_active_personas(session: Session) -> None:
    data = build_digest_data(session, datetime.date(2026, 7, 4))

    assert data.personas == []
    assert data.total_portfolio_value_usd == 0.0
