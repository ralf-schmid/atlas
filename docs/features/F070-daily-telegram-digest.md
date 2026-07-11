# F070 — Täglicher Telegram-Digest

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 4 (schließt DoD-Punkt "Telegram-Tagesdigest kommt täglich" ab)

## 1. Zieldefinition

Ralfs Auftrag: `/digest` implementieren, um den letzten offenen Punkt aus
`docs/dod/phase-4.md` zu streichen (die anderen beiden — Mehrtage-Dauerlauf-
Nachweis, Kosten-Cap-Stichprobe — erledigen sich laut Ralf durch Zeitablauf).
ARCHITECTURE.md §6.4 Punkt 3 spezifiziert Inhalt und Bauweise bereits fix:
*"durchgeführte Trades je Persona, Depotwert je Persona + gesamt, Cash-
Reserve, offene Positionen, LLM-Tageskosten. Digest ist Code (Jinja-Template
über Snapshot-Queries), kein LLM nötig."*

**Vorgefunden:** `src/telegram/digest.py` (Rendering: `DigestData`,
`PersonaDigest`, `render_daily_digest`) war bereits vollständig implementiert
und getestet — laut TODO-Kommentar in `bot.py` seit F053 als Platzhalter
liegen geblieben, weil die DB-Query-Seite fehlte. **Scope:** die fehlende
DB-Aggregation, das `/digest`-Command-Wiring (Handler bereits registriert,
nur der Funktionskörper war ein Stub) und ein zusätzlicher automatischer
Tagesversand (ARCHITECTURE.md nennt "täglicher Digest" separat von den
Kommandos — nicht nur On-Demand).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Keine Finanzkennzahlen vom LLM berechnen | nein | Reine Snapshot-/Ledger-Queries + Jinja-Template, kein LLM-Call — exakt wie ARCHITECTURE.md vorschreibt. |
| #6 Secrets nie im Repo | nein | Nutzt den bestehenden `TelegramConfig`/`send_alert`-Pfad, keine neuen Credentials. |
| Telegram-Bot nur konfigurierte Chat-ID | nein | `/digest`-Command läuft durch den bestehenden `_make_handler`-Authorization-Gate; der automatische Tagesversand nutzt `send_alert`, das bereits ausschließlich an `config.allowed_chat_id` sendet. |
| Fairness | nein | Digest ist reine Reporting-Ausgabe, keine Research-/Order-Quelle — betrifft keine Persona-Entscheidung. |

**Design-Entscheidungen:**
- **`llm_cost_usd` nutzt `src/llm/ledger.py::sum_persona_spend_today`**, die
  exakt gleiche Funktion, die den echten Kosten-Cap durchsetzt (Invariante
  #7) — statt einer zweiten, unabhängig definierten Tagesgrenze. Damit zeigt
  der Digest immer denselben Wert, der auch tatsächlich gegen das Budget
  zählt.
- **"Durchgeführte Trades" = `OrderRecordStatus.FILLED`**, nicht jeder
  Order-Versuch — ein abgelehnter/stornierter Auftrag ist kein Trade, der
  stattgefunden hat (pragmatische, im Commit dokumentierte Auslegung von
  ARCHITECTURE.md §6.4, keine Geld-Themen-Grauzone, da nur eine
  Zähl-Definition).
- **Depotwert/Cash: jeweils der neueste `portfolio_snapshot` unabhängig vom
  exakten Datum**, nicht nur ein Snapshot von genau "heute" — ein Digest an
  einem Tag ohne frischen Snapshot soll den letzten bekannten Stand zeigen,
  nicht auf 0 zurückfallen.
- **Automatischer Tagesversand lebt in `src/orchestrator/scheduler.py`s
  `build_scheduler`**, nicht in einer neuen Registrierungsfunktion — dieselbe
  Stelle, die bereits andere Nicht-Zyklus-Wartungs-Jobs hostet
  (`_sweep_expired_hitl_job`, `_retry_stuck_decisions_job`), läuft im
  selben `scheduler`-Container-Prozess (`scripts/run_scheduler.py`), der
  Telegram-Bot-Prozess selbst hat keinen eigenen Scheduler.
- **Zeitpunkt 16:30 America/New_York, jeden Tag** (`config/cycles.yaml`,
  neues `digest.time`) — nach dem letzten Aktien-Zyklus C4 (15:15 ET) mit
  Puffer fürs Fill-/Snapshot-Reporting, aber ohne Wochentags-Beschränkung
  (anders als die Aktien-Zyklen, F061): CRYPTOR handelt auch am Wochenende,
  ein Digest soll das zeigen.
- **Kein Retry/Consecutive-Failure-Zähler für den Tagesversand** — anders als
  Ingestion-/Zyklus-Jobs (2x-in-Folge-Alert-Schwelle) ist ein fehlgeschlagener
  Digest-Versand einmal täglich; der nächste Versuch ist ohnehin erst morgen,
  und ein zusätzlicher "Digest fehlgeschlagen"-Alert wäre nur eine zweite
  Telegram-Nachricht über denselben Ausfall, den das fehlende Digest schon
  selbst anzeigt.

**Kosten:** keine (kein LLM-Call). **Fairness:** unverändert.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/telegram/test_digest.py` (6 neue Tests, `build_digest_data`):
1. Nur aktive Personas erscheinen.
2. `trades_today` zählt nur `FILLED`-Orders innerhalb des Tages (nicht
   andere Status, nicht andere Tage).
3. Depotwert/Cash kommen vom neuesten Snapshot unabhängig vom Datum.
4. `open_positions` zählt nur `qty != 0` am neuesten Snapshot-Zeitpunkt.
5. `llm_cost_usd` summiert nur Persona-Scope-Kosten des Tages (System-Scope
   und andere Tage ausgeschlossen).
6. Leeres Ergebnis ohne aktive Personas.

`tests/telegram/test_bot.py` (3 Tests, ersetzt den alten Platzhalter-Test):
`_handle_digest` meldet fehlende DB-Konfiguration korrekt; baut/sendet den
gerenderten Digest bei vorhandener `session_factory` (inkl. `session.close()`);
tut nichts ohne `update.message`.

`tests/orchestrator/test_cycles_config.py`: `digest_time` wird geladen.

`tests/orchestrator/test_scheduler.py` (3 Tests): der `daily-digest`-Job ist
mit korrekter Zeit/Zeitzone und **ohne** Wochentags-Filter registriert;
`_daily_digest_job` sendet den gerenderten Digest; ein Fehler wird geloggt,
nicht weitergeworfen.

`tests/telegram/conftest.py` (neu): fehlte bisher — `tests/telegram/` hatte
keinen `_migrated_schema`-Opt-in, daher liefen die neuen DB-gestützten
`build_digest_data`-Tests gegen ein Schema ohne Tabellen. Gleiches Muster wie
`tests/orchestrator/conftest.py`.

## 4. Implementierung

- `src/telegram/digest.py`: `build_digest_data` + Query-Helfer
  (`_count_filled_trades_today`, `_latest_snapshot_field`,
  `_count_open_positions`), nutzt `sum_persona_spend_today` aus
  `src/llm/ledger.py`.
- `src/telegram/bot.py`: `_handle_digest` implementiert (vorher Stub) —
  lädt `DigestData` über die `session_factory` aus `bot_data`, antwortet mit
  `render_daily_digest(...)`.
- `src/orchestrator/cycles_config.py`: `CyclesConfig.digest_time` (neues
  Pflichtfeld) + Laden aus `config/cycles.yaml`s neuer `digest:`-Sektion.
- `src/orchestrator/scheduler.py`: `_daily_digest_job` + Registrierung in
  `build_scheduler` (cron, `16:30` `America/New_York`, kein
  `day_of_week`-Filter).
- `config/cycles.yaml`: neue `digest: time: "16:30"`-Sektion.
- `tests/db/factories.py`: `make_portfolio_snapshot`/`make_position_snapshot`/
  `make_cost_ledger_entry` bekommen zusätzliche Override-Parameter (`ts`,
  `total_value`, `cash`, `qty`, `cost_usd`) — additiv, ändert keine
  bestehenden Aufrufer.
- Kein Alembic-Migrations-Bedarf (keine Schema-Änderung).

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'`: 567 passed (12 neue Tests).
  `ruff check`/`format --check`, `mypy src/` (ganzes Repo): clean.
- Deployment: rsync (`config/cycles.yaml`, `cycles_config.py`,
  `scheduler.py`, `bot.py`, `digest.py`) + `docker compose build api
  scheduler telegram-bot` + `up -d` auf `atlas-ugreen`.
- **Live verifiziert** (echte Produktions-DB, echter Telegram-Versand):
  - Manueller `/digest`-Testlauf gegen die reale DB bestätigte plausible
    Werte je Persona (Depotwert, Cash, offene Positionen, Trades,
    LLM-Kosten) — siehe Chat-Nachweis unten.
  - Scheduler-Neustart bestätigt `daily-digest`-Job registriert (`16:30`
    `America/New_York`, kein Wochentags-Filter) neben allen bestehenden
    Jobs, keine Fehler im Log.
- **Rollback-Pfad:** `daily-digest`-Job-Registrierung aus `build_scheduler`
  entfernen (Zeilen-Revert) + `_handle_digest` auf den alten Platzhaltertext
  zurücksetzen — reiner Code-Revert, kein Schema-/Config-Rollback nötig
  (die neue `digest:`-Sektion in `config/cycles.yaml` kann folgenlos stehen
  bleiben, falls der Job-Code entfernt wird).
