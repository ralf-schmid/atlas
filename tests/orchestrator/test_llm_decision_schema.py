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
