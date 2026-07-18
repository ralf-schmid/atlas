"""The only code path allowed to place a broker order — see F001 §2 (Invariant #2,
Privilege Separation) and docs/features/F023-trading-agent.md.

Takes an already-loaded, already-`APPROVED` `Decision` row (never free text, never
an LLM response directly) and turns it into a real order + `order_record`.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import BrokerAdapter, OrderSide
from src.db.models import (
    Decision,
    DecisionAction,
    DecisionStatus,
    OrderRecord,
    OrderRecordStatus,
    Portfolio,
)
from src.orchestrator.decision_sizing import round_to_tick


def execute_decision(
    session: Session, decision: Decision, broker_adapter: BrokerAdapter, broker_type: str
) -> OrderRecord:
    if decision.status != DecisionStatus.APPROVED:
        raise ValueError(f"execute_decision requires an APPROVED decision, got {decision.status!r}")

    portfolio = session.get_one(Portfolio, decision.portfolio_id)

    if decision.action == DecisionAction.CLOSE:
        return _execute_close(session, decision, portfolio, broker_adapter, broker_type)

    stop_loss_price = decision.expected_outcome.get("stop_loss_price")
    if not isinstance(stop_loss_price, int | float):
        raise ValueError(f"Decision {decision.id} has no stop_loss_price in expected_outcome")
    if decision.quantity is None:
        raise ValueError(f"Decision {decision.id} has no quantity")

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
        status=OrderRecordStatus.FILLED if result.filled_at is not None else OrderRecordStatus.NEW,
        filled_at=result.filled_at,
        fill_price=Decimal(str(result.fill_price)) if result.fill_price is not None else None,
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
) -> OrderRecord:
    if decision.quantity is None:
        raise ValueError(f"Decision {decision.id} has no quantity")

    stop_order_ids = _collect_open_stop_order_ids(
        session, decision.portfolio_id, decision.instrument
    )

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
        status=OrderRecordStatus.FILLED if result.filled_at is not None else OrderRecordStatus.NEW,
        filled_at=result.filled_at,
        fill_price=Decimal(str(result.fill_price)) if result.fill_price is not None else None,
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
