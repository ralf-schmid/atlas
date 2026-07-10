"""See docs/features/F029-scheduler-logging-alert.md §3, test 4."""

from __future__ import annotations

import json
import logging

from src.logging_config import JsonFormatter, configure_logging


def _make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="src.orchestrator.scheduler",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="cycle failed",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_produces_valid_json_with_correlation_fields() -> None:
    record = _make_record(seq=1, market_session="us_equity", cycle_id="abc-123")

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "ERROR"
    assert payload["logger"] == "src.orchestrator.scheduler"
    assert payload["message"] == "cycle failed"
    assert payload["seq"] == 1
    assert payload["market_session"] == "us_equity"
    assert payload["cycle_id"] == "abc-123"


def test_json_formatter_omits_absent_correlation_fields() -> None:
    record = _make_record()

    payload = json.loads(JsonFormatter().format(record))

    assert "cycle_id" not in payload
    assert "seq" not in payload


def test_configure_logging_suppresses_httpx_info_logs() -> None:
    # F056: httpx logs the full request URL at INFO — for the telegram-bot
    # service that includes TELEGRAM_BOT_TOKEN in plaintext (part of Telegram's
    # API URL path), on every single getUpdates poll.
    configure_logging()

    assert logging.getLogger("httpx").level == logging.WARNING
