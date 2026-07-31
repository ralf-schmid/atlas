import json

import httpx

from src.llm.client import LiteLLMClient


def _mock_client(response_json: dict, cost_header: str = "0.0123") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200, json=response_json, headers={"x-litellm-response-cost": cost_header}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_complete_sends_expected_request_and_parses_response():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_mock_client(response_json),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert result.tokens_in == 100
    assert result.tokens_out == 20
    assert result.cost_usd == 0.0123


def test_complete_defaults_cost_to_zero_when_header_missing():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.cost_usd == 0.0


def test_complete_defaults_cost_to_zero_when_header_unparseable():
    """security-audit P7: a malformed header must not raise and lose the whole
    response — the call is already billed by this point."""
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_mock_client(response_json, cost_header="not-a-number"),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.cost_usd == 0.0
    assert result.content == "hello"


def test_complete_sends_tools_when_given():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(httpx_json(request))
        return httpx.Response(200, json=response_json, headers={"x-litellm-response-cost": "0.01"})

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

    client.complete(
        model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}], tools=tools
    )

    assert captured_bodies[0]["tools"] == tools


def test_complete_omits_tools_key_when_not_given():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(httpx_json(request))
        return httpx.Response(200, json=response_json, headers={"x-litellm-response-cost": "0.01"})

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert "tools" not in captured_bodies[0]


def test_complete_sends_tool_choice_when_given():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(httpx_json(request))
        return httpx.Response(200, json=response_json, headers={"x-litellm-response-cost": "0.01"})

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

    client.complete(
        model="claude-sonnet-5",
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        tool_choice="none",
    )

    assert captured_bodies[0]["tool_choice"] == "none"


def test_complete_omits_tool_choice_key_when_not_given():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(httpx_json(request))
        return httpx.Response(200, json=response_json, headers={"x-litellm-response-cost": "0.01"})

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert "tool_choice" not in captured_bodies[0]


def test_complete_sends_thinking_when_given():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(httpx_json(request))
        return httpx.Response(200, json=response_json, headers={"x-litellm-response-cost": "0.01"})

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.complete(
        model="claude-sonnet-5",
        messages=[{"role": "user", "content": "hi"}],
        thinking={"type": "disabled"},
    )

    assert captured_bodies[0]["thinking"] == {"type": "disabled"}


def test_complete_omits_thinking_key_when_not_given():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(httpx_json(request))
        return httpx.Response(200, json=response_json, headers={"x-litellm-response-cost": "0.01"})

    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert "thinking" not in captured_bodies[0]


def test_complete_parses_tool_calls_from_response():
    response_json = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "search_research_pool",
                                "arguments": '{"symbols": ["AAPL"]}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_mock_client(response_json),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.content == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "search_research_pool"
    assert result.tool_calls[0].arguments_json == '{"symbols": ["AAPL"]}'


def test_complete_captures_finish_reason():
    response_json = {
        "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_mock_client(response_json),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason == "stop"


def test_complete_finish_reason_is_none_when_absent():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_mock_client(response_json),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason is None


def test_complete_returns_empty_tool_calls_when_absent():
    response_json = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_mock_client(response_json),
    )

    result = client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])

    assert result.tool_calls == ()


def httpx_json(request: httpx.Request) -> dict:
    return json.loads(request.content)


def _error_client(status: int, body: str) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    )


def test_http_error_message_carries_the_response_body():
    """F093: LiteLLM answers a rejected upstream call with a bare 400 — the reason
    lives only in the body. Live, 34h of failed cycles logged nothing but
    "Client error '400 Bad Request'" while the body named the actual cause."""
    body = (
        '{"error":{"message":"Your credit balance is too low to access the '
        'Anthropic API.","type":"invalid_request_error"}}'
    )
    client = LiteLLMClient(
        base_url="http://localhost:4000", api_key="test-key", http_client=_error_client(400, body)
    )

    try:
        client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])
    except httpx.HTTPStatusError as exc:
        assert "400 Bad Request" in str(exc)
        assert "credit balance is too low" in str(exc)
        assert exc.response.status_code == 400
    else:
        raise AssertionError("expected HTTPStatusError")


def test_http_error_body_is_truncated():
    client = LiteLLMClient(
        base_url="http://localhost:4000",
        api_key="test-key",
        http_client=_error_client(500, "x" * 5_000),
    )

    try:
        client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])
    except httpx.HTTPStatusError as exc:
        assert len(str(exc)) < 2_000
    else:
        raise AssertionError("expected HTTPStatusError")


def test_http_error_with_empty_body_still_raises_the_original_error():
    client = LiteLLMClient(
        base_url="http://localhost:4000", api_key="test-key", http_client=_error_client(502, "")
    )

    try:
        client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])
    except httpx.HTTPStatusError as exc:
        assert "Response body" not in str(exc)
        assert exc.response.status_code == 502
    else:
        raise AssertionError("expected HTTPStatusError")


def test_error_body_survives_the_cycle_alert_cause_walk():
    """Regression (F093): `format_cycle_failure_cause` walks to the innermost
    `__cause__` to get past LangGraph's wrapping. Chaining a *new* enriched
    exception here put the body on the outer one and handed the alert the bare
    original back — caught live on the box, the alert read only
    "Client error '400 Bad Request'"."""
    from src.orchestrator.scheduler import format_cycle_failure_cause

    body = '{"error":{"message":"Your credit balance is too low."}}'
    client = LiteLLMClient(
        base_url="http://localhost:4000", api_key="test-key", http_client=_error_client(400, body)
    )

    try:
        try:
            client.complete(model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}])
        except httpx.HTTPStatusError as inner:
            raise RuntimeError("During task with name 'persona_analysis'") from inner
    except RuntimeError as outer:
        cause = format_cycle_failure_cause(outer)

    assert "credit balance is too low" in cause
