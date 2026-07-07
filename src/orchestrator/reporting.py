"""Reporting-Agent — the last graph stage per ARCHITECTURE.md §5.1 ("... ->
Handels-Agent -> Reporting"). See docs/features/F024-reporting-agent.md.

Pure code (sums/differences from broker data), no LLM calls.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter
from src.db.models import PortfolioSnapshot, PositionSnapshot


def generate_portfolio_snapshot(
    session: Session,
    portfolio_id: uuid.UUID,
    broker_adapter: BrokerAdapter,
    now: datetime.datetime,
) -> PortfolioSnapshot:
    balance = broker_adapter.get_account_balance()
    positions = broker_adapter.get_positions()

    for position in positions:
        session.add(
            PositionSnapshot(
                ts=now,
                portfolio_id=portfolio_id,
                instrument=position.symbol,
                qty=Decimal(str(position.qty)),
                avg_price=Decimal(str(position.avg_entry_price)),
                market_value=Decimal(str(position.market_value)),
                pnl_unrealized=Decimal(str(position.unrealized_pl)),
            )
        )

    pnl_unrealized = sum((p.unrealized_pl for p in positions), start=0.0)

    historical_peak = session.scalar(
        select(func.max(PortfolioSnapshot.total_value)).where(
            PortfolioSnapshot.portfolio_id == portfolio_id
        )
    )
    peak_equity = max(balance.equity, float(historical_peak or 0.0))
    max_drawdown = (peak_equity - balance.equity) / peak_equity if peak_equity > 0 else 0.0

    snapshot = PortfolioSnapshot(
        ts=now,
        portfolio_id=portfolio_id,
        total_value=Decimal(str(balance.equity)),
        cash=Decimal(str(balance.cash)),
        pnl_realized=Decimal("0"),  # no sell/close path yet — see F021 §1, F024 §1
        pnl_unrealized=Decimal(str(pnl_unrealized)),
        benchmark_value=None,  # SPY benchmark portfolio is P5 scope, ARCHITECTURE.md §8
        max_drawdown=Decimal(str(max_drawdown)),
    )
    session.add(snapshot)
    session.flush()
    return snapshot
