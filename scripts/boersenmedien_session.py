"""One-time helper: capture a logged-in konto.boersenmedien.com browser session.

See docs/features/F078-publications-auto-download.md §2.2. The login form sits behind
Cloudflare Turnstile, so ATLAS never scripts the login — a human signs in once in the
window this script opens, and the resulting cookies (Playwright `storage_state`) are
what the automated download job reuses.

Run it on a machine with a display (Ralf's Mac), then copy the JSON to the box:

    uv run python scripts/boersenmedien_session.py
    scp data/ingest/boersenmedien/session_state.json \\
        atlas-ugreen:/mnt/apps/docker/atlas/data/ingest/boersenmedien/session_state.json

Tick "Angemeldet bleiben?" when signing in — without it the session cookie dies with
the browser and the file is worthless. Re-run whenever the download job reports an
expired session via Telegram.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_SUBSCRIPTIONS_URL = "https://konto.boersenmedien.com/produkte/abonnements"
_DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "data" / "ingest" / "boersenmedien" / "session_state.json"
)


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(_SUBSCRIPTIONS_URL, wait_until="networkidle", timeout=60_000)

            print("Bitte im Browser anmelden (inkl. 'Angemeldet bleiben?'), bis")
            print(f"{_SUBSCRIPTIONS_URL} die Abo-Liste zeigt. Danach hier ENTER druecken.")
            input()

            page.goto(_SUBSCRIPTIONS_URL, wait_until="networkidle", timeout=60_000)
            if "login.boersenmedien" in page.url or page.query_selector("#SignInPassword"):
                print(f"Noch nicht angemeldet (Seite: {page.url}) — nichts gespeichert.")
                return 1

            context.storage_state(path=str(output))
        finally:
            browser.close()

    # The file is a credential: it authenticates as Ralf until the cookies expire.
    output.chmod(0o600)
    print(f"Session gespeichert: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
