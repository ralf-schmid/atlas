import datetime
from pathlib import Path

import pytest

from src.ingestion.aktienfinder_grabbing import (
    Snapshot,
    extract_snapshot,
    run_daily_grab,
    sync_aktienfinder_snapshots,
)


class _FakePage:
    def __init__(self, values: dict[str, str | None]) -> None:
        self._values = values
        self.screenshot_calls: list[Path] = []

    def query_selector_text(self, selector: str) -> str | None:
        return self._values.get(selector)

    def screenshot(self, path: Path) -> None:
        self.screenshot_calls.append(path)
        path.write_bytes(b"fake-png")


def test_extract_snapshot_pulls_configured_fields_and_saves_screenshot(tmp_path):
    page = _FakePage({"[data-field='fair-value']": "42.50", "[data-field='quality']": "8/10"})
    snapshot = extract_snapshot(
        page,
        "AAPL",
        {"fair_value": "[data-field='fair-value']", "quality_score": "[data-field='quality']"},
        tmp_path,
        datetime.date(2026, 7, 5),
    )

    assert snapshot.symbol == "AAPL"
    assert snapshot.fields == {"fair_value": "42.50", "quality_score": "8/10"}
    assert snapshot.screenshot_path == str(tmp_path / "AAPL_2026-07-05.png")
    assert page.screenshot_calls == [tmp_path / "AAPL_2026-07-05.png"]
    assert (tmp_path / "AAPL_2026-07-05.png").exists()


def test_extract_snapshot_yields_none_for_missing_selector(tmp_path):
    page = _FakePage({})
    snapshot = extract_snapshot(
        page,
        "AAPL",
        {"fair_value": "[data-field='fair-value']"},
        tmp_path,
        datetime.date(2026, 7, 5),
    )

    assert snapshot.fields == {"fair_value": None}


def test_sync_aktienfinder_snapshots_returns_zero_for_empty_list(session):
    assert sync_aktienfinder_snapshots(session, datetime.date(2026, 7, 5), []) == 0


def test_sync_aktienfinder_snapshots_is_idempotent_on_rerun(session):
    day = datetime.date(2026, 7, 5)
    v1 = [Snapshot(symbol="AAPL", fields={"fair_value": "40.0"}, screenshot_path="/a/old.png")]
    v2 = [Snapshot(symbol="AAPL", fields={"fair_value": "42.5"}, screenshot_path="/a/new.png")]

    first_count = sync_aktienfinder_snapshots(session, day, v1)
    second_count = sync_aktienfinder_snapshots(session, day, v2)

    assert first_count == 1
    assert second_count == 1

    from sqlalchemy import select

    from src.db.models import AktienfinderSnapshot

    rows = session.scalars(
        select(AktienfinderSnapshot).where(AktienfinderSnapshot.symbol == "AAPL")
    ).all()
    assert len(rows) == 1
    assert rows[0].fields == {"fair_value": "42.5"}
    assert rows[0].screenshot_path == "/a/new.png"


def test_run_daily_grab_reads_config_and_env(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    screenshot_dir = tmp_path / "screenshots"
    config_path.write_text(
        "aktienfinder:\n"
        "  screenshot_dir_env: TEST_SCREENSHOT_DIR\n"
        "  field_selectors:\n"
        "    fair_value: \"[data-field='fair-value']\"\n"
    )
    monkeypatch.setenv("TEST_SCREENSHOT_DIR", str(screenshot_dir))

    page = _FakePage({"[data-field='fair-value']": "42.50"})
    count = run_daily_grab(
        session, {"AAPL": page}, datetime.date(2026, 7, 5), config_path=config_path
    )

    assert count == 1


def test_run_daily_grab_raises_when_env_var_missing(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "aktienfinder:\n"
        "  screenshot_dir_env: TEST_SCREENSHOT_DIR_MISSING\n"
        "  field_selectors:\n"
        "    fair_value: \"[data-field='fair-value']\"\n"
    )
    monkeypatch.delenv("TEST_SCREENSHOT_DIR_MISSING", raising=False)

    with pytest.raises(ValueError, match="TEST_SCREENSHOT_DIR_MISSING"):
        run_daily_grab(session, {}, datetime.date(2026, 7, 5), config_path=config_path)
