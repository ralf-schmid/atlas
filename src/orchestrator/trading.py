"""The only code path allowed to place a broker order — see F001 §2 (Invariant #2,
Privilege Separation) and docs/features/F023-trading-agent.md.

Takes an already-loaded, already-`APPROVED` `Decision` row (never free text, never
an LLM response directly) and turns it into a real order + `order_record`.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter, OrderSide
from src.broker.registry import build_spread_provider
from src.db.models import (
    Decision,
    DecisionAction,
    DecisionStatus,
    OrderRecord,
    OrderRecordStatus,
    Portfolio,
)
from src.orchestrator.decision_sizing import round_to_tick

logger = logging.getLogger(__name__)


def measure_spread_bps(symbol: str) -> float | None:
    """F104: the quoted bid/ask spread at order time, in basis points, for the
    slippage malus (`src/review/slippage.py`).

    Read-only market data — this adds no order capability to the trading path
    (Invariant #2), and nothing in the execution depends on the result. Market type
    comes from the symbol, the same "/" convention the rest of the codebase uses
    (`src/api/routes.py::_try_live_price`).
    """
    market = "crypto" if "/" in symbol else "stock"
    return build_spread_provider(market).get_quote_spread_bps(symbol)


def _measured_spread(symbol: str, source: Callable[[str], float | None]) -> Decimal | None:
    """Best effort by contract: a quote outage, an expired market-data key or a
    malformed quote must never keep an approved decision from reaching the broker.
    Logged, not swallowed silently — the WARNING is the entry point if orders start
    showing up without a spread."""
    try:
        bps = source(symbol)
    except Exception:
        logger.warning("F104: spread measurement failed for %s", symbol, exc_info=True)
        return None
    return Decimal(str(round(bps, 4))) if bps is not None else None


def _fill_status(
    filled_at: datetime.datetime | None, fill_price: float | None
) -> OrderRecordStatus:
    """FILLED requires both the timestamp and the price (F096).

    An adapter that reports one without the other has not given us a usable fill;
    leaving the row NEW keeps it in `reconcile_order_fills`' sights instead of
    freezing a half-recorded fill nobody will ever complete.
    """
    return (
        OrderRecordStatus.FILLED
        if filled_at is not None and fill_price is not None
        else OrderRecordStatus.NEW
    )


def execute_decision(
    session: Session,
    decision: Decision,
    broker_adapter: BrokerAdapter,
    broker_type: str,
    spread_source: Callable[[str], float | None] = measure_spread_bps,
) -> OrderRecord:
    if decision.status != DecisionStatus.APPROVED:
        raise ValueError(f"execute_decision requires an APPROVED decision, got {decision.status!r}")

    portfolio = session.get_one(Portfolio, decision.portfolio_id)

    if decision.action == DecisionAction.CLOSE:
        return _execute_close(
            session, decision, portfolio, broker_adapter, broker_type, spread_source
        )

    stop_loss_price = decision.expected_outcome.get("stop_loss_price")
    if not isinstance(stop_loss_price, int | float):
        raise ValueError(f"Decision {decision.id} has no stop_loss_price in expected_outcome")
    if decision.quantity is None:
        raise ValueError(f"Decision {decision.id} has no quantity")

    # F104: measured before the order goes out, so it reflects the book the order
    # actually faced. Never raises (see `_measured_spread`).
    spread_bps = _measured_spread(decision.instrument, spread_source)

    # Defensive re-round (F050): `compute_stop_loss_price` already rounds new
    # decisions, but this also protects decisions persisted before that fix
    # existed and picked up later by `retry_stuck_decisions`.
    result = broker_adapter.place_order(
        decision_id=decision.id,  # type: ignore[arg-type]
        symbol=decision.instrument,
        qty=float(decision.quantity),
        side=OrderSide.BUY,
        stop_loss_price=round_to_tick(float(stop_loss_price)),
    )

    order_record = OrderRecord(
        decision_id=decision.id,
        broker=broker_type,
        broker_order_id=result.entry_order_id,
        mode=portfolio.mode,
        submitted_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        # F075: adapters that know the fill synchronously at placement time
        # (InternalLedgerAdapter) report it via `result.filled_at`/`fill_price` —
        # record it immediately instead of leaving the row NEW forever.
        # AlpacaPaperAdapter never sets these (Alpaca confirms asynchronously);
        # those rows stay NEW until `reconcile_order_fills` polls them.
        # F096: both fields are required for FILLED, not just `filled_at`. Deriving
        # the status from the timestamp alone made "FILLED with no price" a
        # representable state — two such rows exist from 2026-07-12, and everything
        # downstream (review deviation, slippage malus, holdings charts) then reads
        # a fill it cannot price.
        status=_fill_status(result.filled_at, result.fill_price),
        filled_at=result.filled_at,
        fill_price=Decimal(str(result.fill_price)) if result.fill_price is not None else None,
        spread_bps=spread_bps,
        raw={
            "stop_order_id": result.stop_order_id,
            "qty": result.qty,
            "side": result.side.value,
            "stop_loss_price": result.stop_loss_price,
        },
    )
    session.add(order_record)
    decision.status = DecisionStatus.EXECUTED
    session.add(decision)
    session.flush()
    return order_record


def _execute_close(
    session: Session,
    decision: Decision,
    portfolio: Portfolio,
    broker_adapter: BrokerAdapter,
    broker_type: str,
    spread_source: Callable[[str], float | None] = measure_spread_bps,
) -> OrderRecord:
    if decision.quantity is None:
        raise ValueError(f"Decision {decision.id} has no quantity")

    stop_order_ids = _collect_open_stop_order_ids(
        session, decision.portfolio_id, decision.instrument
    )

    spread_bps = _measured_spread(decision.instrument, spread_source)

    result = broker_adapter.close_position(
        decision_id=decision.id,  # type: ignore[arg-type]
        symbol=decision.instrument,
        qty=float(decision.quantity),
        stop_order_ids=stop_order_ids,
    )

    order_record = OrderRecord(
        decision_id=decision.id,
        broker=broker_type,
        broker_order_id=result.order_id,
        mode=portfolio.mode,
        submitted_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        status=_fill_status(result.filled_at, result.fill_price),
        filled_at=result.filled_at,
        fill_price=Decimal(str(result.fill_price)) if result.fill_price is not None else None,
        spread_bps=spread_bps,
        raw={"qty": result.qty, "side": result.side.value, "closed": True},
    )
    session.add(order_record)
    decision.status = DecisionStatus.EXECUTED
    session.add(decision)
    session.flush()
    return order_record


def _collect_open_stop_order_ids(
    session: Session, portfolio_id: uuid.UUID, instrument: str
) -> list[str]:
    """F077: a position can be built from several buy tranches (F071 top-ups),
    each with its own GTC stop-loss order — gather every one so `close_position()`
    cancels all of them, not just the most recently placed."""
    stmt = (
        select(OrderRecord)
        .join(Decision, OrderRecord.decision_id == Decision.id)
        .where(
            Decision.portfolio_id == portfolio_id,
            Decision.instrument == instrument,
            Decision.action == DecisionAction.BUY,
        )
    )
    stop_order_ids: list[str] = []
    for order_record in session.scalars(stmt):
        stop_order_id = (order_record.raw or {}).get("stop_order_id")
        if isinstance(stop_order_id, str) and stop_order_id:
            stop_order_ids.append(stop_order_id)
    return stop_order_ids
