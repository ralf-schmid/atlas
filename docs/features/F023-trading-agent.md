# F023 — Handels-Agent (Order-Ausführung)

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Letztes fehlendes Stück, um eine `APPROVED`-Decision tatsächlich zu einer Order beim
Broker zu machen — `docs/dod/phase-4.md` Punkt 9. `BrokerAdapter.place_order()`
(F001/F002) existiert bereits und verlangt zwingend `decision_id` + `stop_loss_price`,
persistiert aber **nichts** selbst (`del decision_id # order_record ist ein späteres
Feature`, F001 §Implementierung) — dieses Feature schließt genau diese Lücke:
`execute_decision()` nimmt eine bereits `APPROVED`-Decision (nie Freitext, nie eine
LLM-Ausgabe direkt), ruft den Adapter auf, persistiert `order_record`, setzt
`decision.status = EXECUTED`.

**Scope:** Ausführung von `buy`-Decisions mit `status=APPROVED` (der einzige Status,
der aktuell erreichbar ist — direkt bei deaktiviertem HITL oder nach
Telegram-Freigabe, F022). **Non-Scope:** `sell`/`close` (siehe F021 §1 — es gibt noch
keine echten, von ATLAS selbst eröffneten Positionen), Fill-Polling/-Reconciliation
(Order-Status-Updates nach der Platzierung sind ein separater, künftiger
Reporting-Baustein).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #2 Privilege Separation (Kern dieses Features) | ja | `execute_decision(session, decision, broker_adapter)` nimmt ein bereits geladenes `Decision`-**Objekt** aus der DB entgegen (nie einen String/Freitext) und wirft, wenn `decision.status != APPROVED` — es gibt keinen Code-Pfad, der eine nicht-freigegebene Decision an den Broker weiterreicht. Aufgerufen wird es ausschließlich aus `analyze_persona_cycle`, genau in dem Moment, in dem eine Decision den Status `APPROVED` erreicht (direkt oder nach HITL-Resume) — kein separater, von außen aufrufbarer "platziere irgendeine Order"-Pfad. |
| #3 Keine Order ohne persistierte Decision | ja | `order_record.decision_id` ist DB-seitig `NOT NULL` + Fremdschlüssel (F003) — strukturell unmöglich, eine Order ohne Decision-Referenz zu persistieren. |
| #4 Pflicht-Stop-Loss als GTC-Order beim Broker | ja | Unverändert durch F001 sichergestellt (OTO-Bracket-Order, Stop-Leg zwingend) — dieses Feature liest nur `entry_order_id`/`stop_order_id` aus dem bereits-sicheren `OrderResult` und persistiert beide (`stop_order_id` in `order_record.raw`, da das Schema nur eine `broker_order_id`-Spalte hat). |
| #5 Paper/Live-Trennung | ja | `order_record.mode` kommt direkt aus `portfolio.mode` (immer `PAPER` aktuell) — keine Möglichkeit, eine Live-Order zu erzeugen, solange keine Live-Portfolios existieren (P6). |
| Fehlerbehandlung ist kein stiller Fallback | ja | Schlägt `place_order()` fehl (Broker-Ablehnung, Netzwerkfehler), bleibt die Decision auf `APPROVED` (kein `order_record`) — sie wird beim nächsten Lauf erneut versucht, statt in einem unklaren Zwischenzustand zu verschwinden. Der Fehler wird in einem `agent_run` (`agent="trading"`, `status=FAILED`) festgehalten. |

**Design-Entscheidungen:**
- **Aufruf aus `analyze_persona_cycle` heraus, kein eigener Graph-Knoten:** ein
  zusätzlicher, über eine Kante verbundener Graph-Knoten hätte erfordert,
  Branch-lokale Daten (Decision-Objekt) über einen geteilten Graph-State-Kanal zu
  reichen — dieselbe, in F022 experimentell nachgewiesene Kollisionsgefahr bei
  parallelem `Send` ohne `Annotated`-Reducer. Da `execute_decision` ein reiner
  Funktionsaufruf mit Seiteneffekt (DB + Broker) ist, braucht er keinen eigenen
  Knoten — die Modul-Grenze (`src/orchestrator/trading.py`), nicht die
  Graph-Topologie, ist hier die Privilege-Separation-Grenze.
- **`stop_order_id` landet in `order_record.raw`**, nicht in einer neuen Spalte — das
  Schema (F003) sieht bewusst nur ein `broker_order_id`-Feld vor; `raw` ist exakt für
  "zusätzliche Broker-Rohdaten" gedacht.
- **`broker`-Feld kommt aus `config/broker.yaml`** (`registry.get_adapter_type`,
  neue kleine Hilfsfunktion) statt aus einer Typprüfung auf die Adapter-Instanz —
  eine Config-Quelle für "welcher Adapter gehört zu welcher Persona", konsistent mit
  `get_adapter` selbst.

**Kosten:** keine LLM-Calls. **Fairness:** ein Ausführungspfad für alle 6 Personas.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_trading.py` (Fake-`BrokerAdapter`, echte DB):
1. `execute_decision` mit `status=APPROVED` → `order_record` persistiert
   (`decision_id`, `broker`, `broker_order_id=entry_order_id`, `mode`, `status=NEW`,
   `raw["stop_order_id"]` gesetzt), `decision.status` wird `EXECUTED`.
2. `execute_decision` mit `status != APPROVED` (z. B. `RISK_REJECTED`) → wirft
   `ValueError`, kein `order_record`, kein Broker-Aufruf (Fake wirft bei Aufruf).
3. `place_order()` schlägt fehl (Fake wirft `RuntimeError`) → kein `order_record`,
   `decision.status` bleibt `APPROVED`, ein `agent_run` mit `status=FAILED` wird
   geschrieben.
4. `analyze_persona_cycle`: `buy`, Risk-Gate approved, HITL deaktiviert → Decision
   landet direkt bei `EXECUTED` mit echtem (gefaktem) `order_record` — End-to-End
   innerhalb des bestehenden Persona-Analyse-Tests.
5. `analyze_persona_cycle`: `buy`, Risk-Gate approved, HITL-Resume mit "approved" →
   dieselbe End-to-End-Kette nach dem Resume.

## 4. Implementierung

`src/broker/registry.py` (`get_adapter_type`), `src/orchestrator/trading.py`
(`execute_decision`), `src/orchestrator/persona_analysis.py` (Aufruf direkt nach
jeder Stelle, an der eine Decision `APPROVED` wird).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_trading.py -q` → 3 passed. `uv run pytest
tests/orchestrator -q -m 'not integration'` → 53 passed (inkl. 2 neuer End-to-End-
Tests in `test_persona_analysis.py`: direkte Freigabe → `EXECUTED` +
`order_record`; HITL-Resume → `EXECUTED` + `order_record`). `uv run pytest
tests/orchestrator -q -m integration` → 2 passed. `uv run pytest -q -m 'not
integration'` (Gesamtsuite) → 331 passed, 4 deselected. `uv run ruff check`/`ruff
format --check` → sauber. `uv run mypy src/orchestrator src/llm src/personas
src/risk src/broker src/db src/telegram` → sauber.

**Wichtiger Fund während der Umsetzung:** `graph.py`s Persona-Knoten konstruierte den
`BrokerAdapter` bisher fest über die echte Registry (`get_adapter`) — ohne Änderung
hätte der Mehrfach-Interrupt-Integrationstest aus F022 (der einen `buy`-Interrupt auf
"approved" resumt) durch dieses Feature eine **echte Alpaca-Paper-Order** ausgelöst.
Behoben, indem `build_and_compile_graph` einen `adapter_factory`-Parameter bekommt
(Default: die echte Registry-Funktion, Produktionsverhalten unverändert); die
Integrationstests injizieren jetzt einen Fake und brauchen dadurch auch keine echten
Alpaca-Credentials mehr.

**Live-Verifikation (2026-07-07, mit Ralfs ausdrücklicher Zustimmung):** 57 echte
Tagesbars (AAPL/MSFT/SPY) über F008 synchronisiert, eine manuell konstruierte, echte
`APPROVED`-Decision (VULTURE, 1× AAPL @ 312,66 USD, Stop 281,39 USD) über
`execute_decision` mit dem echten `AlpacaPaperAdapter` ausgeführt:
`order_record` persistiert (`broker_order_id`, `raw.stop_order_id` beide echte
Alpaca-Order-IDs), `decision.status → EXECUTED`. Gegenprobe direkt gegen den echten
Account: `buying_power` sank von 5.000 auf 4.685,54 USD — die Order wurde real bei
Alpaca angenommen (reserviert für die offene Order, Markt zum Testzeitpunkt
geschlossen, daher noch kein Fill/keine Position sichtbar).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert (außer dem einen neuen
Aufruf in `persona_analysis.py`), kein Schema. Rollback = Commit zurücknehmen —
Decisions bleiben dann wieder bei `APPROVED` stehen (keine Order, kein Datenverlust).
