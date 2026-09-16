"""F121: the closing valuation on the competition's last day."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.broker.protocol import AccountBalance, BrokerAdapter, OrderSide, Position
from src.db.models import PortfolioSnapshot
from src.orchestrator.competition_config import CompetitionConfig
from src.orchestrator.competition_settlement import (
    is_settlement_due,
    market_close_utc,
    run_final_settlement,
    settlement_snapshot_id,
)
from tests.db.factories import make_persona, make_portfolio, make_portfolio_snapshot

_END = datetime.date(2026, 9, 18)


def _config(end_date: datetime.date | None = _END) -> CompetitionConfig:
    return CompetitionConfig(
        start_date=datetime.date(2026, 7, 27),
        end_date=end_date,
        start_capital_usd=5000,
        benchmark_enabled=True,
        benchmark_symbol="SPY",
    )


class _FakeAdapter:
    requires_whole_shares = False

    def __init__(self, equity: float = 5100.0, fail: bool = False) -> None:
        self._equity = equity
        self._fail = fail

    def get_account_balance(self) -> AccountBalance:
        if self._fail:
            raise RuntimeError("broker unreachable")
        return AccountBalance(cash=100.0, equity=self._equity, buying_power=100.0)

    def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol="AAPL",
                qty=10.0,
                side=OrderSide.BUY,
                avg_entry_price=150.0,
                market_value=1600.0,
                unrealized_pl=100.0,
            )
        ]


def _adapter_factory(**by_persona: BrokerAdapter):
    def factory(persona: str) -> BrokerAdapter:
        return by_persona[persona]

    return factory


def test_market_close_is_2000_utc_in_september() -> None:
    """16:00 ET on an EDT day. Hard-coding -4h would be right today and wrong
    after the DST switch, so the conversion goes through zoneinfo."""
    assert market_close_utc(_END) == datetime.datetime(2026, 9, 18, 20, 0)
    assert market_close_utc(datetime.date(2026, 12, 18)) == datetime.datetime(2026, 12, 18, 21, 0)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime.datetime(2026, 9, 18, 20, 35), True),
        (datetime.datetime(2026, 9, 18, 20, 0), True),
        (datetime.datetime(2026, 9, 18, 19, 15), False),  # C4 ran, market still open
        (datetime.datetime(2026, 9, 17, 20, 35), False),
        (datetime.datetime(2026, 9, 21, 20, 35), False),
    ],
)
def test_is_settlement_due(now: datetime.datetime, expected: bool) -> None:
    assert is_settlement_due(now, _config()) is expected


def test_is_settlement_due_is_false_without_an_end_date() -> None:
    assert (
        is_settlement_due(datetime.datetime(2026, 9, 18, 20, 35), _config(end_date=None)) is False
    )


def test_run_final_settlement_writes_one_snapshot_per_active_portfolio(session: Session) -> None:
    for name in ("VULTURE", "GUARDIAN"):
        make_portfolio(session, make_persona(session, name=name))
    session.flush()
    now = datetime.datetime(2026, 9, 18, 20, 35)

    result = run_final_settlement(
        session,
        _adapter_factory(VULTURE=_FakeAdapter(), GUARDIAN=_FakeAdapter(4900.0)),
        now,
    )

    assert result.personas == ["GUARDIAN", "VULTURE"]
    assert result.failed == []
    written = session.scalar(
        select(func.count()).select_from(PortfolioSnapshot).where(PortfolioSnapshot.ts == now)
    )
    assert written == 2


def test_run_final_settlement_skips_archived_portfolios(session: Session) -> None:
    persona = make_persona(session, name="HYPE")
    portfolio = make_portfolio(session, persona)
    portfolio.archived_at = datetime.datetime(2026, 7, 26, 12, 0)
    session.flush()

    result = run_final_settlement(
        session, _adapter_factory(HYPE=_FakeAdapter()), datetime.datetime(2026, 9, 18, 20, 35)
    )

    assert result.personas == []


def test_run_final_settlement_reports_a_failing_portfolio_and_settles_the_rest(
    session: Session,
) -> None:
    """Five valuations plus a named gap beats none — the run must not abort."""
    for name in ("CONTRA", "CRYPTOR"):
        make_portfolio(session, make_persona(session, name=name))
    session.flush()

    result = run_final_settlement(
        session,
        _adapter_factory(CONTRA=_FakeAdapter(), CRYPTOR=_FakeAdapter(fail=True)),
        datetime.datetime(2026, 9, 18, 20, 35),
    )

    assert result.personas == ["CONTRA"]
    assert result.failed == ["CRYPTOR"]


def test_settlement_snapshot_id_picks_the_last_snapshot_before_the_cutoff(
    session: Session,
) -> None:
    portfolio = make_portfolio(session, make_persona(session, name="CHARTIST"))
    make_portfolio_snapshot(session, portfolio, ts=datetime.datetime(2026, 9, 18, 19, 15))
    expected = make_portfolio_snapshot(
        session, portfolio, ts=datetime.datetime(2026, 9, 18, 20, 35), total_value=Decimal("5300")
    )
    # the paper field keeps running after the competition (§4.7)
    make_portfolio_snapshot(session, portfolio, ts=datetime.datetime(2026, 9, 21, 19, 15))
    session.flush()

    assert settlement_snapshot_id(session, portfolio.id, _config()) == expected.id
