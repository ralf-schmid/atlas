"""See docs/features/F022-hitl-flow.md §3, test 1 and F072 (HITL off for paper)."""

from __future__ import annotations

from src.db.models import PortfolioMode
from src.orchestrator.hitl_config import is_hitl_required


def test_paper_hitl_required_matches_config_file() -> None:
    assert is_hitl_required(PortfolioMode.PAPER) is False


def test_live_hitl_required_matches_config_file() -> None:
    assert is_hitl_required(PortfolioMode.LIVE) is True
