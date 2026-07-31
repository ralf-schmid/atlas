"""F093: retry behaviour for the ingestion jobs' outbound HTTP calls."""

from unittest.mock import patch

import httpx
import pytest

from src.ingestion.http_retry import RETRYABLE_STATUSES, get_with_retry

_REQUEST = httpx.Request("GET", "https://example.test/feed")


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=_REQUEST)


def test_returns_first_successful_response_without_sleeping():
    calls = []

    def send() -> httpx.Response:
        calls.append(1)
        return _response(200)

    with patch("src.ingestion.http_retry.time.sleep") as sleep:
        assert get_with_retry(send, label="test").status_code == 200

    assert len(calls) == 1
    sleep.assert_not_called()


def test_retries_read_timeout_and_succeeds_on_second_attempt():
    """The live EDGAR failure mode: sec.gov answers slower than the read timeout
    on one attempt, fine on the next (12x in 30h, see F093)."""
    responses = [httpx.ReadTimeout("timed out"), _response(200)]

    def send() -> httpx.Response:
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with patch("src.ingestion.http_retry.time.sleep"):
        assert get_with_retry(send, label="edgar").status_code == 200

    assert responses == []


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUSES))
def test_retries_every_retryable_status(status: int):
    responses = [_response(status), _response(200)]

    with patch("src.ingestion.http_retry.time.sleep"):
        assert get_with_retry(lambda: responses.pop(0), label="test").status_code == 200

    assert responses == []


def test_does_not_retry_a_non_retryable_client_error():
    """A genuine 4xx (bad URL, bad auth) repeats forever — retrying only delays
    the alert Ralf actually needs to see."""
    calls = []

    def send() -> httpx.Response:
        calls.append(1)
        return _response(404)

    with patch("src.ingestion.http_retry.time.sleep") as sleep:
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            get_with_retry(send, label="test")

    assert excinfo.value.response.status_code == 404
    assert len(calls) == 1
    sleep.assert_not_called()


def test_extra_retryable_status_is_honoured():
    """CoinGecko's parameterless /global endpoint answered 400 once — it takes no
    request parameters, so that cannot be a genuine client error (F093)."""
    responses = [_response(400), _response(200)]

    with patch("src.ingestion.http_retry.time.sleep"):
        response = get_with_retry(
            lambda: responses.pop(0),
            label="coingecko",
            retryable_statuses=RETRYABLE_STATUSES | {400},
        )

    assert response.status_code == 200


def test_raises_the_last_error_when_every_attempt_fails():
    with patch("src.ingestion.http_retry.time.sleep") as sleep:
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            get_with_retry(lambda: _response(503), label="test")

    assert excinfo.value.response.status_code == 503
    assert sleep.call_count == 2  # 3 attempts, 2 waits in between


def test_raises_the_last_transport_error_when_every_attempt_fails():
    def send() -> httpx.Response:
        raise httpx.ConnectError("no route")

    with patch("src.ingestion.http_retry.time.sleep"):
        with pytest.raises(httpx.ConnectError):
            get_with_retry(send, label="test")


def test_backoff_sequence_defines_the_attempt_count():
    calls = []

    def send() -> httpx.Response:
        calls.append(1)
        return _response(503)

    with patch("src.ingestion.http_retry.time.sleep") as sleep:
        with pytest.raises(httpx.HTTPStatusError):
            get_with_retry(send, label="test", backoff_seconds=(0.1, 0.2, 0.3))

    assert len(calls) == 4
    assert [call.args[0] for call in sleep.call_args_list] == [0.1, 0.2, 0.3]
