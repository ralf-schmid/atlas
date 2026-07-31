"""See docs/features/F022-hitl-flow.md §3, test 1, F072 (HITL off for paper), and
F078 (set_hitl_required — the /hitl Telegram command actually writing this file).
"""

from __future__ import annotations

import pytest

from src.db.models import PortfolioMode
from src.orchestrator.hitl_config import is_hitl_required, set_hitl_required


def test_paper_hitl_required_matches_config_file() -> None:
    assert is_hitl_required(PortfolioMode.PAPER) is False


def test_live_hitl_required_matches_config_file() -> None:
    assert is_hitl_required(PortfolioMode.LIVE) is True


@pytest.fixture
def hitl_config_path(tmp_path):
    path = tmp_path / "hitl.yaml"
    path.write_text("# comment that must survive a write\npaper: false\nlive: true\n")
    return path


def test_set_hitl_required_updates_paper_and_preserves_rest(hitl_config_path) -> None:
    set_hitl_required(True, mode=PortfolioMode.PAPER, path=hitl_config_path)

    text = hitl_config_path.read_text()
    assert "paper: true" in text
    assert "live: true" in text
    assert "# comment that must survive a write" in text
    assert is_hitl_required(PortfolioMode.PAPER, path=hitl_config_path) is True
    assert is_hitl_required(PortfolioMode.LIVE, path=hitl_config_path) is True


def test_set_hitl_required_updates_live_without_touching_paper(hitl_config_path) -> None:
    set_hitl_required(False, mode=PortfolioMode.LIVE, path=hitl_config_path)

    text = hitl_config_path.read_text()
    assert "live: false" in text
    assert "paper: false" in text


def test_set_hitl_required_rejects_config_without_the_target_mode_line(tmp_path) -> None:
    path = tmp_path / "hitl.yaml"
    path.write_text("live: true\n")

    with pytest.raises(ValueError, match="paper"):
        set_hitl_required(True, mode=PortfolioMode.PAPER, path=path)
