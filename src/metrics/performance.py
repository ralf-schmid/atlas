"""Deterministic performance metrics for leaderboards and reports.
No LLM calls. See docs/features/F082-kennzahlen-modul.md §1.

All functions accept and return Decimal for consistency with the DB schema;
internal arithmetic uses float only in sortino_ratio (annualisation with
√252 — acceptable precision loss for a ratio).  Every function documents
its preconditions (min N, empty-input behavior) in the docstring.
"""

from __future__ import annotations

import datetime
import math
import uuid
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.db.models import (
    Decision,
    OrderRecord,
    OrderRecordStatus,
    PortfolioSnapshot,
    PositionSnapshot,
    Review,
)

# ---------------------------------------------------------------------------
# Pure series functions — no DB access
# ---------------------------------------------------------------------------

_MIN_SORTINO_N = 20


def simple_return(values: list[Decimal]) -> float:
    """(last / first) − 1.  Returns 0 for single-element or empty list."""
    if len(values) < 2:
        return 0.0
    first = float(values[0])
    if first == 0:
        return 0.0
    return float(values[-1]) / first - 1.0


def daily_returns(values: list[Decimal]) -> list[float]:
    """Consecutive daily returns from a list of daily close values
    (one value per day, already deduplicated to last-of-day by caller).
    Returns empty list for < 2 values."""
    if len(values) < 2:
        return []
    result: list[float] = []
    for prev, cur in zip(values, values[1:], strict=False):
        p = float(prev)
        if p == 0:
            result.append(0.0)
        else:
            result.append(float(cur) / p - 1.0)
    return result


def sortino_ratio(
    daily_rets: list[float], target: float = 0.0, min_n: int = _MIN_SORTINO_N
) -> float | None:
    """Sortino ratio (annualised by √252) over daily returns.

    Downside deviation = sqrt(Σ min(r−target, 0)² / N), using N (not N−1).

    Returns None if fewer than *min_n* data points, or if no returns fall
    below the target (downside deviation is 0 → undefined ratio).
    """
    if len(daily_rets) < min_n:
        return None

    downside_sq_sum = sum(min(r - target, 0.0) ** 2 for r in daily_rets)
    downside_dev = math.sqrt(downside_sq_sum / len(daily_rets))
    if downside_dev == 0:
        return None

    mean = sum(daily_rets) / len(daily_rets)
    return (mean - target) / downside_dev * math.sqrt(252)


def max_drawdown(values: list[Decimal]) -> float:
    """Maximum peak-to-trough decline over the series.
    Returns 0 for empty / single-element / monotonically increasing series."""
    if not values:
        return 0.0
    peak = float(values[0])
    worst = 0.0
    for v in values:
        fv = float(v)
        if fv > peak:
            peak = fv
        if peak > 0:
            dd = (peak - fv) / peak
            if dd > worst:
                worst = dd
    return worst


def adjusted_return(
    raw_return: float, malus_sum_usd: Decimal | None, start_capital_usd: int
) -> float:
    """Raw return adjusted for slippage malus (F083).
    malus_sum_usd=None or 0 → raw_return unchanged."""
    if malus_sum_usd is None:
        return raw_return
    return raw_return - float(malus_sum_usd) / start_capital_usd


# ---------------------------------------------------------------------------
# DB-backed function
# ---------------------------------------------------------------------------


def daily_portfolio_values(
    session: Session, portfolio_id: uuid.UUID, since: datetime.datetime
) -> list[Decimal]:
    """One value per calendar day — the day's *last* `portfolio_snapshot` — oldest
    first. Cycles write 2-5 snapshots a day; every series metric here (Sortino,
    drawdown, daily returns) is defined on daily closes, not on intraday points."""
    day = func.date(PortfolioSnapshot.ts).label("day")
    stmt = (
        select(PortfolioSnapshot.total_value)
        .distinct(day)
        .where(PortfolioSnapshot.portfolio_id == portfolio_id, PortfolioSnapshot.ts >= since)
        .order_by(day, PortfolioSnapshot.ts.desc())
    )
    return list(session.scalars(stmt).all())


def daily_benchmark_values(session: Session, since: datetime.datetime) -> list[Decimal]:
    """Same day-close reduction for the SPY buy-and-hold benchmark (F081). The
    value is identical across portfolios — every snapshot carries the same
    computed number — so the day's last non-NULL row is the day's benchmark."""
    day = func.date(PortfolioSnapshot.ts).label("day")
    stmt = (
        select(PortfolioSnapshot.benchmark_value)
        .distinct(day)
        .where(PortfolioSnapshot.ts >= since, PortfolioSnapshot.benchmark_value.is_not(None))
        .order_by(day, PortfolioSnapshot.ts.desc())
    )
    return [value for value in session.scalars(stmt).all() if value is not None]


def open_position_count(session: Session, portfolio_id: uuid.UUID) -> int:
    """Non-zero positions at the newest `portfolio_snapshot`.

    Anchored on the portfolio snapshot, never on `max(position_snapshot.ts)`: a
    portfolio holding nothing writes no position rows at all, so the latter keeps
    reporting the last day the persona held something (F101, live-hit in the daily
    digest on 02.08.2026).
    """
    latest_ts = session.scalar(
        select(func.max(PortfolioSnapshot.ts)).where(PortfolioSnapshot.portfolio_id == portfolio_id)
    )
    if latest_ts is None:
        return 0
    stmt = (
        select(func.count())
        .select_from(PositionSnapshot)
        .where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.ts == latest_ts,
            PositionSnapshot.qty != 0,
        )
    )
    return session.scalar(stmt) or 0


def slippage_malus_sum(
    session: Session, portfolio_id: uuid.UUID, since: datetime.datetime
) -> Decimal | None:
    """Σ `review.slippage_malus` (F083) over this portfolio's reviewed decisions.

    Returns None when the portfolio has no review with a malus yet — the
    leaderboard shows "adjusted = raw" plus a hint in that case instead of
    pretending a zero malus is a measured one.
    """
    stmt = (
        select(func.sum(Review.slippage_malus))
        .join(Decision, Decision.id == Review.decision_id)
        .where(Decision.portfolio_id == portfolio_id, Review.reviewed_at >= since)
    )
    return session.scalar(stmt)


def trade_count(session: Session, portfolio_id: uuid.UUID, since: datetime.datetime) -> int:
    """Count FILLED order_records for *portfolio_id* submitted at or after *since*.
    Uses the Decision join for portfolio filtering (OrderRecord has no
    portfolio_id directly — see F082 §1)."""
    stmt = (
        select(func.count(OrderRecord.id))
        .join(Decision, Decision.id == OrderRecord.decision_id)
        .where(
            and_(
                Decision.portfolio_id == portfolio_id,
                OrderRecord.status == OrderRecordStatus.FILLED,
                OrderRecord.submitted_at >= since,
            )
        )
    )
    return session.scalar(stmt) or 0


def spread_method_split(session: Session, since: datetime.datetime) -> tuple[int, int]:
    """(measured, flat) counts of FILLED orders since *since*, across all portfolios.

    F104 started measuring the real bid/ask spread at order time; orders placed
    before that carry `spread_bps IS NULL` and their review falls back to the
    configured flat rate. Historical quotes aren't reconstructible, so the two
    methods coexist until the last pre-F104 order has left the scoring window.
    The weekly report uses this to say so out loud (F104 §2) rather than
    presenting one malus number as if it came from one method.
    """
    stmt = (
        select(
            func.count(OrderRecord.id).filter(OrderRecord.spread_bps.isnot(None)),
            func.count(OrderRecord.id).filter(OrderRecord.spread_bps.is_(None)),
        )
        .join(Decision, Decision.id == OrderRecord.decision_id)
        .where(
            and_(
                OrderRecord.status == OrderRecordStatus.FILLED,
                OrderRecord.submitted_at >= since,
            )
        )
    )
    measured, flat = session.execute(stmt).one()
    return measured or 0, flat or 0


def malus_trade_count(session: Session, portfolio_id: uuid.UUID, since: datetime.datetime) -> int:
    """How many of the portfolio's trades actually carry a slippage malus.

    `slippage_malus_sum` only sums what `review` holds, and a review exists once a
    position closed or a buy passed the intermediate age (F084). Most recent buys
    have neither, so the adjusted return in the leaderboard is systematically
    optimistic — it prices in the friction of the reviewed trades only. Reporting
    this count next to the malus is what keeps that honest (F112).
    """
    stmt = (
        select(func.count(Review.id))
        .join(Decision, Decision.id == Review.decision_id)
        .where(
            and_(
                Decision.portfolio_id == portfolio_id,
                Review.reviewed_at >= since,
                Review.slippage_malus.is_not(None),
            )
        )
    )
    return session.scalar(stmt) or 0
