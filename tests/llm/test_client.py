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
