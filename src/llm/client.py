"""Thin client against the self-hosted LiteLLM proxy (OpenAI-compatible).

Reads cost per request from LiteLLM's own `x-litellm-response-cost` response
header rather than maintaining a duplicate per-model price table in this repo
(see F006 §2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    tool_calls: tuple[ToolCall, ...] = ()


# httpx defaults to a 5s read timeout — far too short for LLM completions, which
# routinely take longer (Sonnet analysis calls especially). Generous read timeout,
# tight connect timeout so a dead proxy still fails fast. 300s (not 120) because
# the LiteLLM proxy retries provider rate limits (429) internally for ~2 minutes
# before answering — live-measured against Groq's 12k-TPM free tier (F046); a
# shorter read timeout turns every such retry window into a lost response.
_DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class LiteLLMClient:
    def __init__(
        self, base_url: str, api_key: str, http_client: httpx.Client | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http_client or httpx.Client(timeout=_DEFAULT_TIMEOUT)

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResponse:
        body: dict[str, object] = {"model": model, "messages": messages}
        if tools is not None:
            body["tools"] = tools
        response = self._http.post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        data = response.json()
        usage = data["usage"]
        cost_usd = _parse_cost_header(response.headers.get("x-litellm-response-cost"))
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = tuple(_parse_tool_call(raw) for raw in message.get("tool_calls") or [])
        return LLMResponse(
            content=str(content),
            tokens_in=int(usage["prompt_tokens"]),
            tokens_out=int(usage["completion_tokens"]),
            cost_usd=cost_usd,
            tool_calls=tool_calls,
        )


def _parse_tool_call(raw: dict[str, object]) -> ToolCall:
    function = raw["function"]
    assert isinstance(function, dict)
    return ToolCall(
        id=str(raw["id"]),
        name=str(function["name"]),
        arguments_json=str(function["arguments"]),
    )


def _parse_cost_header(raw: str | None) -> float:
    """The LLM call is already billed by the time this header is read — a missing
    or unparseable value must not lose the response (and with it, the caller's
    ability to still write *some* cost_ledger row); see security-audit P7. Default
    to 0.0 and log an incident instead of raising.
    """
    if raw is None:
        logger.error("x-litellm-response-cost header missing from LiteLLM response")
        return 0.0
    try:
        return float(raw)
    except ValueError:
        logger.error("x-litellm-response-cost header unparseable: %r", raw)
        return 0.0
