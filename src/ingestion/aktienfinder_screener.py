"""aktienfinder.net Screener-Tool grid (`/aktienfinder`) as a dynamic candidate
source — see docs/features/F068-aktienfinder-screener-discovery.md.

Distinct from `aktienfinder_grabbing.py`'s per-ISIN deep-grab (profile page +
dividend history, F012/F037's small Ralf-curated `candidate_isins` list): this
module paginates the Screener-Tool grid itself. Every row already carries ISIN,
ticker *and* ~65 quality/valuation columns (Kursziel, Stabilität, KGV,
Kursgewinn-Historie, ...) — no per-symbol profile-page navigation needed, so a
single grid pass can cover hundreds of candidates cheaply. Ralf has a paid
aktienfinder subscription with full access to this grid (~7800 tracked
securities as of 2026-07-11); this reverses F037's "no real screener, too
costly" MVP decision now that the cost constraint no longer applies (see
docs/adr/0006-aktienfinder-screener-instead-of-static-list.md).
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

from src.db.models import AktienfinderScreenerCandidate
from src.ingestion.aktienfinder_grabbing import login
from src.ingestion.vulture_screener import AlpacaAssetUniverseProvider

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
_BASE_URL = "https://aktienfinder.net"
_SCREENER_URL = f"{_BASE_URL}/aktienfinder"
# Same stable DataTables id as aktienfinder_grabbing.py's per-ISIN search — this
# is a different interaction with the same table (full-page reads + pagination
# instead of a single ISIN filter), see that module's selector comment for why
# the id (not a generic `table`) is required.
_SCREENER_TABLE_SELECTOR = "table#SecuritiesTable"
_LENGTH_SELECT_SELECTOR = "#SecuritiesTable_length select"
_NEXT_PAGE_SELECTOR = "#SecuritiesTable_next"
_PAGE_LENGTH = "100"  # largest option the grid's length selector offers


class TradableSymbolsProvider(Protocol):
    def get_tradable_symbols(self) -> list[str]: ...


class ScreenerGridPage(Protocol):
    """One already-navigated, already-logged-in, already-paged-to-100 grid
    view. `PlaywrightScreenerGridPage` wraps a real Playwright `Page`; tests use
    a fake — same split as `AktienfinderPage` in `aktienfinder_grabbing.py`."""

    def read_rows(self, field_labels: dict[str, str]) -> list[ScreenerCandidate]: ...
    def go_to_next_page(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ScreenerCandidate:
    isin: str
    ticker: str
    name: str
    region: str
    fields: dict[str, object]


def _map_screener_grid_row(
    headers: list[str],
    cells: list[str],
    isin: str,
    ticker: str,
    name: str,
    field_labels: dict[str, str],
) -> ScreenerCandidate:
    """Pure header/cell mapping for one grid row — unit-tested without a browser.
    Same "look up the header text fresh, never a fixed column index" contract as
    `aktienfinder_grabbing._map_screener_row` (F043), for the same reason: the
    grid's column set/order is user-configurable on aktienfinder.net."""
    header_index = {h: i for i, h in enumerate(headers)}
    region_idx = header_index.get("Region")
    region = cells[region_idx] if region_idx is not None else ""
    fields: dict[str, object] = {
        field_name: cells[header_index[label]] if label in header_index else None
        for field_name, label in field_labels.items()
    }
    return ScreenerCandidate(isin=isin, ticker=ticker, name=name, region=region, fields=fields)


class PlaywrightScreenerGridPage:
    """Real grid-row source — thin wrapper around a Playwright `Page` already
    logged in and navigated to `_SCREENER_URL`. A `ScreenerGridPage` protocol
    isn't introduced here (unlike `AktienfinderPage`) because the row structure
    (nested ISIN/ticker/name markup inside the first cell, see module docstring)
    needs real DOM traversal that isn't worth abstracting for tests — the pure
    `_map_screener_grid_row` above is what's unit-tested instead."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def read_rows(self, field_labels: dict[str, str]) -> list[ScreenerCandidate]:
        table = self._page.query_selector(_SCREENER_TABLE_SELECTOR)
        assert table is not None, "Screener table not found — page layout changed?"
        headers = [
            h.inner_text().strip().replace("\n", " ") for h in table.query_selector_all("th")
        ]

        candidates: list[ScreenerCandidate] = []
        for row in table.query_selector_all("tbody tr"):
            # ISIN/ticker/name live in a nested `.isinSymbol`/`.securityName`
            # structure inside the first cell (live-verified 2026-07-11,
            # F068 §5) — not exposed as separate `<td>` columns, so header-based
            # lookup doesn't apply to them like it does to the rest of the row.
            isin_link = row.query_selector(".isinSymbol a")
            ticker_span = row.query_selector(".isinSymbol span")
            name_el = row.query_selector(".securityName b")
            if isin_link is None or ticker_span is None:
                continue  # no ticker tracked for this row (dividend-profile-only) — not tradable
            isin = isin_link.inner_text().strip()
            ticker = ticker_span.inner_text().strip()
            name = name_el.inner_text().strip() if name_el else ""
            cells = [
                c.inner_text().strip().replace("\n", " ") for c in row.query_selector_all("td")
            ]
            candidates.append(
                _map_screener_grid_row(headers, cells, isin, ticker, name, field_labels)
            )
        return candidates

    def go_to_next_page(self) -> bool:
        """Returns False (no-op) once the "next" button is disabled — the last
        page reached, rather than clicking and looping forever."""
        next_button = self._page.query_selector(_NEXT_PAGE_SELECTOR)
        if next_button is None:
            return False
        classes = next_button.get_attribute("class") or ""
        if "disabled" in classes:
            return False
        next_button.click()
        self._page.wait_for_timeout(1_500)
        return True


def discover_candidates(
    grid: ScreenerGridPage,
    field_labels: dict[str, str],
    regions: set[str],
    target_candidates: int,
    max_pages: int,
) -> list[ScreenerCandidate]:
    """Paginates the already-loaded grid, keeping only rows in `regions` with a
    ticker, until `target_candidates` is reached or `max_pages` is exhausted
    (safety bound — the grid has ~7800 rows/78 pages total, scraping all of it
    isn't the goal, see F068 §2 for the cost/scope tradeoff)."""
    collected: list[ScreenerCandidate] = []
    for _page_num in range(max_pages):
        rows = grid.read_rows(field_labels)
        collected.extend(c for c in rows if c.region in regions)
        if len(collected) >= target_candidates:
            break
        if not grid.go_to_next_page():
            break
    return collected


def sync_screener_candidates(
    session: Session,
    discovered_at: datetime.date,
    candidates: list[ScreenerCandidate],
) -> int:
    if not candidates:
        return 0

    rows = [
        {
            "isin": c.isin,
            "ticker": c.ticker,
            "name": c.name,
            "region": c.region,
            "discovered_at": discovered_at,
            "fields": c.fields,
        }
        for c in candidates
    ]

    stmt = insert(AktienfinderScreenerCandidate).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_aktienfinder_screener_candidate_isin_date",
        set_={
            "ticker": stmt.excluded.ticker,
            "name": stmt.excluded.name,
            "region": stmt.excluded.region,
            "fields": stmt.excluded.fields,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def run_screener_discovery_live(
    session: Session,
    discovered_at: datetime.date,
    tradable_symbols: TradableSymbolsProvider,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Real, credential-backed entry point: logs into aktienfinder.net, paginates
    the Screener-Tool grid, filters to `tradable_symbols` (Alpaca's real
    tradable-asset directory — a region match ("Nordamerika") is only a
    pre-filter to limit how many pages are scraped; actual Alpaca tradability is
    the authoritative gate, same "don't assume, verify" principle as F067),
    persists."""
    config = yaml.safe_load(config_path.read_text())
    aktienfinder_config = config["aktienfinder"]
    discovery_config = aktienfinder_config["screener_discovery"]
    field_labels: dict[str, str] = aktienfinder_config["screener_fields"]
    regions = set(discovery_config["regions"])
    target_candidates: int = discovery_config["target_candidates"]
    max_pages: int = discovery_config["max_pages"]
    username = _require_env(aktienfinder_config["username_env"])
    password = _require_env(aktienfinder_config["password_env"])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            login(page, username, password)
            page.goto(_SCREENER_URL, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(1_500)
            page.select_option(_LENGTH_SELECT_SELECTOR, _PAGE_LENGTH)
            page.wait_for_timeout(1_500)

            grid = PlaywrightScreenerGridPage(page)
            candidates = discover_candidates(
                grid, field_labels, regions, target_candidates, max_pages
            )
        finally:
            browser.close()

    tradable = set(tradable_symbols.get_tradable_symbols())
    filtered = [c for c in candidates if c.ticker in tradable]
    return sync_screener_candidates(session, discovered_at, filtered)


def run_screener_discovery_configured(
    session: Session,
    discovered_at: datetime.date,
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> int:
    """Config-driven entry point for the scheduler — mirrors
    `aktienfinder_grabbing.run_daily_grab_configured`."""
    config = yaml.safe_load(config_path.read_text())
    screener_config = config["vulture_screener"]  # same Alpaca trading creds, F010
    key_id = _require_env(screener_config["key_id_env"])
    secret_key = _require_env(screener_config["secret_key_env"])
    tradable_symbols = AlpacaAssetUniverseProvider(api_key=key_id, secret_key=secret_key)
    return run_screener_discovery_live(
        session, discovered_at, tradable_symbols, config_path=config_path
    )


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
