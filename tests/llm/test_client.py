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
