"""aktienfinder.de screen-grabbing: DOM extraction + screenshot evidence into
`aktienfinder_snapshot`. See docs/features/F012-aktienfinder-grabbing.md.

Screen-grabbing (not an API — aktienfinder.de doesn't have one), per
ARCHITECTURE.md §3.5.2: a logged-in Playwright session renders the target view,
values come from the DOM (robust/cheap vs. vision), a screenshot is kept as lineage
evidence. Idempotent: upsert on (symbol, snapshot_date).

`extract_snapshot`/`sync_aktienfinder_snapshots` are exercised against
`AktienfinderPage`, a small protocol a fake implements in tests — no real browser
needed. `PlaywrightAktienfinderPage`/`login`/`grab_isin_snapshot`/
`run_daily_grab_live` are the real, Playwright-backed path verified live against
Ralf's own aktienfinder.de account (see F012 §5) — these aren't unit-tested with a
real browser (no browser in the default test run), only the pure/fake-backed
functions are.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from playwright.sync_api import Page, sync_playwright
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import AktienfinderSnapshot

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
_BASE_URL = "https://aktienfinder.net"


class AktienfinderLoginError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Snapshot:
    symbol: str
    fields: dict[str, object]
    screenshot_path: str


class AktienfinderPage(Protocol):
    """One already-navigated, already-logged-in page for a symbol's aktienfinder.de
    view. The real implementation (`PlaywrightAktienfinderPage`) wraps a Playwright
    `Page`; tests use a fake."""

    def query_selector_text(self, selector: str) -> str | None: ...
    def screenshot(self, path: Path) -> None: ...


class PlaywrightAktienfinderPage:
    """Real `AktienfinderPage` — thin wrapper around a Playwright `Page` already
    navigated to a symbol's `/aktien-profil/<isin>` view. Uses Playwright's own CSS
    selector engine (supports `:has-text()`, `:nth-match()`, not just plain CSS),
    which is what makes the label-based selectors in `config/ingestion.yaml` work
    without brittle DOM-position assumptions."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def query_selector_text(self, selector: str) -> str | None:
        element = self._page.query_selector(selector)
        return element.inner_text().strip() if element else None

    def screenshot(self, path: Path) -> None:
        self._page.screenshot(path=str(path))


def extract_snapshot(
    page: AktienfinderPage,
    symbol: str,
    field_selectors: dict[str, str],
    screenshot_dir: Path,
    snapshot_date: datetime.date,
) -> Snapshot:
    """Pulls each configured field out of the DOM and saves a screenshot as lineage
    evidence. A missing selector yields `None` for that field rather than raising —
    aktienfinder.de's layout isn't guaranteed stable, and a partial snapshot is more
    useful than losing the whole symbol over one missing element."""
    fields: dict[str, object] = {
        name: page.query_selector_text(selector) for name, selector in field_selectors.items()
    }

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"{symbol}_{snapshot_date.isoformat()}.png"
    page.screenshot(screenshot_path)

    return Snapshot(symbol=symbol, fields=fields, screenshot_path=str(screenshot_path))


def extract_dividend_history(page: Page) -> list[dict[str, str]]:
    """Parses the Ex-Datum/Zahltag/Betrag/Art table on `/dividenden-profil/<isin>`.
    Not part of `field_selectors` (a table isn't a single-element text value like the
    other fields) — called separately by `grab_isin_snapshot` against the dividend
    profile page."""
    js = (
        "trs => trs.map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()))"
    )
    rows: list[list[str]] = page.eval_on_selector_all("table tbody tr", js)
    return [
        {"ex_date": row[0], "pay_date": row[1], "amount": row[2], "type": row[3]}
        for row in rows
        if len(row) >= 4
    ]


def login(page: Page, username: str, password: str) -> None:
    """Logs into aktienfinder.de. Discovered flow (no public docs): `/profil` ->
    click "Anmelden" -> fills the `#username`/`#password` fields that appear -> click
    the "Weiter" submit button. Raises `AktienfinderLoginError` if the nav bar doesn't
    show "Abmelden" afterward (wrong credentials, or the site's login flow changed)."""
    page.goto(f"{_BASE_URL}/profil", wait_until="networkidle", timeout=30_000)
    page.get_by_text("Anmelden", exact=True).first.click()
    page.wait_for_timeout(500)
    page.fill("#username", username)
    page.fill("#password", password)
    page.get_by_role("button", name="Weiter").click()
    page.wait_for_timeout(1_500)

    if not page.get_by_text("Abmelden", exact=True).first.is_visible():
        raise AktienfinderLoginError(
            "Login did not succeed — nav bar doesn't show 'Abmelden' after submit"
        )

    # Dismiss the cookie banner once, so it doesn't obscure the evidence screenshots
    # taken for every symbol afterward. Best-effort — a changed/missing banner
    # shouldn't fail the whole grab.
    try:
        page.get_by_text("Alles akzeptieren", exact=True).first.click(timeout=3_000)
    except Exception:
        pass


def grab_isin_snapshot(
    page: Page,
    isin: str,
    field_selectors: dict[str, str],
    screenshot_dir: Path,
    snapshot_date: datetime.date,
) -> Snapshot:
    """Full real grab for one ISIN: navigates to the stock-profile view (scalar
    fields + screenshot via `extract_snapshot`), then the dividend-profile view
    (dividend history table), merges both into one `Snapshot`."""
    page.goto(f"{_BASE_URL}/aktien-profil/{isin}", wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(1_000)
    snapshot = extract_snapshot(
        PlaywrightAktienfinderPage(page), isin, field_selectors, screenshot_dir, snapshot_date
    )

    page.goto(f"{_BASE_URL}/dividenden-profil/{isin}", wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(1_000)
    dividend_history = extract_dividend_history(page)

    return Snapshot(
        symbol=snapshot.symbol,
        fields={**snapshot.fields, "dividend_history": dividend_history},
        screenshot_path=snapshot.screenshot_path,
    )


def sync_aktienfinder_snapshots(
    session: Session, snapshot_date: datetime.date, snapshots: list[Snapshot]
) -> int:
    if not snapshots:
        return 0

    rows = [
        {
            "symbol": s.symbol,
            "snapshot_date": snapshot_date,
            "fields": s.fields,
            "screenshot_path": s.screenshot_path,
        }
        for s in snapshots
    ]

    stmt = insert(AktienfinderSnapshot).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_aktienfinder_snapshot_symbol_date",
        set_={
            "fields": stmt.excluded.fields,
            "screenshot_path": stmt.excluded.screenshot_path,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def run_daily_grab(
    session: Session,
    pages_by_symbol: dict[str, AktienfinderPage],
    snapshot_date: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point, mirrors the other F008-F011 `run_*` functions.

    Takes already-navigated `AktienfinderPage`s per symbol rather than owning
    browser/login lifecycle itself — that's what `run_daily_grab_live` does for the
    real Playwright path. Kept separate so the extraction/persistence logic stays
    testable without a real browser (see `tests/ingestion/test_aktienfinder_grabbing.py`).
    """
    config = yaml.safe_load(config_path.read_text())
    grab_config = config["aktienfinder"]
    field_selectors: dict[str, str] = grab_config["field_selectors"]
    screenshot_dir = Path(_require_env(grab_config["screenshot_dir_env"]))

    snapshots = [
        extract_snapshot(page, symbol, field_selectors, screenshot_dir, snapshot_date)
        for symbol, page in pages_by_symbol.items()
    ]
    return sync_aktienfinder_snapshots(session, snapshot_date, snapshots)


def run_daily_grab_live(
    session: Session,
    isins: list[str],
    snapshot_date: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Real, credential-backed entry point: launches a headless Chromium, logs into
    aktienfinder.de, grabs a snapshot (stock-profile fields + dividend history +
    screenshot) for each ISIN, persists. Live-verified against Ralf's own account for
    two symbols (Apple, SAP) — see docs/features/F012-aktienfinder-grabbing.md §5.
    """
    config = yaml.safe_load(config_path.read_text())
    grab_config = config["aktienfinder"]
    field_selectors: dict[str, str] = grab_config["field_selectors"]
    screenshot_dir = Path(_require_env(grab_config["screenshot_dir_env"]))
    username = _require_env(grab_config["username_env"])
    password = _require_env(grab_config["password_env"])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            login(page, username, password)
            snapshots = [
                grab_isin_snapshot(page, isin, field_selectors, screenshot_dir, snapshot_date)
                for isin in isins
            ]
        finally:
            browser.close()

    return sync_aktienfinder_snapshots(session, snapshot_date, snapshots)


def run_daily_grab_configured(
    session: Session,
    snapshot_date: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point for the scheduler (F037): reads the Ralf-curated
    `aktienfinder.candidate_isins` list and delegates to `run_daily_grab_live` —
    see docs/features/F037-aktienfinder-candidate-list-and-scheduling.md. There is
    deliberately no automatic candidate discovery (no fundamentals-screening data
    source available); Ralf maintains the list by hand.
    """
    config = yaml.safe_load(config_path.read_text())
    candidate_isins: list[str] = config["aktienfinder"]["candidate_isins"]
    return run_daily_grab_live(session, candidate_isins, snapshot_date, config_path=config_path)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
