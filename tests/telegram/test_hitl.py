import datetime

import pytest

from src.telegram.hitl import HitlDecision, HitlRequest, format_approval_message, process_callback

_CREATED_AT = datetime.datetime(2026, 7, 5, 12, 0)


@pytest.fixture
def request_() -> HitlRequest:
    return HitlRequest(
        decision_id=1,
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

    outcome = process_callback(request_, "approve", now)

    assert outcome.decision == HitlDecision.APPROVED
    assert outcome.decided_by == "user"


def test_process_callback_reject_before_timeout(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    outcome = process_callback(request_, "reject", now)

    assert outcome.decision == HitlDecision.REJECTED
    assert outcome.decided_by == "user"


def test_process_callback_after_timeout_rejects_regardless_of_callback(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=31)

    outcome = process_callback(request_, "approve", now)

    assert outcome.decision == HitlDecision.REJECTED
    assert outcome.decided_by == "timeout"


def test_process_callback_unknown_data_raises(request_):
    now = _CREATED_AT + datetime.timedelta(minutes=5)

    with pytest.raises(ValueError, match="Unknown callback_data"):
        process_callback(request_, "banana", now)


def test_format_approval_message_contains_key_fields(request_):
    message = format_approval_message(request_)

    assert "AAPL" in message
    assert "Fair-Value-Abschlag > 15%" in message
    assert "1,500.00" in message
    assert "140.00" in message
