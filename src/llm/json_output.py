"""Tolerant parsing of a JSON object out of an LLM response.

See docs/features/F110-review-json-trailing-comma.md.

Lifted out of `src/review/agent.py` and `src/review/meta_agent.py`, which carried
byte-identical copies — and therefore the same defect: a response ending in
`..."lessons_text":"…",}` (a trailing comma before the closing brace, produced by
the model with `finish_reason: stop`, not a truncation) failed both the strict and
the substring parse, and the review was dropped. Every occurrence cost an LLM call
and a review that the §4.7 scoring never got.
"""

from __future__ import annotations

import json
import re

# `,}` / `,]`, optionally with whitespace or a newline in between. Deliberately not
# a general "repair the JSON" attempt: this is the one malformation observed in
# production (F110 §1), and a parser that guesses at broken output would silently
# turn a garbled verdict into a recorded judgement.
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def parse_json_object(content: str) -> dict[str, object] | None:
    """The first JSON object in `content`, or None.

    Three passes, each strictly more forgiving than the last: the whole string, the
    outermost `{...}` span (drops prose or a markdown fence around it), and the same
    span with trailing commas removed.
    """
    text = content.strip()
    if not text:
        return None

    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        span = text[start : end + 1]
        candidates.append(span)
        candidates.append(_TRAILING_COMMA.sub(r"\1", span))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def excerpt(content: str, limit: int = 300) -> str:
    """Short, log-safe rendering of a response for a parse-failure message.

    Without this the raw output was thrown away with the exception, so the only
    record of *why* a review failed was "no JSON object" — which is exactly what
    made F110 take a live capture to diagnose. Head and tail, because the defects
    worth seeing sit at the end.
    """
    text = " ".join(content.split())
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]} […] {text[-half:]}"
