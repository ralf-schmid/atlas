"""See docs/features/F021-persona-analysis-agent.md §3, tests 9-10."""

from __future__ import annotations

from src.orchestrator.llm_decision_schema import parse_llm_decision


def test_parses_plain_json() -> None:
    raw = (
        '{"action": "hold", "instrument": "PORTFOLIO", "thesis_text": "nothing new", '
        '"input_research_ids": ["abc"]}'
    )

    parsed = parse_llm_decision(raw)

    assert parsed is not None
    assert parsed.action == "hold"
    assert parsed.input_research_ids == ["abc"]


def test_parses_json_wrapped_in_code_fence() -> None:
    raw = (
        "```json\n"
        '{"action": "buy", "instrument": "AAPL", "conviction": 0.7, '
        '"thesis_text": "strong signal", "input_research_ids": ["abc", "def"]}\n'
        "```"
    )

    parsed = parse_llm_decision(raw)

    assert parsed is not None
    assert parsed.action == "buy"
    assert parsed.conviction == 0.7
    assert parsed.input_research_ids == ["abc", "def"]


def test_invalid_json_returns_none() -> None:
    assert parse_llm_decision("not json at all") is None


def test_missing_required_field_returns_none() -> None:
    raw = '{"action": "hold"}'  # missing required thesis_text

    assert parse_llm_decision(raw) is None


def test_empty_content_returns_none() -> None:
    """F065/F057: every production `llm_output_parse_error` observed so far was
    an empty completion, not malformed JSON — must not raise, just signal
    "no parse" so the caller's retry (F065) can kick in."""
    assert parse_llm_decision("") is None


def test_parses_json_wrapped_in_uppercase_code_fence() -> None:
    """F065: the original regex was case-sensitive (```json only) and missed a
    ```JSON language tag some models emit."""
    raw = (
        "```JSON\n"
        '{"action": "hold", "instrument": "PORTFOLIO", "thesis_text": "ok", '
        '"input_research_ids": ["abc"]}\n'
        "```"
    )

    parsed = parse_llm_decision(raw)

    assert parsed is not None
    assert parsed.action == "hold"


def test_parses_bare_json_object_preceded_by_prose() -> None:
    """F076: live-confirmed shape (2026-07-15, 3 llm_output_parse_error decisions)
    — the model reasons in German prose first despite the "keine Erklärung
    davor/danach" instruction, then appends one well-formed but unfenced JSON
    object. The old fallback ran json.loads() on the whole string, which fails
    immediately since it isn't pure JSON from character 0, even though a valid
    object is sitting right there."""
    raw = (
        "Keine zusätzlichen Treffer im Pool. Die verfügbaren Datenpunkte zeigen "
        "eine stabile Seitwärtsbewegung ohne klaren Trend.\n\n"
        '{"action": "hold", "instrument": "PORTFOLIO", "thesis_text": "chop regime", '
        '"input_research_ids": ["abc"]}'
    )

    parsed = parse_llm_decision(raw)

    assert parsed is not None
    assert parsed.action == "hold"
    assert parsed.input_research_ids == ["abc"]


def test_parses_bare_json_object_with_leading_and_trailing_prose() -> None:
    raw = (
        "Some reasoning first.\n"
        '{"action": "hold", "instrument": "PORTFOLIO", "thesis_text": "ok", '
        '"input_research_ids": ["abc"]}\n'
        "And a closing remark."
    )

    parsed = parse_llm_decision(raw)

    assert parsed is not None
    assert parsed.action == "hold"


def test_parses_json_wrapped_in_code_fence_with_trailing_prose() -> None:
    """F065: the original regex was anchored (`^...$`), so any text after the
    closing fence (a model sign-off sentence, e.g. "Hope this helps!") broke
    the match entirely even though the JSON itself was well-formed."""
    raw = (
        "```json\n"
        '{"action": "hold", "instrument": "PORTFOLIO", "thesis_text": "ok", '
        '"input_research_ids": ["abc"]}\n'
        "```\n"
        "Hope this helps!"
    )

    parsed = parse_llm_decision(raw)

    assert parsed is not None
    assert parsed.action == "hold"
