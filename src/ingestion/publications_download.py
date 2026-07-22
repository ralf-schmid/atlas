"""Boersenmedien auto-download: newest issue PDF -> the F011 ingest directory.

See docs/features/F078-publications-auto-download.md. This is the "Ziel-Pipeline"
half of ARCHITECTURE.md §3.5.1 that F013 deliberately deferred — the Telegram
fallback prompt stays as the failure path, it just stops being the normal path.

Auth is a **stored browser session**, never a scripted login: konto.boersenmedien.com's
login form is behind Cloudflare Turnstile (F078 §2.1), so Ralf signs in himself once
via scripts/boersenmedien_session.py and this job reuses the resulting Playwright
`storage_state`. An expired session is an expected outcome, not a crash — the caller
turns `BoersenmedienSessionExpired` back into the F013 prompt.

Subscription URLs are discovered at runtime rather than configured: the abo number
changes on every renewal (2778322 -> 2877536, observed live), so the three URLs
F013 hard-coded are already dead. Matching runs against the product title using the
same `subject_keyword` that identifies the magazine from the mail subject.

`select_subscription`/`select_latest_issue`/`download_latest_issue` are exercised
against `BoersenmedienPortal`, a small protocol a fake implements in tests — no real
browser needed. `PlaywrightBoersenmedienPortal`/`run_auto_download_live` are the real
path, verified live (F078 §5), not unit-tested.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Page, sync_playwright

from src.ingestion.publications_notify import Magazine

_BASE_URL = "https://konto.boersenmedien.com"
_SUBSCRIPTIONS_URL = f"{_BASE_URL}/produkte/abonnements"
# The subscription cards carry this modifier class; the "Neuerscheinungen" ad box on
# the same page is a plain `.content-box` and must not be picked up — it holds
# "In den Warenkorb" links, i.e. purchase actions this job must never touch.
_SUBSCRIPTION_CARD_SELECTOR = "div.content-box-with-image-header"
_ISSUES_LINK_SELECTOR = 'a[href*="/ausgaben"]'
_DOWNLOAD_LINK_SELECTOR = 'a[href*="/produkte/content/"][href$="/download"]'
_PASSWORD_FIELD_SELECTOR = "#SignInPassword"
# Word boundary matters: a plain "AKTIV" substring also matches "INAKTIV", which
# would let an expired subscription win and silently download a stale issue.
_ACTIVE_RE = re.compile(r"\bAKTIV\b")
_DOWNLOAD_TIMEOUT_MS = 180_000  # a full magazine PDF is tens of MB over a home line


class BoersenmedienSessionExpired(RuntimeError):
    """The stored session no longer authenticates — a human has to re-run
    scripts/boersenmedien_session.py. Expected periodically, not a bug."""


class SubscriptionNotFound(RuntimeError):
    pass


class IssueNotFound(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SubscriptionCard:
    title: str
    issues_url: str
    active: bool


@dataclass(frozen=True, slots=True)
class IssueLink:
    label: str
    href: str


@dataclass(frozen=True, slots=True)
class DownloadResult:
    magazine_slug: str
    issue_label: str
    pdf_path: Path
    skipped: bool


class BoersenmedienPortal(Protocol):
    """One already-authenticated view of konto.boersenmedien.com. The real
    implementation wraps a Playwright `Page`; tests use a fake."""

    def list_subscriptions(self) -> list[SubscriptionCard]: ...
    def list_issue_downloads(self, issues_url: str) -> list[IssueLink]: ...
    def download(self, href: str, target: Path) -> None: ...


def parse_active_flag(card_text: str) -> bool:
    return bool(_ACTIVE_RE.search(card_text.upper()))


def select_subscription(cards: list[SubscriptionCard], subject_keyword: str) -> SubscriptionCard:
    """Picks the active subscription whose product title contains the magazine's
    keyword ("DER AKTIONÄR" -> "DER AKTIONÄR E-Paper"). Inactive cards are excluded
    outright rather than used as a fallback — an expired subscription's issue list
    ends at its last covered issue, so falling back to it would download an old PDF
    and label it as today's."""
    keyword = subject_keyword.lower()
    matches = [card for card in cards if keyword in card.title.lower()]
    active = [card for card in matches if card.active]
    if not active:
        raise SubscriptionNotFound(
            f"No active subscription matching {subject_keyword!r} "
            f"(found {len(matches)} inactive match(es) among {len(cards)} card(s))"
        )
    return active[0]


def select_latest_issue(links: list[IssueLink]) -> IssueLink:
    """The issues page lists newest first (verified live, F078 §2.1), so document
    order is the ordering — the labels ("DER AKTIONÄR 31/26") are issue numbers, not
    dates, and sorting them would mean parsing a week/year scheme that resets."""
    if not links:
        raise IssueNotFound("Issues page contains no download links")
    return links[0]


def target_pdf_path(base_dir: Path, slug: str, issue_date: datetime.date) -> Path:
    """F011's convention, unchanged: `<base_dir>/<slug>/<YYYY-MM-DD>.pdf`."""
    return base_dir / slug / f"{issue_date.isoformat()}.pdf"


def download_latest_issue(
    portal: BoersenmedienPortal,
    magazine: Magazine,
    base_dir: Path,
    issue_date: datetime.date | None = None,
) -> DownloadResult:
    """Discovers the magazine's subscription, downloads its newest issue into the
    ingest directory, and reports what happened.

    Skips the download when the target file already exists — n8n retries the webhook
    on a non-2xx, and re-pulling tens of megabytes for an issue that is already on
    disk is pure waste. The caller still runs the (idempotent) article pipeline."""
    issue_date = issue_date or datetime.date.today()
    target = target_pdf_path(base_dir, magazine.slug, issue_date)

    if target.exists():
        return DownloadResult(
            magazine_slug=magazine.slug,
            issue_label=target.name,
            pdf_path=target,
            skipped=True,
        )

    subscription = select_subscription(portal.list_subscriptions(), magazine.subject_keyword)
    issue = select_latest_issue(portal.list_issue_downloads(subscription.issues_url))

    target.parent.mkdir(parents=True, exist_ok=True)
    portal.download(issue.href, target)

    return DownloadResult(
        magazine_slug=magazine.slug,
        issue_label=issue.label,
        pdf_path=target,
        skipped=False,
    )


def format_download_success(result: DownloadResult, article_count: int) -> str:
    action = "war bereits abgelegt" if result.skipped else "automatisch geladen"
    return (
        f"📰 {result.issue_label} {action}\n\n"
        f"Datei: {result.pdf_path}\n"
        f"Artikel in der DB: {article_count}"
    )


class PlaywrightBoersenmedienPortal:
    """Real `BoersenmedienPortal` — thin wrapper around a Playwright `Page` running
    in a context built from the stored session state."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def list_subscriptions(self) -> list[SubscriptionCard]:
        self._goto(_SUBSCRIPTIONS_URL)
        cards = []
        for box in self._page.query_selector_all(_SUBSCRIPTION_CARD_SELECTOR):
            heading = box.query_selector("h1, h2, h3, h4, h5")
            link = box.query_selector(_ISSUES_LINK_SELECTOR)
            if heading is None or link is None:
                continue
            href = link.get_attribute("href")
            if href is None:
                continue
            # The heading holds title + status badge ("DER AKTIONÄR E-Paper\nAKTIV");
            # the title is its first line, the status is read from the whole card.
            title = heading.inner_text().strip().splitlines()[0].strip()
            cards.append(
                SubscriptionCard(
                    title=title,
                    issues_url=self._absolute(href),
                    active=parse_active_flag(box.inner_text()),
                )
            )
        return cards

    def list_issue_downloads(self, issues_url: str) -> list[IssueLink]:
        self._goto(issues_url)
        links = []
        for article in self._page.query_selector_all("article"):
            anchor = article.query_selector(_DOWNLOAD_LINK_SELECTOR)
            if anchor is None:
                continue
            href = anchor.get_attribute("href")
            if href is None:
                continue
            # The heading, not the first text line: a promo badge ("★GRATIS★") can
            # precede the title in the card body, and that badge would then end up
            # as the issue name in the Telegram confirmation.
            heading = article.query_selector("h1, h2, h3, h4, h5")
            label = heading.inner_text().strip() if heading else href
            links.append(IssueLink(label=label or href, href=href))
        return links

    def download(self, href: str, target: Path) -> None:
        # Clicking, not `goto`: the endpoint answers 405 to HEAD and Playwright aborts
        # a navigation that turns into a file response, so the download event is the
        # only reliable way to get at the bytes (F078 §2.1).
        with self._page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as download_info:
            self._page.click(f'a[href="{href}"]')
        download_info.value.save_as(target)

    def _goto(self, url: str) -> None:
        # `domcontentloaded`, not `networkidle`: the portal keeps analytics
        # connections open, so networkidle never settles and every navigation ran
        # into the timeout (measured from the box, F078 §5). The pages are
        # server-rendered ASP.NET views — the markup is complete at DOMContentLoaded.
        self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        if "login.boersenmedien" in self._page.url or self._page.query_selector(
            _PASSWORD_FIELD_SELECTOR
        ):
            raise BoersenmedienSessionExpired(
                f"Stored session no longer authenticates (landed on {self._page.url})"
            )

    def _absolute(self, href: str) -> str:
        return href if href.startswith("http") else f"{_BASE_URL}{href}"


def run_auto_download_live(
    magazine: Magazine,
    base_dir: Path,
    session_state_path: Path,
    issue_date: datetime.date | None = None,
) -> DownloadResult:
    """Blocking, browser-backed entry point — run it off the event loop."""
    if not session_state_path.exists():
        raise BoersenmedienSessionExpired(
            f"No stored session at {session_state_path} — run scripts/boersenmedien_session.py"
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(
                storage_state=str(session_state_path), accept_downloads=True
            )
            portal = PlaywrightBoersenmedienPortal(context.new_page())
            return download_latest_issue(portal, magazine, base_dir, issue_date)
        finally:
            browser.close()
