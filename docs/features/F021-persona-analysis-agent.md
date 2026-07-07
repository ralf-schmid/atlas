# F021 — Persona-Analyse-Agent

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Der erste Agent, der echte LLM-Calls macht und echte `decision`-Zeilen erzeugt
(`docs/dod/phase-4.md` Punkt 7). Pro Persona/Portfolio, pro Zyklus: liest die
Recherche-Items dieses Zyklus (F017) + offene Positionen (F020/BrokerAdapter), ruft
die Persona über `guarded_complete` (F019) mit ihrem Charter (F018) auf, parst eine
strukturierte Entscheidung, validiert sie, und — bei `buy` — lässt sie durchs
Risk-Gate (F004) laufen. Ergebnis ist immer eine persistierte `decision`-Zeile (außer
wenn der Recherche-Pool für diesen Zyklus leer ist, siehe Non-Scope) mit validierten
`input_research_ids`.

**Scope:** `hold`, `reject_idea`, `buy` (mit Risk-Gate-Anbindung, Sizing per
Konfidenz-Formel — von Ralf entschieden, siehe unten). **Non-Scope (bewusst, siehe
Begründung):**
- **`sell`/`close`:** Kein Order-Ausführungspfad existiert bisher (Handels-Agent ist
  ein späteres Feature) — es gibt also noch keine echten, von ATLAS selbst
  eröffneten Positionen, gegen die ein `sell`/`close` sinnvoll geprüft werden könnte.
  Wird mit dem Handels-Agenten gemeinsam nachgezogen, wenn echte Positionen
  existieren.
- **Kein Order-Platzieren:** dieses Feature persistiert nur `decision`-Zeilen
  (`status=approved` oder `risk_rejected`) — keine Order geht an den Broker
  (Invariante #2 Privilege Separation: nur der separate Handels-Agent darf Order
  platzieren, und der liest ausschließlich `approved`-Decisions per DB-ID).
- **Leerer Recherche-Pool:** wenn F017 für diesen Zyklus 0 Items liefert, macht die
  Persona **keinen** LLM-Call und erzeugt **keine** Decision — `input_research_ids`
  muss laut Schema (F003) nicht-leer sein, eine Decision ohne echte Referenz wäre
  eine Fake-Zitierung. "Nichts Neues seit dem letzten Zyklus" ist ein legitimer
  Zustand, kein Fehler.
- **HITL:** noch nicht verdrahtet (eigenes, folgendes Feature) — `approved` heißt
  hier "vom Risk-Gate freigegeben", nicht "zum Handeln autorisiert".

**Sizing-Formel (mit Ralf abgestimmt, nicht selbst angenommen):** die Persona liefert
eine `conviction` zwischen 0 und 1 (keine USD-Zahl); Code berechnet
`position_value_usd = conviction × max_position_pct × portfolio_equity_usd`. Bei
`conviction=1.0` wird exakt die persona-eigene Obergrenze ausgeschöpft, nie mehr —
das Risk-Gate prüft das Ergebnis danach ohnehin nochmal (u. a. gegen die
System-Ceiling).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate ist deterministischer Code | ja | Das LLM liefert `conviction` (0-1) und Instrument — **keine** USD-Beträge, Preise oder Stop-Distanzen. `compute_position_value_usd`, `compute_stop_loss_price`, `compute_atr14` sind reiner Code; `evaluate_decision` selbst bleibt unverändert (F004). |
| #2 Privilege Separation | ja | Dieses Feature hat keinerlei Order-Tool — es persistiert nur `decision`. `AgentRun.agent="persona_analysis"` (kein `"trading"`-Agent-Typ hier). |
| #3 Keine Order ohne Decision / `input_research_ids` validiert | ja (Kern) | `input_research_ids` wird gegen die tatsächlich für diesen Zyklus geladenen `research_item`-IDs validiert — ein vom LLM erfundenes oder leeres Set führt zu Fallback `reject_idea` mit `rejection_reason="invalid_research_ids"`, zitiert dann alle real verfügbaren Items dieses Zyklus (ehrlicher Fallback, keine Fake-Zitierung). |
| #9 Untrusted Content | ja | Recherche-Items werden im User-Prompt als klar markierter, getaggter JSON-Block übergeben (`BEGIN RESEARCH_ITEMS (untrusted data)` / `END`), zusätzlich zur allgemeinen Charter-Instruktion (F018). Dieser Agent hat ohnehin keine Order-Tools — ein bösartiger Artikel kann höchstens eine `decision` mit schlechter These erzeugen, nie eine Order auslösen. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Entry-Preis (`market_bar`, DAY-Timeframe, jüngster Close), ATR14 (14-Perioden True-Range-Mittel aus `market_bar`), Stop-Loss-Preis und Positionsgröße sind alle Code — das LLM sieht diese Werte nicht einmal im Prompt (nur die Recherche-Items + offene Positionen). |
| Fehlende Marktdaten | ja | Kein `market_bar` für das vorgeschlagene Instrument, oder (bei CHARTIST) < 15 Bars für ATR → Fallback `reject_idea` mit `rejection_reason="insufficient_price_history"`, kein Crash, kein erfundener Preis. |
| Fairness | ja | Identischer Code-Pfad für alle 6 Personas; einzige Unterschiede sind Charter-Inhalt (F018) und `stop_loss_policy`-Typ (F004-Config) — beides bereits vorhandene, versionierte Config, kein neuer Sondercode pro Persona. |

**Design-Entscheidungen:**
- **Drei neue, unabhängig testbare Module** statt einem Monolithen:
  `market_pricing.py` (Preis/ATR aus `market_bar`), `decision_sizing.py`
  (Stop-Loss-Preis + Positionsgröße, reine Arithmetik), `llm_decision_schema.py`
  (Pydantic-Schema + robustes JSON-Parsing inkl. Markdown-Code-Fence-Stripping).
  `persona_analysis.py` orchestriert nur.
- **`AgentRun` wird immer geschrieben** (auch bei Fallback-`reject_idea`), damit die
  Kosten-/Fehlerquote pro Persona sichtbar bleibt — `status=FAILED` nur bei einer
  echten Exception (z. B. LLM-Call schlägt fehl), nicht bei einem sauber behandelten
  Fallback wie fehlenden Marktdaten (das ist ein gültiges Ergebnis, kein Fehler).
- **`BudgetExceededError` (F019) wird nicht abgefangen** — wenn das Kosten-Budget
  aufgebraucht ist, soll der Zyklus für diese Persona sichtbar fehlschlagen
  (`AgentRun.status=FAILED`, Fehlertext im `error`-Feld), nicht still eine
  Fallback-Decision erzeugen, die suggeriert, die Persona hätte "nachgedacht".

**Kosten:** genau ein `persona_analysis`-Call (Sonnet, `config/llm.yaml`) je Persona
und Zyklus, mit leerem Recherche-Pool: null Calls. **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_market_pricing.py`:
1. `get_latest_price` liefert den jüngsten `close` für ein Symbol.
2. `get_latest_price` liefert `None` ohne vorhandene Bars.
3. `compute_atr14` mit ≥ 15 Bars liefert einen plausiblen, deterministisch
   nachrechenbaren Wert.
4. `compute_atr14` liefert `None` mit < 15 Bars.

`tests/orchestrator/test_decision_sizing.py`:
5. `compute_position_value_usd`: `conviction=1.0` → exakt `max_position_pct × equity`;
   `conviction=0.5` → die Hälfte.
6. `compute_stop_loss_price` (FIXED) → `entry_price × (1 - max_loss_pct)`.
7. `compute_stop_loss_price` (ATR) → `entry_price × (1 - max(atr_multiplier×atr14/entry_price, min_loss_pct))`.
8. `compute_stop_loss_price` (ATR) ohne `atr14` → `None`.

`tests/orchestrator/test_llm_decision_schema.py`:
9. Gültiges JSON (auch in ```-Fences verpackt) → korrekt geparst.
10. Ungültiges JSON / fehlendes Pflichtfeld → `None` (Aufrufer entscheidet Fallback).

`tests/orchestrator/test_persona_analysis.py` (LLM gemockt, echte DB):
11. Leerer Recherche-Pool → kein LLM-Call, keine Decision, keine `agent_run`-Zeile
    (siehe Design — nichts zu tun ist kein Ereignis).
12. `hold`-Antwort → Decision mit `status=RECORDED`, `action=HOLD`, korrekte
    `input_research_ids`.
13. `reject_idea`-Antwort → Decision mit `status=RECORDED`, `rejection_reason`
    übernommen.
14. `buy`-Antwort, Risk-Gate approved → Decision `status=APPROVED`, `risk_check`
    gefüllt, Positionsgröße/Stop-Preis korrekt aus Sizing-Formel.
15. `buy`-Antwort, Risk-Gate rejected (z. B. `max_trades_per_day` überschritten) →
    Decision `status=RISK_REJECTED`.
16. LLM liefert ungültige/leere `input_research_ids` → Fallback `reject_idea` mit
    `rejection_reason="invalid_research_ids"`, zitiert alle Items des Zyklus.
17. `buy` ohne verfügbare Marktdaten für das Instrument → Fallback `reject_idea`
    mit `rejection_reason="insufficient_price_history"`.
18. Jeder Aufruf schreibt genau einen `agent_run` mit `agent="persona_analysis"`.

## 4. Implementierung

`src/orchestrator/market_pricing.py`, `src/orchestrator/decision_sizing.py`,
`src/orchestrator/llm_decision_schema.py`, `src/orchestrator/persona_analysis.py`.

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_market_pricing.py
tests/orchestrator/test_decision_sizing.py tests/orchestrator/test_llm_decision_schema.py
tests/orchestrator/test_persona_analysis.py -q` → 21 passed (LLM gemockt, echte lokale
DB). `uv run pytest tests/orchestrator -q -m integration` → 1 passed
(Graph-Integrationstest, LLM gemockt mit dynamischer Zitat-Extraktion, siehe
Testdatei-Docstring). `uv run pytest -q -m 'not integration'` (Gesamtsuite) → 323
passed, 3 deselected. `uv run ruff check`/`ruff format --check` → sauber.
`uv run mypy src/orchestrator src/llm src/personas src/risk src/broker src/db` →
sauber.

**Live-Verifikation (2026-07-07), voller Stack lokal:** lokalen `litellm`-Container
gestartet (`docker compose up -d litellm`, gegen die bereits laufende lokale
Postgres-Instanz, kein separater DB-Container nötig), 49 echte EDGAR-Filings
synchronisiert (F009), `scripts/run_cycle.py` end-to-end ausgeführt — **echter
Sonnet-Call für alle 6 Personas**. Ergebnis: alle 6 haben korrekt erkannt, dass der
Research-Pool nur aus Routine-EDGAR-Formularen (3/4/13) besteht, und produzierten
plausible, charaktertypisch formulierte `hold`-Decisions mit validierten
`input_research_ids` (kein einziger Parse-/Validierungs-Fallback nötig). 6 echte
`cost_ledger`-Zeilen (`scope=persona`, korrekte `persona_id`), Gesamtkosten dieses
einen Zyklus: **0,1312 USD** — weit unter allen Caps. `litellm`-Container danach
gestoppt.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert, kein Schema. Rollback =
Commit zurücknehmen; die Graph-Integration (Ersatz des F016-Platzhalter-Knotens)
fällt mit demselben Revert zurück auf `create_persona_agent_run_placeholder`.
