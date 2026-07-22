"""One-time helper: capture a logged-in konto.boersenmedien.com browser session.

See docs/features/F078-publications-auto-download.md §2.2. The login form sits behind
Cloudflare Turnstile, so ATLAS never scripts the login — a human signs in once and this
script only exports the resulting cookies as a Playwright `storage_state` for the
download job to reuse.

The sign-in happens in Ralf's **own Chrome**, not in a Playwright-launched browser:
Cloudflare blocks the latter outright (verified 22.07.2026 — a Playwright Chromium is
flagged by its automation surface even when headed and driven by a human). Nothing
attaches to the browser while he signs in; this script connects afterwards, over CDP,
purely to read cookies.

Usage — start a dedicated Chrome profile (a normal Chrome window, own profile so it
never touches the main one and no profile lock fights an already-running Chrome):

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
        --remote-debugging-port=9222 \\
        --user-data-dir="$HOME/.atlas-boersenmedien-chrome"

Sign in at konto.boersenmedien.com, ticking "Angemeldet bleiben?" — without it the
cookie dies with the browser and the export is worthless. Then:

    uv run python scripts/boersenmedien_session.py
    scp data/ingest/boersenmedien/session_state.json \\
        atlas-ugreen:/mnt/apps/docker/atlas/data/ingest/boersenmedien/session_state.json
    ssh atlas-ugreen 'chmod 640 /mnt/apps/docker/atlas/data/ingest/boersenmedien/session_state.json'

Keep that profile around: refreshing an expired session is then just "open it, check
you are still signed in, re-run this script".

Only cookies for boersenmedien domains are exported. The profile may hold cookies for
anything else Ralf opened in it, and none of that belongs in a file that gets copied to
a server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

_SUBSCRIPTIONS_URL = "https://konto.boersenmedien.com/produkte/abonnements"
_CDP_ENDPOINT = "http://localhost:9222"
_COOKIE_DOMAIN_MARKER = "boersenmedien"
_DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "data" / "ingest" / "boersenmedien" / "session_state.json"
)


def _filter_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cookies if _COOKIE_DOMAIN_MARKER in c.get("domain", "")]


def _export_from_running_chrome() -> list[dict[str, Any]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(_CDP_ENDPOINT)
        try:
            if not browser.contexts:
                raise RuntimeError("Chrome is reachable but has no browser context open")
            cookies: list[dict[str, Any]] = []
            for context in browser.contexts:
                cookies.extend(context.cookies())
            return _filter_cookies(cookies)
        finally:
            browser.close()


def _verify(state_path: Path) -> bool:
    """Proves the exported cookies actually authenticate, in a headless browser like
    the one on the box — better to find out here than from a Telegram failure alert
    after the next issue is published."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context(storage_state=str(state_path)).new_page()
            page.goto(_SUBSCRIPTIONS_URL, wait_until="domcontentloaded", timeout=60_000)
            return "login.boersenmedien" not in page.url and not page.query_selector(
                "#SignInPassword"
            )
        finally:
            browser.close()


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        cookies = _export_from_running_chrome()
    except Exception as exc:
        print(f"Kein Chrome mit Remote-Debugging auf {_CDP_ENDPOINT} erreichbar: {exc}")
        print("Chrome so starten (eigenes Profil, normales Fenster) und dort anmelden:")
        print('  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\')
        print("      --remote-debugging-port=9222 \\")
        print('      --user-data-dir="$HOME/.atlas-boersenmedien-chrome"')
        return 1

    if not cookies:
        print("Keine boersenmedien-Cookies gefunden — im geoeffneten Chrome angemeldet?")
        return 1

    persistent = [c for c in cookies if c.get("expires", -1) > 0]
    if not persistent:
        print(f"{len(cookies)} Cookie(s) gefunden, aber alle nur Session-Cookies.")
        print("Beim Anmelden 'Angemeldet bleiben?' ankreuzen, sonst ist die Datei wertlos.")
        return 1

    output.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2))
    # The file is a credential: it authenticates as Ralf until the cookies expire. On
    # the box it needs 640 (group familie) instead — the container user is UID 3001,
    # the host user 3000; see F078 §2.2.
    output.chmod(0o600)

    if not _verify(output):
        print(f"Cookies exportiert nach {output}, aber der Test-Login schlug fehl.")
        print("Im Chrome-Fenster pruefen, ob die Abo-Liste wirklich angezeigt wird.")
        return 1

    print(f"Session gespeichert und headless verifiziert: {output}")
    print(f"{len(cookies)} Cookie(s), davon {len(persistent)} persistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
