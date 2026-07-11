"""Structured-output schema for the persona-analysis LLM response, and robust
parsing of it. See docs/features/F021-persona-analysis-agent.md §2/§3.

Deliberately no arithmetic here — `conviction` is the only number the LLM supplies,
and it's a 0-1 self-assessment, not a dollar amount or price (see decision_sizing.py).
"""

from __future__ import annotations

import json
import re

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


def parse_llm_decision(raw_content: str) -> PersonaDecisionOutput | None:
    match = _CODE_FENCE_RE.search(raw_content.strip())
    json_text = match.group(1) if match else raw_content.strip()

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    try:
        return PersonaDecisionOutput.model_validate(data)
    except ValidationError:
        return None
