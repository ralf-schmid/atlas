"""Assembles real Risk-Gate inputs (src.risk.gate.evaluate_decision) from the real
BrokerAdapter + order/decision history. See
docs/features/F020-portfolio-risk-inputs.md.
"""

from __future__ import annotations

import datetime
import uuid
import zoneinfo
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter
from src.db.models import Cycle, Decision, MarketSession, OrderRecord, PortfolioSnapshot
from src.orchestrator.cycles_config import load_cycles_config


@dataclass(frozen=True, slots=True)
class PortfolioRiskState:
    equity_usd: float
    cash_usd: float
    peak_equity_usd: float
    open_positions_count: int
    trades_today_count: int


def read_portfolio_risk_state(
    session: Session,
    adapter: BrokerAdapter,
    portfolio_id: uuid.UUID,
    cycle_id: uuid.UUID,
) -> PortfolioRiskState:
    balance = adapter.get_account_balance()
    positions = adapter.get_positions()

    historical_peak = session.scalar(
        select(func.max(PortfolioSnapshot.total_value)).where(
            PortfolioSnapshot.portfolio_id == portfolio_id
        )
    )
    peak_equity_usd = max(balance.equity, float(historical_peak or 0.0))

    trades_today_count = _count_trades_today(session, portfolio_id, cycle_id)

    return PortfolioRiskState(
        equity_usd=balance.equity,
        cash_usd=balance.cash,
        peak_equity_usd=peak_equity_usd,
        open_positions_count=len(positions),
        trades_today_count=trades_today_count,
    )


def _count_trades_today(session: Session, portfolio_id: uuid.UUID, cycle_id: uuid.UUID) -> int:
    # security-audit P7: "today" must be the market's trading day, not the UTC (or
    # host-local) calendar day — a stock cycle just before/after midnight UTC would
    # otherwise count trades from the wrong day. `Cycle.trading_day` is already
    # computed in the market timezone by the scheduler (F025); reuse it instead of
    # re-deriving a day boundary from a raw timestamp.
    cycle = session.get_one(Cycle, cycle_id)
    tz = zoneinfo.ZoneInfo(_market_timezone(cycle.market_session))
    local_midnight = datetime.datetime.combine(cycle.trading_day, datetime.time.min, tzinfo=tz)
    start = local_midnight.astimezone(datetime.UTC).replace(tzinfo=None)
    end = (
        (local_midnight + datetime.timedelta(days=1)).astimezone(datetime.UTC).replace(tzinfo=None)
    )

    stmt = (
        select(func.count())
        .select_from(OrderRecord)
        .join(Decision, OrderRecord.decision_id == Decision.id)
        .where(
            Decision.portfolio_id == portfolio_id,
            OrderRecord.submitted_at >= start,
            OrderRecord.submitted_at < end,
        )
    )
    return int(session.scalar(stmt) or 0)


def _market_timezone(market_session: MarketSession) -> str:
    cycles_config = load_cycles_config()
    if market_session == MarketSession.CRYPTO:
        return cycles_config.crypto_timezone
    return cycles_config.stock_timezone
