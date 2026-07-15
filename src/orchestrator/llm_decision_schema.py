"""Structured-output schema for the persona-analysis LLM response, and robust
parsing of it. See docs/features/F021-persona-analysis-agent.md §2/§3.

Deliberately no arithmetic here — `conviction` is the only number the LLM supplies,
and it's a 0-1 self-assessment, not a dollar amount or price (see decision_sizing.py).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError


class PersonaDecisionOutput(BaseModel):
    action: str  # "buy" | "hold" | "reject_idea" — validated against DecisionAction by the caller
    instrument: str | None = None
    conviction: float | None = None
    thesis_text: str
    rejection_reason: str | None = None
    input_research_ids: list[str] = []


# F065: not anchored (`^...$`) and case-insensitive — the original pattern
# missed a code fence with an uppercase language tag (```JSON) and broke on
# any trailing prose after the closing fence (e.g. a sign-off sentence),
# because `.match()` requires the whole stripped string to be exactly one
# fenced block. `.search()` finds the fenced block wherever it sits and
# ignores text before/after it, which is what "one JSON object, ignore
# everything else the model added" actually means.
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

# F076: no code fence at all — the model sometimes reasons in prose first
# ("Keine zusätzlichen Treffer im Pool...") despite the prompt's "ausschließlich
# ein JSON-Objekt, keine Erklärung davor/danach", then appends one raw,
# well-formed JSON object with no fence around it (live-confirmed, 2026-07-15:
# 3 llm_output_parse_error decisions all had this exact shape — real content,
# real valid JSON, just prefixed by prose). The old fallback ran `json.loads()`
# on the *whole* string, which fails immediately once it isn't pure JSON from
# character 0. `.search()` (not `.find`/slicing) so it still ignores anything
# after the object too, matching the code-fence path's "ignore everything else"
# contract; DOTALL so the object's own newlines don't stop the match; greedy
# `.*` deliberately reaches the *last* `}` in the string, not the first nested
# one, since `input_research_ids`/thesis_text can't legally contain braces in
# this schema.
_BARE_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_llm_decision(raw_content: str) -> PersonaDecisionOutput | None:
    stripped = raw_content.strip()
    fence_match = _CODE_FENCE_RE.search(stripped)
    if fence_match is not None:
        json_text = fence_match.group(1)
    else:
        json_text = stripped

    data = _try_parse_json(json_text)
    if data is None and fence_match is None:
        # F076: no fence and the whole string wasn't valid JSON either — try
        # pulling just the `{...}` object out of whatever prose surrounds it.
        bare_match = _BARE_JSON_OBJECT_RE.search(stripped)
        if bare_match is not None:
            data = _try_parse_json(bare_match.group(0))
    if data is None:
        return None

    try:
        return PersonaDecisionOutput.model_validate(data)
    except ValidationError:
        return None


def _try_parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
