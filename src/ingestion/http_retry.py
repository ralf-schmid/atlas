"""Retry helper for the ingestion jobs' outbound HTTP calls (F093).

Ingestion jobs run unattended on a schedule and alert Ralf on two consecutive
failures. Without a retry, every transient upstream hiccup — sec.gov answering
slower than the read timeout, CoinGecko's free tier throttling a request — turns
into a job failure and eventually a Telegram alert, even though the very next
scheduled run succeeds. Live-measured over 30h: 12 EDGAR read timeouts, 2
CoinGecko 5xx/4xx, all transient.

Takes a `send` callable rather than doing the `httpx.get` itself so each caller
keeps its own request construction (URL, headers, timeout) — and so the existing
per-module tests that patch `src.ingestion.<module>.httpx.get` keep working.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

import httpx

logger = logging.getLogger(__name__)

#: Statuses that mean "upstream is busy/broken right now", not "the request was
#: wrong". 4xx is deliberately absent — a genuine client error repeats forever.
RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

#: Waits *between* attempts, so len(backoff) + 1 attempts in total. Deliberately
#: short: the ingestion scheduler runs these jobs on 30-60 min intervals, so a
#: retry window of a few seconds is free, and a long one would overlap the next run.
_DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 5.0)


def get_with_retry(
    send: Callable[[], httpx.Response],
    *,
    label: str,
    retryable_statuses: frozenset[int] | set[int] = RETRYABLE_STATUSES,
    backoff_seconds: Sequence[float] = _DEFAULT_BACKOFF_SECONDS,
) -> httpx.Response:
    """Calls `send`, retrying transport errors and `retryable_statuses`.

    Returns the first response whose status is not retryable, with
    `raise_for_status()` already applied — so a non-retryable 4xx still raises
    `httpx.HTTPStatusError` on the first attempt, exactly as before. When every
    attempt fails, the last exception propagates unchanged: callers and the
    scheduler's failure alert keep seeing the real upstream error.
    """
    last_exc: Exception | None = None
    waits: list[float | None] = [*backoff_seconds, None]
    for attempt, wait in enumerate(waits):
        try:
            response = send()
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code not in retryable_statuses
            ):
                raise
            last_exc = exc
        if wait is None:
            break
        logger.warning(
            "%s attempt %d/%d failed, retrying in %.1fs",
            label,
            attempt + 1,
            len(backoff_seconds) + 1,
            wait,
            extra={"retry_label": label, "attempt": attempt + 1},
        )
        time.sleep(wait)

    assert last_exc is not None  # loop only exits here after a failed attempt
    raise last_exc
