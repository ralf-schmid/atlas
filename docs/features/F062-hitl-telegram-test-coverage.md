# F062 — Testabdeckung des HITL-/Telegram-Sendepfads geschlossen

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Ralf: "Solche Fehler, dass die Telegram Nachricht nicht verarbeitet wird oder
die Order nicht platziert wird, dürfen nicht passieren. Ich erwarte, dass das
über die Tests ... abgedeckt wird." Coverage-Lauf (`pytest --cov=src`) deckte
auf, dass genau die Module, die dieser Vorfall betraf, am schwächsten getestet
waren:

- `src/telegram/alerts.py` (der tatsächliche `Bot.send_message()`-Aufruf für
  Alerts **und** HITL-Freigabe-Anfragen): **0 % Coverage**, keine einzige
  Testdatei existierte.
- `src/orchestrator/scheduler.py`s `run_one_cycle`/`notify_pending_hitl_decisions`
  — Letztere ist die Funktion, die `thread_id`/`interrupt_id` auf der Decision
  speichert **und** die Telegram-Nachricht auslöst: **0 % Coverage**,
  `run_one_cycle` wird in jedem bestehenden Scheduler-Test nur weggemockt.
- `src/telegram/bot.py` (`_handle_hitl_callback`, der Button-Klick-Handler):
  73 % — der `graph.invoke(...)`-Resume-Aufruf selbst (die Zeile, die aus
  einem Klick tatsächlich eine fortgesetzte Order macht) war nie getestet,
  ebenso mehrere Fehlerzweige (ungültige Callback-Daten, unbekannte Decision,
  Decision-ID-Mismatch, Callback-Handler-Autorisierung).

Das erklärt strukturell, warum der F049-Vorfall (Listener nie deployt) und die
F050-F052-Kette (Order-Platzierung scheiterte dreimal in Folge an Alpaca)
unentdeckt bleiben konnten — der Code, der beides tut, hatte kaum
Testabdeckung.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Feature-Prozess "Testdefinition vor Umsetzung" | ja | Dieses Feature ist reine Testabdeckung für bereits bestehenden, unveränderten Code — keine neue Logik, kein Verhalten geändert. |

**Kosten:** keine (keine echten LLM-/Telegram-Calls in den neuen Tests, alles
gemockt).

## 3. Testdefinition / Implementierung

- `tests/telegram/test_alerts.py` (neu): `send_alert`/`send_hitl_approval_request`
  gegen einen gemockten `telegram.Bot` — richtige `chat_id`, richtiger Text,
  richtige Inline-Buttons.
- `tests/orchestrator/test_run_one_cycle.py` (neu, `integration`):
  `notify_pending_hitl_decisions` speichert `thread_id`/`interrupt_id` korrekt
  auf der echten Decision-Zeile und löst pro Interrupt genau eine
  Telegram-Nachricht aus; `run_one_cycle` ruft den Graphen mit dem korrekten
  `thread_id` auf und delegiert bei `__interrupt__` an
  `notify_pending_hitl_decisions` (bzw. lässt es bei keinem Interrupt bleiben).
- `tests/telegram/test_bot.py` (erweitert, 11 neue Tests): der
  `graph.invoke(...)`-Resume-Aufruf in `_handle_hitl_callback` (der eigentliche
  Mechanismus hinter einem Button-Klick), die
  `_make_callback_handler`-Autorisierungsprüfung, alle Fehlerzweige
  (ungültige Callback-Daten, unbekannte/bereits bearbeitete Decision,
  Decision-ID-Mismatch), `/pause`/`/resume`/`/hitl` Fehlerzweige (fehlender
  Text, ungültige Eingabe, Persona nicht in DB), `/status`/`/digest`-Stubs,
  `build_application` mit echtem `session_factory`/`graph`.
- `tests/orchestrator/test_trading.py` (erweitert): `execute_decision` lehnt
  eine Decision ohne `stop_loss_price` bzw. ohne `quantity` ab, statt eine
  unvollständige Order an den Broker zu schicken (Invariante #4).

## 4. Testdurchlauf

`uv run pytest -q -m 'not integration'` → 521 passed, 14 deselected (vorher
503). `uv run pytest -q -m integration` → 12 passed, 2 skipped (vorher 8).
`uv run ruff check`/`ruff format --check` → sauber. `uv run mypy src` → sauber
(68 Dateien, exakt der CI-Check).

**Coverage-Ergebnis** (`pytest --cov=src`, kombiniert Unit + Integration):
gesamt 92 % → 96 %. Einzeln:
- `src/telegram/alerts.py`: 0 % → **100 %**
- `src/telegram/bot.py`: 73 % → **99 %**
- `src/orchestrator/trading.py`: 86 % → **100 %**
- `src/risk/*`, `src/broker/*`: weiterhin 100 % (Pflicht-Coverage laut
  CLAUDE.md unverändert erfüllt).

`src/orchestrator/scheduler.py`/`graph.py` erreichen nur mit Integration-Tests
kombiniert hohe Werte (100 % bzw. 73 %) — konsistent mit dem Projekt-Muster,
DB-/Broker-berührenden Code per echtem Postgres statt gemockt zu testen.

## 5. Rollback-Pfad

Rein additiv (nur neue/erweiterte Tests, kein Produktionscode geändert) —
Commit zurücknehmen genügt.
