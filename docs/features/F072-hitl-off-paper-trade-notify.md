# F072 — HITL aus für Paper, Trade-Info statt Freigabe-Button

Status: umgesetzt
Datum: 2026-07-13
Phase: 5

## 1. Zieldefinition

Ralf: "Wir verzichten auf HITL. Stelle um, dass ich nur noch eine Info bekomme,
wenn die Agenten handeln, aber nicht mehr aktiv zustimmen muss. Wir bleiben
aber auf dem Paper-Weg noch diese Woche." Zwei Teile:

1. `config/hitl.yaml` für `paper` auf `false` — Personas handeln autonom,
   keine Freigabe-Anfrage mit Inline-Buttons mehr.
2. Ersatz-Signal: bisher war die einzige Nachricht bei HITL aus **keine** —
   `_maybe_execute_decision` (`src/orchestrator/persona_analysis.py`) führte
   die Order direkt aus, ohne irgendeine Telegram-Nachricht zu senden (das
   gab es nur im HITL-Pfad, als Freigabe-Anfrage). Ohne HITL wäre Ralf sonst
   komplett blind für ausgeführte Trades bis zum nächsten `/digest`.

`live` bleibt unverändert `true` (Invariante #5: Live-Orders brauchen HITL
gemäß Phasenlogik — diese Config wird hier nicht angefasst).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #5 Paper/Live-Trennung, HITL-Schaltung ist Config | ja, direkt | Genau der vorgesehene Mechanismus: `config/hitl.yaml` ändern, keine Umgehung im Code. `live: true` unverändert. |
| #2 Privilege Separation | nein | Ausführungspfad (`execute_decision`, einziger Order-Ausführungsort) unverändert; nur die vorgelagerte Pause entfällt. |
| #3 Keine Order ohne persistierte Decision | nein | Unverändert — Risk-Gate + Decision-Persistenz laufen exakt wie vorher, nur ohne die Wartepause. |
| Fairness (#10) | nein | Gilt für alle 6 Personas identisch (systemweite Config, kein Persona-spezifisches Flag). |

**Kosten:** keine (kein zusätzlicher LLM-Call). Ein zusätzlicher
Telegram-`sendMessage`-Call pro ausgeführtem Trade — vernachlässigbar
gegenüber Approval-Nachrichten, die er ersetzt.

**Bekannte Lücke (nicht Teil dieses Features, hier nur dokumentiert):**
`src/telegram/bot.py::_handle_hitl` hat für `/hitl on|off` einen
`# TODO(Folgearbeit): hitl.yaml / Config-Flag setzen.` — der Telegram-Befehl
schreibt `hitl.yaml` bisher **nicht** tatsächlich. Ralf kann HITL also aktuell
nur durch manuelles Editieren von `config/hitl.yaml` (+ Neustart/Reload)
wieder anschalten, nicht per `/hitl on`. Separates Ticket, falls gewünscht.

## 3. Testdefinition

- `tests/orchestrator/test_hitl_config.py`: `is_hitl_required(PAPER)` liefert
  jetzt `False` (Config-Default-Test, spiegelt die reale Datei).
- `tests/orchestrator/test_persona_analysis.py`,
  `tests/orchestrator/test_graph.py`: die vier bestehenden Tests, die den
  HITL-*required*-Pfad prüfen, patchen `is_hitl_required` jetzt explizit auf
  `True` (vorher verließen sie sich auf den Config-Default) — Verhalten bleibt
  vollständig abgedeckt, unabhängig vom aktuellen Schalterstand.
- Neu: `tests/telegram/test_alerts.py::test_format_trade_executed_message_*`
  — Formatierung (Persona, Instrument, Menge, optionale Stop-Loss-Zeile).
- Neu: `tests/orchestrator/test_persona_analysis.py::
  test_buy_executed_with_hitl_disabled_sends_a_telegram_trade_alert` — Direkt
  ausgeführter Buy (HITL aus) sendet eine `send_alert`-Nachricht mit Persona +
  Instrument; kein `telegram_notify`-`AgentRun` im Erfolgsfall.
- Neu: `..._survives_a_telegram_outage` — fehlende Telegram-Config darf den
  bereits committeten Trade nicht rückgängig machen; Fehler landet als
  `AgentRun(agent="telegram_notify", status=FAILED)`, gleicher
  Non-Fatal-Vertrag wie `_maybe_execute_decision`/`_safe_generate_
  portfolio_snapshot` im selben Modul.
- Neu: `tests/orchestrator/test_stuck_decision_sweep.py::
  test_retry_sends_a_telegram_trade_alert` — derselbe Alert auch auf dem
  Retry-Sweep-Pfad (`scheduler.retry_stuck_decisions`), der Decisions nach
  einem vorherigen Broker-Fehler nachträglich ausführt.

## 4. Implementierung

- `config/hitl.yaml`: `paper: false`, Kommentar aktualisiert.
- `src/telegram/alerts.py`: neue Funktion `format_trade_executed_message
  (persona_name, instrument, qty, stop_loss_price)` — reiner Text-Baustein,
  kein neuer Sende-Pfad (nutzt weiter `send_alert`).
- `src/orchestrator/persona_analysis.py`: `_maybe_execute_decision` reicht den
  `OrderRecord` von `execute_decision` an neue `_notify_trade_executed`
  weiter. Diese lädt `TelegramConfig` und sendet best-effort; Fehler (fehlende
  Env-Vars, Telegram-Outage) werden als `AgentRun(agent="telegram_notify",
  status=FAILED)` festgehalten, niemals fatal für den Cycle — exakt der
  Non-Fatal-Vertrag, der in diesem Modul für `_maybe_execute_decision` und
  `_safe_generate_portfolio_snapshot` bereits gilt.
- `src/orchestrator/scheduler.py`: `retry_stuck_decisions` sendet denselben
  Alert nach einer erfolgreichen Retry-Ausführung (eigener Try/Except, loggt
  über den bestehenden `logger` statt `AgentRun`, da dieser Pfad außerhalb
  eines Cycle-Kontexts läuft).

## 5. Testdurchlauf

`DATABASE_URL=postgresql+psycopg://atlas:atlas@localhost:5432/atlas uv run
pytest -q -m 'not integration'` → 582 passed, 16 deselected. `uv run pytest -q
-m integration` → 14 passed, 2 skipped (unverändert). `uv run ruff check` /
`ruff format --check` → sauber. `uv run mypy src/telegram src/orchestrator` →
sauber.

## 6. Rollback-Pfad

`config/hitl.yaml`: `paper` zurück auf `true` — sofort wirksam (wird pro
Cycle-Start gelesen, kein Redeploy nötig, `is_hitl_required` liest die Datei
live). Die Notify-Ergänzung selbst ist additiv (kein Verhalten entfernt,
nur eine zusätzliche best-effort Nachricht) und bleibt auch bei HITL wieder an
unschädlich — sie feuert dann zusätzlich zur bisherigen Ausführungsbestätigung,
sobald eine Decision auf `APPROVED` steht.
