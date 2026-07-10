# F063 — Kritischer Review des HITL-/Order-Pfads: zwei weitere Lücken geschlossen

Status: umgesetzt
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

Ralfs Auftrag: "Solche Fehler, dass die Telegram Nachricht nicht verarbeitet
wird oder die Order nicht platziert wird, dürfen nicht passieren... Gehe
nochmal kritisch über alle Punkte." Erneutes, gezieltes Durchgehen der
kompletten Kette Telegram-Klick → DB-Update → Graph-Resume → Order-Ausführung
→ Snapshot fand zwei weitere reale Lücken, beide durch Fehlen eines
Non-Fatal-Try/Except an einer Stelle, wo der Rest der Kette dieses Muster
bereits konsequent nutzt:

1. **`_handle_hitl_callback` (`src/telegram/bot.py`):** der
   `graph.invoke(Command(resume=...))`-Aufruf, der einen Button-Klick
   tatsächlich in eine fortgesetzte Order verwandelt, hatte **kein**
   Try/Except — anders als das strukturell identische `graph.invoke` in
   `sweep_expired_hitl_decisions` (`scheduler.py`), das bereits geschützt ist.
   Ein Fehler beim Resume (Broker-Hänger, DB-Blip) hätte die
   `_handle_hitl_callback`-Funktion crashen lassen, **bevor** die finale
   `edit_message_text`-Bestätigung erreicht wird — der Nutzer hätte auf
   Telegram nie erfahren, ob sein Klick etwas bewirkt hat, obwohl die
   Datenbank (dank vorherigem `db_session.commit()`) den Klick bereits korrekt
   verarbeitet hatte.
2. **`generate_portfolio_snapshot`-Aufrufe in `persona_analysis.py` und
   `retry_stuck_decisions`:** ungeschützt. Ein Fehler beim Bauen des
   Snapshots — direkt **nach** einer erfolgreichen Order-Ausführung in
   derselben Transaktion — hätte in `persona_analysis.py` die komplette
   Exception aus `analyze_persona_cycle` propagieren lassen; der Graph-Knoten
   (`graph.py::_persona_analysis_node`) erreicht sein `session.commit()` dann
   nie, und die Transaktion rollt zurück — **inklusive der Order, die gerade
   erfolgreich beim Broker platziert und lokal per `execute_decision`
   persistiert wurde.** Die reale Order bleibt beim Broker bestehen (nichts
   macht die dort rückgängig), aber ihr `order_record` verschwindet aus
   Postgres, bis ein späterer Retry sie über die Client-Order-ID-Idempotenz
   (F027) wiederfindet.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #3 Keine Order ohne persistierte Decision | ja, verstärkt | Fix #2 verhindert genau das Szenario, in dem eine reale Order beim Broker existiert, aber ihr `order_record` durch einen Folgefehler aus Postgres verschwindet. |
| Fehlerbehandlung kein stiller Fallback | ja | Beide Fixes folgen exakt dem bereits etablierten Muster (`_maybe_execute_decision`, `_sweep_stop_orders`, `sweep_expired_hitl_decisions`): Fehler wird als `agent_run(status=FAILED)` bzw. strukturiertes Log festgehalten, nicht verschluckt, aber auch nicht fatal für die bereits erfolgreiche Order. |
| Kosten | keine | Reine Fehlerbehandlung, kein zusätzlicher Call. |

**Design-Entscheidung (`retry_stuck_decisions`):** `execute_decision` und
`generate_portfolio_snapshot` werden jetzt als **zwei getrennte
Transaktionen** committet (vorher eine gemeinsame) — genau damit ein
Snapshot-Fehler den bereits committeten Order-Commit nicht mehr zurückrollen
kann.

## 3. Testdefinition

- `tests/telegram/test_bot.py`: neuer Test — ein fehlschlagender
  `graph.invoke`-Aufruf lässt `_handle_hitl_callback` trotzdem die
  Bestätigungsnachricht senden (die DB-Freigabe bleibt gültig, F050s Retry-Sweep
  holt die Ausführung nach).
- `tests/orchestrator/test_persona_analysis.py`: neuer Test — ein
  `get_positions()`-Fehler, der erst beim dritten Aufruf (also beim
  Post-Trade-Snapshot, nicht bei der Prompt-Erstellung oder der
  Risk-Gate-Prüfung) auftritt, lässt die bereits erfolgreiche Order stehen
  (`order_record` existiert, `decision.status == EXECUTED`) und erzeugt einen
  `agent_run(agent="reporting", status=FAILED)`.
- `tests/orchestrator/test_stuck_decision_sweep.py`: analoger Test für
  `retry_stuck_decisions` — ein Snapshot-Fehler nach erfolgreicher
  `execute_decision` lässt die Order bestehen.

## 4. Implementierung

- `src/telegram/bot.py`: `graph.invoke(...)`-Aufruf in
  `_handle_hitl_callback` in Try/Except, Fehler geloggt (neuer Modul-Logger),
  Bestätigungsnachricht wird trotzdem gesendet.
- `src/orchestrator/persona_analysis.py`: neue `_safe_generate_portfolio_
  snapshot()`, an beiden bisherigen `generate_portfolio_snapshot`-Aufrufstellen
  verwendet (Idempotenz-Replay-Zweig und Hauptpfad).
- `src/orchestrator/scheduler.py`: `retry_stuck_decisions` committet
  `execute_decision` und `generate_portfolio_snapshot` jetzt als zwei
  getrennte Try/Except-Blöcke statt eines gemeinsamen.

## 5. Testdurchlauf

`uv run pytest -q -m 'not integration'` → 525 passed, 15 deselected. `uv run
pytest -q -m integration` → 13 passed, 2 skipped. `uv run ruff check`/`ruff
format --check` → sauber. `uv run mypy src` → sauber (68 Dateien, exakt der
CI-Check).

## 6. Rollback-Pfad

Rein additiv (Try/Except um bereits bestehende Aufrufe, eine Transaktion in
zwei aufgeteilt) — Commit zurücknehmen genügt, kein Schema-Change, kein
geändertes Erfolgsverhalten.
