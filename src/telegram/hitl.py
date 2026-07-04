"""HITL approval flow — inline-button callback + 30-minute timeout-is-reject.

See docs/features/F005-telegram-bot.md §2: the timeout is a plain time
comparison with no bypass path, matching ARCHITECTURE.md §5.3
("Timeout 30 Min = Reject").
"""

from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass

TIMEOUT = datetime.timedelta(minutes=30)


class HitlDecision(enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class HitlRequest:
    decision_id: int
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


def process_callback(
    request: HitlRequest, callback_data: str, now: datetime.datetime
) -> HitlOutcome:
    """Timeout is checked first and wins regardless of callback_data — a stale
    button press after the window has closed must not approve anything."""
    if request.is_expired(now):
        return HitlOutcome(decision=HitlDecision.REJECTED, decided_by="timeout")
    if callback_data == "approve":
        return HitlOutcome(decision=HitlDecision.APPROVED, decided_by="user")
    if callback_data == "reject":
        return HitlOutcome(decision=HitlDecision.REJECTED, decided_by="user")
    raise ValueError(f"Unknown callback_data: {callback_data!r}")


def format_approval_message(request: HitlRequest) -> str:
    return (
        f"\U0001f514 Freigabe erforderlich: {request.instrument}\n\n"
        f"These: {request.thesis_text}\n"
        f"Betrag: ${request.amount_usd:,.2f}\n"
        f"Stop-Loss: ${request.stop_loss_price:,.2f}\n\n"
        "Timeout in 30 Min = automatische Ablehnung."
    )
