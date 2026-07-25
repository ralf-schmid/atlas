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

from src.db.models import Decision, OrderRecord, OrderRecordStatus

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
