"""F110: tolerantes Parsen der LLM-JSON-Antwort. Siehe
docs/features/F110-review-json-trailing-comma.md §3."""

from __future__ import annotations

from src.llm.json_output import excerpt, parse_json_object


def test_parses_plain_json_object() -> None:
    assert parse_json_object('{"verdict":"inconclusive"}') == {"verdict": "inconclusive"}


def test_parses_trailing_comma_before_closing_brace() -> None:
    """Der Live-Fall vom 15.08.2026: die Antwort endete auf `…","}` bei
    finish_reason=stop — kein Abschneiden, sondern ein überzähliges Komma."""
    raw = '{"verdict":"inconclusive","lessons_text":"Die Position wurde geschlossen.",}'

    assert parse_json_object(raw) == {
        "verdict": "inconclusive",
        "lessons_text": "Die Position wurde geschlossen.",
    }


def test_parses_trailing_comma_in_nested_array() -> None:
    assert parse_json_object('{"verdict":"ok","tags":["a","b",],}') == {
        "verdict": "ok",
        "tags": ["a", "b"],
    }


def test_parses_json_wrapped_in_prose_and_a_fence() -> None:
    raw = 'Hier meine Bewertung:\n```json\n{"verdict":"thesis_confirmed"}\n```\nGruß'

    assert parse_json_object(raw) == {"verdict": "thesis_confirmed"}


def test_comma_inside_a_string_value_is_untouched() -> None:
    """Die Regex darf nur strukturelle Kommas treffen — ein `,}` im Fließtext
    einer Lehre wäre sonst weg."""
    raw = '{"lessons_text":"Erst pruefen, dann handeln,}"}'

    assert parse_json_object(raw) == {"lessons_text": "Erst pruefen, dann handeln,}"}


def test_returns_none_without_any_object() -> None:
    assert parse_json_object("Ich kann diese Entscheidung nicht bewerten.") is None


def test_returns_none_for_empty_input() -> None:
    assert parse_json_object("   ") is None


def test_returns_none_for_a_json_array() -> None:
    """Ein Array ist kein Objekt — der Aufrufer erwartet Felder, keine Liste."""
    assert parse_json_object('["a","b"]') is None


def test_excerpt_keeps_head_and_tail() -> None:
    """Die Defekte, um die es geht, sitzen am Ende — ein reiner Prefix hätte den
    Trailing Comma nie gezeigt."""
    text = "A" * 200 + "ENDE,}"

    result = excerpt(text, limit=40)

    assert result.startswith("AAAA")
    assert result.endswith("ENDE,}")
    assert "[…]" in result


def test_excerpt_collapses_whitespace_and_passes_short_text_through() -> None:
    assert excerpt("kurz\n  und   knapp") == "kurz und knapp"
