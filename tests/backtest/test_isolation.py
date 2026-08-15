"""Leitplanken 1-3 as automatic tests — F111 §8, tests 24-25.

These are not style checks. They are the difference between an invariant that is
written down and one that holds: without them, the first convenient import from a
persona agent into the backtest module would quietly create the cost and fairness
asymmetry ADR-0015 rejected the whole feature over.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
_PERSONA_PATH_DIRS = ("orchestrator", "agents", "personas", "api", "telegram")


def _python_files(*relative: str) -> list[Path]:
    files: list[Path] = []
    for name in relative:
        directory = _SRC / name
        if directory.exists():
            files.extend(sorted(directory.rglob("*.py")))
    return files


def test_the_persona_path_cannot_reach_the_backtest() -> None:
    """Test 24 — Leitplanke 2 (Invarianten #2 und #10).

    No persona may trigger a backtest or see its result: one persona holding an
    edge the others lack destroys the comparison the eight-week experiment is.
    """
    offenders = [
        path
        for path in _python_files(*_PERSONA_PATH_DIRS)
        if re.search(r"^\s*(from|import)\s+src\.backtest", path.read_text(), re.MULTILINE)
    ]
    assert not offenders, f"backtest imported from the persona/UI path: {offenders}"


def test_the_backtest_has_no_broker_access() -> None:
    """Test 25a — Leitplanke 3. The module reads bars and writes results. It must not
    be able to place an order even by accident."""
    offenders = [
        path
        for path in _python_files("backtest")
        if re.search(r"^\s*(from|import)\s+src\.broker", path.read_text(), re.MULTILINE)
    ]
    assert not offenders, f"backtest touches the broker adapter: {offenders}"


def test_the_backtest_calls_no_llm() -> None:
    """Test 25b — Leitplanke 1. Every number in the artefact is code-computed.
    CLAUDE.md forbids letting a model calculate financial figures, and the whole
    value of the artefact rests on that."""
    pattern = re.compile(r"^\s*(from|import)\s+src\.llm", re.MULTILINE)
    offenders = [path for path in _python_files("backtest") if pattern.search(path.read_text())]
    assert not offenders, f"backtest reaches for an LLM client: {offenders}"


def test_the_backtest_writes_only_its_own_table() -> None:
    """The module persists `backtest_run` and nothing else — no decision, no order,
    no research item can originate here (Invarianten #2 und #3)."""
    forbidden = ("Decision(", "OrderRecord(", "ResearchItem(", "Review(", "Portfolio(")
    for path in _python_files("backtest"):
        source = path.read_text()
        for name in forbidden:
            assert name not in source, f"{path} constructs {name}"
