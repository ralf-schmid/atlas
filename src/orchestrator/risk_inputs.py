"""Assembles real Risk-Gate inputs (src.risk.gate.evaluate_decision) from the real
BrokerAdapter + order/decision history. See
docs/features/F020-portfolio-risk-inputs.md.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter
from src.db.models import Decision, OrderRecord, PortfolioSnapshot


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
    now: datetime.datetime,
) -> PortfolioRiskState:
    balance = adapter.get_account_balance()
    positions = adapter.get_positions()

    historical_peak = session.scalar(
        select(func.max(PortfolioSnapshot.total_value)).where(
            PortfolioSnapshot.portfolio_id == portfolio_id
        )
    )
    peak_equity_usd = max(balance.equity, float(historical_peak or 0.0))

    trades_today_count = _count_trades_today(session, portfolio_id, now)

    return PortfolioRiskState(
        equity_usd=balance.equity,
        cash_usd=balance.cash,
        peak_equity_usd=peak_equity_usd,
        open_positions_count=len(positions),
        trades_today_count=trades_today_count,
    )


def _count_trades_today(session: Session, portfolio_id: uuid.UUID, now: datetime.datetime) -> int:
    start = datetime.datetime(now.year, now.month, now.day)
    end = start + datetime.timedelta(days=1)
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
