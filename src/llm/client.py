"""Thin client against the self-hosted LiteLLM proxy (OpenAI-compatible).

Reads cost per request from LiteLLM's own `x-litellm-response-cost` response
header rather than maintaining a duplicate per-model price table in this repo
(see F006 §2).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class LiteLLMClient:
    def __init__(
        self, base_url: str, api_key: str, http_client: httpx.Client | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http_client or httpx.Client()

    def complete(self, *, model: str, messages: list[dict[str, str]]) -> LLMResponse:
        response = self._http.post(
            f"{self._base_url}/chat/completions",
            json={"model": model, "messages": messages},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        data = response.json()
        usage = data["usage"]
        cost_usd = float(response.headers.get("x-litellm-response-cost", "0.0"))
        content = str(data["choices"][0]["message"]["content"])
        return LLMResponse(
            content=content,
            tokens_in=int(usage["prompt_tokens"]),
            tokens_out=int(usage["completion_tokens"]),
            cost_usd=cost_usd,
        )
