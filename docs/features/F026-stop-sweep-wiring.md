# F026 — Stop-Sweep-Verdrahtung

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Security-Audit 2026-07-07, Finding P1: `InternalLedgerAdapter.check_stop_orders()`
(F002 §2) existiert und ist vollständig getestet, wird aber von keinem Code-Pfad
aufgerufen. Für HYPE/CONTRA/CRYPTOR (virtuelle Personas, kein echter Broker)
triggern Stop-Losses dadurch nie — Invariante 4 ("jede Position hat einen
Stop-Loss") ist für diese drei Personas faktisch tot.

**Scope:** `check_stop_orders()` einmal pro Orchestrator-Zyklus und Persona
aufrufen, ausschließlich für Personas mit `internal_ledger`-Adapter, bevor die
Persona ihre aktuellen Positionen sieht.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #4 Stop-Loss pro Position | ja (Kern dieses Fixes) | Sweep läuft vor jedem `get_positions()`-Aufruf in `analyze_persona_cycle` — sowohl im Frisch- als auch im HITL-Replay-Zweig. |
| #10 Fairness | ja | Sweep ist reiner Code (kein LLM), betrifft nur Personas, die ohnehin keinen echten Broker haben — kein Informationsvorteil. |
| Keine stillen Annahmen bei Geld-Themen | ja | Löst reale (virtuelle) Verkäufe aus — deshalb nicht automatisch im ursprünglichen Audit gefixt, sondern als eigenes Feature mit Testdefinition + Paper-Smoke-Test. |

**Design-Entscheidungen:**
- **Aufruf-Ort:** ganz am Anfang von `analyze_persona_cycle()`
  (`src/orchestrator/persona_analysis.py`), vor dem HITL-Replay-Kurzschluss und vor
  jedem `broker_adapter.get_positions()`. Ein eigener Graph-Knoten wurde verworfen —
  der Sweep muss zwingend pro Persona und vor deren Positions-Fetch laufen; ein
  gemeinsamer Vor-Knoten müsste dieselbe Persona-Iteration duplizieren.
- **Gating:** `isinstance(broker_adapter, InternalLedgerAdapter)` statt eines neuen
  Protocol-Members — `BrokerAdapter` ist ein strukturelles `Protocol`, ein
  No-op-Default dort würde nichts erzwingen und wäre irreführend. Alpaca-Personas
  haben ein broker-seitiges GTC-Stop und brauchen keinen Sweep.
- **Fehlerbehandlung:** try/except um den Sweep-Aufruf, bei Exception
  `AgentRun(agent="stop_sweep", status=FAILED, error=...)` — exakt das bestehende
  Muster aus `_maybe_execute_decision` (nicht fatal für den Zyklus der Persona,
  nicht stillschweigend verschluckt).
- **Keine neue Persistenz für ausgelöste Stops:** kein `order_record` (FK
  `decision_id` ist `NOT NULL`, ein Stop hat keine Decision — analog dazu erzeugt
  auch das Risk-Gate keine eigene Decision-Zeile). Die Positions-/Cash-Änderung ist
  bereits im Ledger und fließt automatisch in den nächsten `portfolio_snapshot`.
  Auch bei Erfolg wird kein zusätzlicher `AgentRun` geschrieben (Konsistenz mit
  `_maybe_execute_decision`, das ebenfalls nur bei Fehlern loggt).
- **Kein Hardening von `check_stop_orders()` selbst:** ein fehlschlagender
  Preis-Abruf für ein Symbol bricht den gesamten Sweep-Durchlauf der Persona für
  diesen Zyklus ab (Exception vor `store.save()`, also kein Teil-Fill persistiert)
  — außerhalb des Scopes dieses Fixes, nächster Zyklus versucht es erneut.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_persona_analysis.py`:
1. Sweep wird für `internal_ledger`-Personas aufgerufen, für native (Alpaca)
   Personas nicht (kein `AttributeError`, da `_FakeAdapter` keine
   `check_stop_orders`-Methode hat).
2. Sweep läuft vor dem ersten `get_positions()`-Aufruf.
3. Sweep triggert einen fälligen Stop und reduziert Position/erhöht Cash korrekt
   (Ende-zu-Ende über `analyze_persona_cycle`, nicht nur die bereits in
   `tests/broker/test_internal_ledger.py` getestete Trigger-Logik selbst).
4. Exception im Sweep → `AgentRun(agent="stop_sweep", status=FAILED)` geschrieben,
   Zyklus läuft für die Persona trotzdem weiter (Decision wird trotzdem erzeugt).

## 4. Implementierung

`src/orchestrator/persona_analysis.py`: neue Helper-Funktion `_sweep_stop_orders()`,
Aufruf als erste Zeile in `analyze_persona_cycle()`.
`tests/orchestrator/test_persona_analysis.py`: 4 neue Tests (`_SpyInternalLedgerAdapter`
zur Beobachtung von Aufrufreihenfolge/-anzahl, ohne die bereits getestete
Trigger-Logik zu duplizieren).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_persona_analysis.py -q` → 16 passed (12
bestehend + 4 neu). `uv run pytest tests/orchestrator tests/broker -q` → 111
passed, 3 deselected (unverändert ggü. vorher, keine Regression). `uv run mypy
src/orchestrator/persona_analysis.py` → sauber. `uv run ruff check`/`ruff format
--check` → sauber.

**Paper-Smoke-Test (Pflicht, siehe Audit-Hinweis):** durchgeführt gegen die lokale
Test-Postgres (`atlas:atlas@localhost:5432`) und eine temporäre JSON-Ledger-Datei
(`tmp_path`-Fixture in Test 3 oben) — kein Lauf gegen die Produktions-Ledger auf der
UGREEN. Ein manueller End-to-End-Lauf mit echter `config/broker.yaml`/HYPE-Config
gegen die reale (leere) Box-DB ist bewusst nicht Teil dieses Fixes — analog zu F025
§1 ist das Starten eines dauerhaften, automatisierten Zyklus-Betriebs eine separate,
von Ralf zu initiierende Aktion.

## 6. Rollback-Pfad

Commit zurücknehmen — `_sweep_stop_orders()` ist ein rein additiver Aufruf ohne
Schema-/Config-Änderung, kein Feature-Flag nötig.
