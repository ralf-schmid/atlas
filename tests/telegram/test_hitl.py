import datetime
import uuid

import pytest

from src.telegram.hitl import (
    HitlDecision,
    HitlRequest,
    format_approval_message,
    format_outcome_message,
    make_callback_data,
    process_callback,
)

_DECISION_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
_CREATED_AT = datetime.datetime(2026, 7, 5, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture
def request_() -> HitlRequest:
    return HitlRequest(
        decision_id=_DECISION_ID,
        persona_name="VULTURE",
        instrument="AAPL",
        thesis_text="Fair-Value-Abschlag > 15%",
        amount_usd=1500.0,
        stop_loss_price=140.0,
        created_at=_CREATED_AT,
    )


def test_is_expired_false_before_timeout(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=29)

    assert request_.is_expired(now) is False


def test_is_expired_true_after_timeout(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=30)

    assert request_.is_expired(now) is True


def test_process_callback_approve_before_timeout(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    outcome = process_callback(request_, f"hitl:approve:{_DECISION_ID}", now)

    assert outcome.decision == HitlDecision.APPROVED
    assert outcome.decided_by == "user"


def test_process_callback_reject_before_timeout(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    outcome = process_callback(request_, f"hitl:reject:{_DECISION_ID}", now)

    assert outcome.decision == HitlDecision.REJECTED
    assert outcome.decided_by == "user"


def test_process_callback_after_timeout_rejects_regardless_of_callback(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=31)

    outcome = process_callback(request_, f"hitl:approve:{_DECISION_ID}", now)

    assert outcome.decision == HitlDecision.REJECTED
    assert outcome.decided_by == "timeout"


def test_process_callback_unknown_data_raises(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    with pytest.raises(ValueError, match="Unknown callback_data"):
        process_callback(request_, "banana", now)


def test_process_callback_non_numeric_decision_id_raises(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    with pytest.raises(ValueError, match="Unknown callback_data"):
        process_callback(request_, "hitl:approve:banana", now)


def test_process_callback_mismatched_decision_id_raises(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    with pytest.raises(ValueError, match="does not match"):
        process_callback(request_, f"hitl:approve:{uuid.uuid4()}", now)


def test_make_callback_data_round_trips():
    decision_id = uuid.UUID("00000000-0000-0000-0000-000000000007")
    assert make_callback_data("approve", decision_id) == f"hitl:approve:{decision_id}"
    assert make_callback_data("reject", decision_id) == f"hitl:reject:{decision_id}"


def test_make_callback_data_unknown_action_raises():
    with pytest.raises(ValueError, match="Unknown HITL action"):
        make_callback_data("delete", _DECISION_ID)


def test_format_outcome_message_approve():
    outcome = process_callback(
        HitlRequest(
            decision_id=_DECISION_ID,
            persona_name="VULTURE",
            instrument="AAPL",
            thesis_text="x",
            amount_usd=1.0,
            stop_loss_price=1.0,
            created_at=_CREATED_AT,
        ),
        f"hitl:approve:{_DECISION_ID}",
        _CREATED_AT,
    )
    message = format_outcome_message("VULTURE", "AAPL", outcome)
    assert "Freigabe erteilt" in message
    assert "VULTURE" in message


def test_format_outcome_message_timeout():
    outcome = process_callback(
        HitlRequest(
            decision_id=_DECISION_ID,
            persona_name="VULTURE",
            instrument="AAPL",
            thesis_text="x",
            amount_usd=1.0,
            stop_loss_price=1.0,
            created_at=_CREATED_AT,
        ),
        f"hitl:approve:{_DECISION_ID}",
        _CREATED_AT + datetime.timedelta(minutes=31),
    )
    message = format_outcome_message("VULTURE", "AAPL", outcome)
    assert "Timeout" in message
    assert "VULTURE" in message


def test_format_approval_message_contains_key_fields(request_):
    message = format_approval_message(request_)

    assert "VULTURE" in message
    assert "AAPL" in message
    assert "Fair-Value-Abschlag > 15%" in message
    assert "1,500.00" in message
    assert "140.00" in message
