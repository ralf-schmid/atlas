# F027 — Crash-idempotente Order-Ausführung

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Security-Audit 2026-07-07, Finding P2: Stirbt der Prozess zwischen
`broker_adapter.place_order()` und dem DB-Commit (Commit passiert erst im
Graph-Knoten, nicht in `execute_decision()` selbst), platziert ein LangGraph-Replay
dieselbe Order erneut — Doppelkauf. `decision_id` wird an beide Adapter
durchgereicht, aber bisher ignoriert (`del decision_id`).

**Scope:** `place_order()` für beide Adapter idempotent bezüglich `decision_id`
machen — ein Replay mit derselben `decision_id` liefert das ursprüngliche Ergebnis
zurück, statt erneut zu füllen/zu bestellen.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Geldpfad, keine stillen Annahmen | ja | Ursprünglich bewusst nicht automatisch gefixt (Audit-Dokument) — jetzt als eigenes Feature mit Ralfs Freigabe. |
| #3 Keine Order ohne persistierte Decision | indirekt | Bleibt unverändert — dieser Fix ändert nur, was bei *wiederholtem* Aufruf für dieselbe `decision_id` passiert. |

**Design-Entscheidungen:**
- **Warum kein reiner DB-Check vor `place_order()`:** Ein Blick auf
  `execute_decision()`/`_maybe_execute_decision()` zeigt, dass `order_record` und
  `decision.status = EXECUTED` in derselben Transaktion wie der Graph-Knoten-Commit
  landen. Stirbt der Prozess vor diesem Commit, existiert beim Replay **kein**
  `order_record` — ein "existiert schon ein Record?"-Check vor dem Broker-Call
  fände nichts und würde das eigentliche Problem nicht lösen. Die Idempotenz muss
  auf Broker-/Ledger-Ebene sitzen, nicht auf DB-Ebene. Aus demselben Grund ist auch
  keine zusätzliche DB-Unique-Constraint auf `order_record.decision_id` nötig: da
  `_maybe_execute_decision` nur bei `status == APPROVED` überhaupt platziert und
  `execute_decision` Status+Record atomar mit demselben Commit setzt, kann es nie
  zwei committete `order_record`-Zeilen für dieselbe Decision geben — der Replay
  ersetzt lediglich den (nie committeten) ersten Versuch.
- **Alpaca:** `client_order_id=str(decision_id)`. Alpaca dedupliziert selbst und
  antwortet bei Wiederholung mit HTTP 422 ("client order id must be unique") statt
  still die bestehende Order zurückzugeben — das wird gezielt abgefangen
  (`_is_duplicate_client_order_id`, prüft Status **und** Nachricht, damit andere
  422er wie "insufficient buying power" weiterhin durchschlagen) und die
  bestehende Order per `get_order_by_client_id()` nachgeladen.
- **InternalLedgerAdapter:** neues `executed_decisions: dict[str, ExecutedOrder]`
  in `LedgerState` (`src/broker/ledger_store.py`), Schlüssel `str(decision_id)`.
  `place_order()` prüft zuerst diese Map; bei Treffer wird das gespeicherte
  Ergebnis zurückgegeben, ohne Cash/Position erneut zu verändern oder einen
  weiteren Pending-Stop zu registrieren. Rückwärtskompatibel: ältere Ledger-JSON-
  Dateien ohne dieses Feld werden beim Laden als leere Map behandelt.
- **Kein Pruning der `executed_decisions`-Map:** wächst um eine Zeile pro
  ausgeführter Decision — bei diesem Projektumfang (Experiment über 8 Wochen,
  Handvoll Decisions/Tag) vernachlässigbar, keine Aufräumlogik nötig.

## 3. Testdefinition (vor Umsetzung)

`tests/broker/test_internal_ledger.py`:
1. Replay mit gleicher `decision_id` füllt nicht erneut (Cash/Position unverändert
   ggü. dem ersten Fill).
2. Replay registriert keinen zweiten Pending-Stop.
3. Andere `decision_id` füllt weiterhin normal (kein Über-Blocken).

`tests/broker/test_alpaca_paper.py`:
4. `client_order_id` wird korrekt aus `decision_id` gesetzt.
5. Bei "duplicate client_order_id"-Fehler wird die bestehende Order per
   `get_order_by_client_id` nachgeladen und liefert deren IDs zurück.
6. Andere APIErrors (z. B. "insufficient buying power") werden weiterhin
   durchgereicht, nicht als Duplikat missverstanden.

## 4. Implementierung

`src/broker/ledger_store.py` (`ExecutedOrder`-Dataclass, `LedgerState.executed_decisions`,
De-/Serialisierung), `src/broker/internal_ledger.py` (`place_order` Idempotenz-Check),
`src/broker/alpaca_paper.py` (`client_order_id`, `_is_duplicate_client_order_id`,
Recovery via `get_order_by_client_id`).

## 5. Testdurchlauf

`uv run pytest tests/broker tests/orchestrator -q` → 117 passed, 3 deselected
(keine Regression). `uv run mypy src/broker src/orchestrator` → sauber.
`uv run ruff check`/`ruff format --check` → sauber.

**Kein Paper-Smoke-Test gegen echtes Alpaca-Paper nötig:** die Änderung ist rein
defensiv (Duplikat-Erkennung) und in den bestehenden Alpaca-Paper-Integrationstest
(`test_alpaca_paper_integration.py`, läuft in CI gegen echtes Alpaca Paper)
eingeschlossen — ein Normal-Fall-Durchlauf dort bestätigt, dass `client_order_id`
Alpaca nicht stört.

## 6. Rollback-Pfad

Commit zurücknehmen. Additiv: kein Schema-Change, kein Feature-Flag nötig.
Ältere Ledger-JSON-Dateien bleiben ohne Codeänderung les- und schreibbar
(`executed_decisions` fehlt dort einfach, wird beim nächsten Save ergänzt).
