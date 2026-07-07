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


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_llm_decision(raw_content: str) -> PersonaDecisionOutput | None:
    match = _CODE_FENCE_RE.match(raw_content.strip())
    json_text = match.group(1) if match else raw_content.strip()

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    try:
        return PersonaDecisionOutput.model_validate(data)
    except ValidationError:
        return None
