import datetime
from pathlib import Path

import pytest

from src.ingestion.aktienfinder_grabbing import (
    AktienfinderLoginError,
    Snapshot,
    extract_dividend_history,
    extract_snapshot,
    login,
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


class _FakeLocator:
    def __init__(self, visible: bool = True) -> None:
        self.clicked = False
        self._visible = visible

    @property
    def first(self) -> "_FakeLocator":
        return self

    def click(self, timeout: int | None = None) -> None:
        self.clicked = True

    def is_visible(self) -> bool:
        return self._visible


class _FakeRealPage:
    """Minimal fake of the subset of Playwright's `Page` API used by
    `login`/`extract_dividend_history` — no real browser involved."""

    def __init__(self, rows: list[list[str]] | None = None, login_succeeds: bool = True) -> None:
        self.filled: dict[str, str] = {}
        self.goto_calls: list[str] = []
        self._rows = rows or []
        self._login_succeeds = login_succeeds

    def goto(self, url: str, **kwargs: object) -> None:
        self.goto_calls.append(url)

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def fill(self, selector: str, value: str) -> None:
        self.filled[selector] = value

    def get_by_text(self, text: str, exact: bool = False) -> _FakeLocator:
        if text == "Abmelden":
            return _FakeLocator(visible=self._login_succeeds)
        return _FakeLocator()

    def get_by_role(self, role: str, name: str | None = None) -> _FakeLocator:
        return _FakeLocator()

    def eval_on_selector_all(self, selector: str, js: str) -> list[list[str]]:
        return self._rows


def test_login_fills_credentials_and_submits():
    page = _FakeRealPage(login_succeeds=True)
    login(page, "user@example.com", "hunter2")

    assert page.filled == {"#username": "user@example.com", "#password": "hunter2"}
    assert page.goto_calls == ["https://aktienfinder.net/profil"]


def test_login_raises_when_nav_bar_does_not_show_abmelden():
    page = _FakeRealPage(login_succeeds=False)
    with pytest.raises(AktienfinderLoginError, match="Abmelden"):
        login(page, "user@example.com", "wrong-password")


def test_extract_dividend_history_maps_table_rows():
    page = _FakeRealPage(
        rows=[
            ["11.05.2026", "14.05.2026", "0,27 USD", "Regulär"],
            ["09.02.2026", "12.02.2026", "0,26 USD", "Regulär"],
        ]
    )
    history = extract_dividend_history(page)

    assert history == [
        {
            "ex_date": "11.05.2026",
            "pay_date": "14.05.2026",
            "amount": "0,27 USD",
            "type": "Regulär",
        },
        {
            "ex_date": "09.02.2026",
            "pay_date": "12.02.2026",
            "amount": "0,26 USD",
            "type": "Regulär",
        },
    ]


def test_extract_dividend_history_skips_malformed_rows():
    page = _FakeRealPage(
        rows=[["only", "two"], ["11.05.2026", "14.05.2026", "0,27 USD", "Regulär"]]
    )
    history = extract_dividend_history(page)

    assert history == [
        {"ex_date": "11.05.2026", "pay_date": "14.05.2026", "amount": "0,27 USD", "type": "Regulär"}
    ]
