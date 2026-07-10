"""Structured (JSON) logging setup — CLAUDE.md requires JSON logs correlated via
`cycle_id`/`portfolio_id`; see docs/features/F029-scheduler-logging-alert.md
(security-audit P4). Stdlib `logging` + a small custom formatter, not a new
dependency (structlog) — CLAUDE.md only asks for JSON output.
"""

from __future__ import annotations

import json
import logging

_CORRELATION_FIELDS = ("cycle_id", "portfolio_id", "seq", "market_session", "trading_day")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _CORRELATION_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # httpx logs the full request URL at INFO for every call — for the
    # telegram-bot service that's `https://api.telegram.org/bot<TOKEN>/...`, so
    # TELEGRAM_BOT_TOKEN ends up in plaintext in container logs on every single
    # getUpdates poll (live-confirmed 2026-07-10, F056). WARNING still surfaces
    # real httpx errors, just not the routine per-request line.
    logging.getLogger("httpx").setLevel(logging.WARNING)
