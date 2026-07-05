"""Load and persist HITL state on `decision` rows (JSONB `hitl` + `status`).

Pure callback logic stays in hitl.py; this module is the DB bridge used by bot.py
until the LangGraph orchestrator resumes interrupted runs (Phase 4).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Cycle, Decision, DecisionStatus
from src.telegram.hitl import HitlDecision, HitlOutcome, HitlRequest

_NumericJson = int | float | str | Decimal


def _json_float(value: object, default: float) -> float:
    if isinstance(value, _NumericJson):
        return float(value)
    return default


def mark_hitl_pending(
    session: Session,
    decision: Decision,
    *,
    amount_usd: float,
    requested_at: datetime.datetime | None = None,
) -> None:
    """Called by the orchestrator when a risk-approved decision needs Telegram approval."""
    now = requested_at or datetime.datetime.now(datetime.UTC)
    decision.status = DecisionStatus.HITL_PENDING
    decision.hitl = {
        "required": True,
        "requested_at": now.isoformat(),
        "amount_usd": amount_usd,
    }
    session.add(decision)


def load_pending_decision(
    session: Session, decision_id: uuid.UUID
) -> tuple[Decision, Cycle] | None:
    row = session.execute(
        select(Decision, Cycle)
        .join(Cycle, Decision.cycle_id == Cycle.id)
        .where(Decision.id == decision_id)
    ).one_or_none()
    if row is None:
        return None
    decision, cycle = row
    if decision.status != DecisionStatus.HITL_PENDING:
        return None
    return decision, cycle


def decision_to_hitl_request(decision: Decision, cycle: Cycle) -> HitlRequest:
    hitl = decision.hitl or {}
    requested_at_raw = hitl.get("requested_at")
    if isinstance(requested_at_raw, str):
        created_at = datetime.datetime.fromisoformat(requested_at_raw)
    else:
        created_at = cycle.started_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.UTC)

    stop_loss = _json_float(decision.expected_outcome.get("stop_loss"), 0.0)
    amount_usd = _json_float(
        hitl.get("amount_usd"),
        float(decision.quantity or 0) * stop_loss,
    )

    return HitlRequest(
        decision_id=decision.id,
        instrument=decision.instrument,
        thesis_text=decision.thesis_text,
        amount_usd=amount_usd,
        stop_loss_price=stop_loss,
        created_at=created_at,
    )


def apply_hitl_outcome(
    session: Session, decision: Decision, outcome: HitlOutcome, now: datetime.datetime
) -> None:
    hitl = dict(decision.hitl or {})
    hitl["required"] = True
    hitl["decided_by"] = outcome.decided_by
    hitl["at"] = now.isoformat()
    decision.hitl = hitl
    if outcome.decision == HitlDecision.APPROVED:
        decision.status = DecisionStatus.APPROVED
    else:
        decision.status = DecisionStatus.HITL_REJECTED
    session.add(decision)
