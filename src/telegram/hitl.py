"""HITL approval flow — inline-button callback + 30-minute timeout-is-reject.

See docs/features/F005-telegram-bot.md §2: the timeout is a plain time
comparison with no bypass path, matching ARCHITECTURE.md §5.3
("Timeout 30 Min = Reject").
"""

from __future__ import annotations

import datetime
import enum
import uuid
from dataclasses import dataclass

TIMEOUT = datetime.timedelta(minutes=30)


class HitlDecision(enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class HitlRequest:
    decision_id: uuid.UUID
    instrument: str
    thesis_text: str
    amount_usd: float
    stop_loss_price: float
    created_at: datetime.datetime

    def is_expired(self, now: datetime.datetime) -> bool:
        return now - self.created_at >= TIMEOUT


@dataclass(frozen=True, slots=True)
class HitlOutcome:
    decision: HitlDecision
    decided_by: str  # "user" | "timeout"


def make_callback_data(action: str, decision_id: uuid.UUID) -> str:
    """Callback payload carries the decision id — a button press must only ever be
    able to approve/reject the exact decision its message belongs to, even with
    several HITL requests pending at once."""
    if action not in ("approve", "reject"):
        raise ValueError(f"Unknown HITL action: {action!r}")
    return f"hitl:{action}:{decision_id}"


def parse_callback_data(callback_data: str) -> tuple[str, uuid.UUID]:
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != "hitl" or parts[1] not in ("approve", "reject"):
        raise ValueError(f"Unknown callback_data: {callback_data!r}")
    try:
        decision_id = uuid.UUID(parts[2])
    except ValueError as exc:
        raise ValueError(f"Unknown callback_data: {callback_data!r}") from exc
    return parts[1], decision_id


def process_callback(
    request: HitlRequest, callback_data: str, now: datetime.datetime
) -> HitlOutcome:
    """Timeout is checked before the action — a stale button press after the window
    has closed must not approve anything. A decision-id mismatch always raises."""
    action, decision_id = parse_callback_data(callback_data)
    if decision_id != request.decision_id:
        raise ValueError(
            f"callback decision id {decision_id} does not match request {request.decision_id}"
        )
    if request.is_expired(now):
        return HitlOutcome(decision=HitlDecision.REJECTED, decided_by="timeout")
    if action == "approve":
        return HitlOutcome(decision=HitlDecision.APPROVED, decided_by="user")
    return HitlOutcome(decision=HitlDecision.REJECTED, decided_by="user")


def format_outcome_message(instrument: str, outcome: HitlOutcome) -> str:
    if outcome.decision == HitlDecision.APPROVED:
        return f"✅ Freigabe erteilt: {instrument}."
    if outcome.decided_by == "timeout":
        return f"⏱ Timeout — automatisch abgelehnt: {instrument}."
    return f"❌ Abgelehnt: {instrument}."


def format_approval_message(request: HitlRequest) -> str:
    return (
        f"\U0001f514 Freigabe erforderlich: {request.instrument}\n\n"
        f"These: {request.thesis_text}\n"
        f"Betrag: ${request.amount_usd:,.2f}\n"
        f"Stop-Loss: ${request.stop_loss_price:,.2f}\n\n"
        "Timeout in 30 Min = automatische Ablehnung."
    )
