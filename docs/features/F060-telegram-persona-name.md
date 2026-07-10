# F060 — Persona-Name explizit in der Telegram-HITL-Nachricht

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Ralf: "Mir fehlt in der Telegram-Nachricht der Agent, der handelt." Die
Freigabe-Anfrage zeigte bisher nur `🔔 Freigabe erforderlich: AAPL` — bei
sechs parallel laufenden Personas ist ohne Namen unklar, wer die Order
vorschlägt. `HitlRequest` (`src/telegram/hitl.py`) hatte kein
`persona_name`-Feld überhaupt.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #2 Privilege Separation | nein | Reine Anzeige-Ergänzung, keine neue Schreib-/Order-Fähigkeit. |
| Fairness | nein | Gilt für alle 6 Personas identisch. |

**Kosten:** keine.

## 3. Testdefinition

`tests/telegram/test_hitl.py`: `format_approval_message`/
`format_outcome_message` enthalten den Persona-Namen. `tests/telegram/
test_hitl_store.py`: `decision_to_hitl_request` gibt den übergebenen
Persona-Namen zurück, `load_pending_decision` liefert ihn als drittes
Tupel-Element. `tests/telegram/test_bot.py`: `_handle_hitl_callback` reicht
den Namen bis in die finale Bestätigungsnachricht durch.

## 4. Implementierung

- `src/telegram/hitl.py`: `HitlRequest` bekommt `persona_name: str`;
  `format_approval_message`/`format_outcome_message` (letztere jetzt mit
  `persona_name`-Parameter) zeigen ihn.
- `src/telegram/hitl_store.py`: `load_pending_decision` joint zusätzlich auf
  `Portfolio`/`Persona` und gibt `(Decision, Cycle, str)` zurück;
  `decision_to_hitl_request` nimmt `persona_name` als Parameter.
- `src/orchestrator/persona_analysis.py`: `_await_hitl_outcome` bekommt
  `persona_name` und legt ihn im `interrupt()`-Payload ab (`"persona_name"`)
  — der Weg, über den der Name den Telegram-Sendepfad überhaupt erreicht,
  wenn eine Decision zum ersten Mal pausiert.
- `src/orchestrator/scheduler.py`: `notify_pending_hitl_decisions` liest
  `payload["persona_name"]` für die ausgehende Nachricht;
  `sweep_expired_hitl_decisions`s Query erweitert um denselben
  `Portfolio`/`Persona`-Join.
- `src/telegram/bot.py`: `_handle_hitl_callback` reicht den aus
  `load_pending_decision` geladenen Namen an `decision_to_hitl_request` und
  `format_outcome_message` durch.

## 5. Testdurchlauf

`uv run pytest -q -m 'not integration'` → 502 passed, 10 deselected. `uv run
pytest -q -m integration` → 8 passed, 2 skipped (unverändert). `uv run ruff
check`/`ruff format --check` → sauber. `uv run mypy src/telegram
src/orchestrator` → sauber.

## 6. Rollback-Pfad

Reine Signatur-/Text-Erweiterung über mehrere Module, aber additiv (kein
Verhalten entfernt) — Commit zurücknehmen genügt, kein Schema-Change.
