# F061 — Aktien-Zyklen auf Handelstage beschränken

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Gefunden beim Beantworten von Ralfs Frage "wann sind die nächsten Läufe der
Agenten?": `build_scheduler` (`src/orchestrator/scheduler.py`) registriert
die vier US-Aktien-Zyklen (C1-C4) per `trigger="cron"` **ohne**
`day_of_week`-Filter — im Gegensatz zu den beiden Krypto-Job-Gruppen direkt
darunter, die explizit `day_of_week="mon-fri"` bzw. `"sat,sun"` setzen.
Ergebnis: die Aktien-Zyklen wären auch am Wochenende gefeuert, obwohl die
Börse zu ist — echte LLM-Kosten gegen veraltete Freitagsdaten, ohne dass
ein neues Signal überhaupt möglich ist. Kein Test hatte das je geprüft
(`test_stock_jobs_use_exchange_timezone_and_crypto_jobs_use_utc` prüft nur
Timezone/Uhrzeit, nicht den Wochentag).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #7 Kosten-Caps | ja, mildernd | Ein Wochenend-Lauf hätte reale LLM-Kosten verursacht, ohne dass die Kosten-Caps das verhindert hätten (die greifen erst ab einer Schwelle, nicht präventiv gegen unnötige Läufe). Fix verhindert die unnötigen Läufe von vornherein. |

**Kosten:** keine (verhindert unnötige zukünftige Kosten). **Bewusst nicht
Teil dieses Fixes:** US-Feiertage (Thanksgiving, Weihnachten, ...) — reine
Wochentags-Restriktion war der konkrete, klar abgegrenzte Fund; ein
Feiertagskalender ist ein separates, größeres Feature.

## 3. Testdefinition

`tests/orchestrator/test_scheduler.py`: neuer Test prüft, dass alle vier
`stock-c{1..4}`-Jobs `day_of_week="mon-fri"` gesetzt haben (gleiches Muster
wie die bestehende Timezone-/Uhrzeit-Prüfung).

## 4. Implementierung

`src/orchestrator/scheduler.py`: `day_of_week="mon-fri"` zur
`scheduler.add_job(...)`-Aufruf für die Aktien-Zyklen ergänzt.

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_scheduler.py -q` → 8 passed (7
bestehende + 1 neuer). `uv run pytest -q -m 'not integration'` → 503 passed,
10 deselected. `uv run pytest -q -m integration` → 8 passed, 2 skipped
(unverändert). `uv run ruff check`/`ruff format --check` → sauber. `uv run
mypy src/orchestrator` → sauber.

## 6. Rollback-Pfad

Eine Zeile in einer bestehenden `add_job`-Aufruf — Commit zurücknehmen
genügt, kein Schema-Change.
