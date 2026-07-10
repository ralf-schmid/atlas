# F056 — Telegram-Bot-Token nicht mehr im Klartext im Log

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Live beim F049-Deploy beobachtet: `telegram-bot`-Container-Logs enthalten bei
jedem `getUpdates`-Poll (alle ~10 Sekunden) die volle Request-URL inklusive
`TELEGRAM_BOT_TOKEN` im Klartext, z. B. `POST
https://api.telegram.org/bot<TOKEN>/getUpdates` — httpx (von
python-telegram-bot intern genutzt) loggt das standardmäßig auf `INFO`. Der
Token steht damit unverschlüsselt in `docker compose logs`, potenziell auch
in jedem Log-Aggregator, der diese Logs später einsammelt.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #6 Secrets nie im Repo | indirekt | Der Token selbst kam nie ins Repo (Env-Var, `.env` auf der Box) — aber Logs sind ein zweiter, bisher nicht bedachter Leck-Pfad für dasselbe Secret. |

**Kosten:** keine. **Kein Rotationsbedarf durch diesen Fix selbst** — ob der
bereits mehrfach geloggte Token rotiert werden soll, ist eine reine
Risikoabwägung für Ralf (kein Log-Zugriff durch Dritte bekannt), nicht Teil
dieses technischen Fixes.

## 3. Testdefinition

`tests/test_logging_config.py`: neuer Test prüft, dass `configure_logging()`
den `httpx`-Logger auf `WARNING` setzt.

## 4. Implementierung

`src/logging_config.py`: `configure_logging()` setzt zusätzlich
`logging.getLogger("httpx").setLevel(logging.WARNING)` — echte httpx-Fehler
(z. B. Verbindungsabbrüche) bleiben weiterhin sichtbar, nur die
Routine-Zeile pro Request (inkl. URL) verschwindet.

## 5. Testdurchlauf

`uv run pytest tests/test_logging_config.py -q` → 3 passed (2 bestehende + 1
neuer). `uv run ruff check`/`ruff format --check` → sauber. `uv run mypy
src/logging_config.py` → sauber.

## 6. Rollback-Pfad

Eine Zeile in einer zentralen Setup-Funktion — Commit zurücknehmen genügt,
kein Schema-Change.
