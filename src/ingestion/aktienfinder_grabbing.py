"""aktienfinder.de screen-grabbing: DOM extraction + screenshot evidence into
`aktienfinder_snapshot`. See docs/features/F012-aktienfinder-grabbing.md.

Screen-grabbing (not an API — aktienfinder.de doesn't have one), per
ARCHITECTURE.md §3.5.2: a logged-in Playwright session renders the target view,
values come from the DOM (robust/cheap vs. vision), a screenshot is kept as lineage
evidence. Idempotent: upsert on (symbol, snapshot_date).

The real Playwright-backed `PlaywrightAktienfinderPage` needs a live, logged-in
session against aktienfinder.de — that requires Ralf's real login credentials, which
this module deliberately doesn't assume or request. Everything else (field
extraction, persistence) is exercised against `AktienfinderPage`, a small protocol a
fake implements in tests.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import AktienfinderSnapshot

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


@dataclass(frozen=True, slots=True)
class Snapshot:
    symbol: str
    fields: dict[str, str | None]
    screenshot_path: str


class AktienfinderPage(Protocol):
    """One already-navigated, already-logged-in page for a symbol's aktienfinder.de
    view. The real implementation wraps a Playwright `Page`; tests use a fake."""

    def query_selector_text(self, selector: str) -> str | None: ...
    def screenshot(self, path: Path) -> None: ...


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
    fields = {
        name: page.query_selector_text(selector) for name, selector in field_selectors.items()
    }

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"{symbol}_{snapshot_date.isoformat()}.png"
    page.screenshot(screenshot_path)

    return Snapshot(symbol=symbol, fields=fields, screenshot_path=str(screenshot_path))


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
    browser/login lifecycle itself — that lifecycle needs a real Playwright session
    plus Ralf's aktienfinder.de credentials, which is exactly the piece this feature
    leaves for a follow-up (see docs/features/F012 §5 "Noch offen").
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


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
