# F024 — Reporting-Agent (Portfolio-/Positions-Snapshots)

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Letzter Graph-Schritt aus ARCHITECTURE.md §5.1 ("... → Handels-Agent → Reporting") —
`docs/dod/phase-4.md` Punkt 10. Erzeugt pro Portfolio und Zyklus einen echten
`portfolio_snapshot` (+ `position_snapshot` je offener Position) aus dem echten
Broker-Kontostand — die Datengrundlage für den Telegram-Digest (F005, bisher ohne
echte Daten), die spätere Leaderboard-UI (P5) und F020s Peak-Equity-Historie (die
bisher nur passiv von *falls irgendwann* vorhandenen Snapshots profitierte, ohne dass
je einer geschrieben wurde).

**Scope:** `generate_portfolio_snapshot()` liest Equity/Cash/Positionen live über den
`BrokerAdapter`, berechnet `pnl_unrealized` (Summe über offene Positionen),
`max_drawdown` (aus der wachsenden Snapshot-Historie, gleiche Logik wie F020s
Peak-Equity), persistiert beide Tabellen. Aufgerufen am Ende von
`analyze_persona_cycle` — für jede Persona, jeden Zyklus, unabhängig vom
Decision-Ergebnis (auch bei `hold`/leerem Recherche-Pool soll die Zeitreihe für
Drawdown/Leaderboard nicht lückenhaft sein). **Non-Scope:** `pnl_realized` bleibt `0`
(es gibt noch keinen `sell`/`close`-Pfad, also nichts Realisiertes, siehe F021 §1);
`benchmark_value` bleibt `NULL` (SPY-Benchmark-Portfolio ist explizit P5-Scope,
ARCHITECTURE.md §8 P5); keine Telegram-Digest-Anbindung selbst (der Digest-Renderer
ist seit F005 fertig, aber ihn mit diesen neuen Snapshots zu füttern ist ein
eigener, kleiner Folgeschritt in `bot.py`, nicht Teil dieses Features).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Reine Code-Arithmetik (Summen, Differenzen) aus Broker-Rohdaten — kein LLM-Call in diesem Feature. |
| Broker-Zugriff ausschließlich über `BrokerAdapter` | ja | Nutzt denselben, bereits an `analyze_persona_cycle` übergebenen Adapter — keine zweite Adapter-Instanz, kein zusätzlicher Credential-Zugriff. |
| Fairness | ja | Identischer Snapshot-Code für alle 6 Personas — Aufruf immer am selben Punkt im Ablauf (Ende von `analyze_persona_cycle`), unabhängig vom Decision-Ausgang. |
| Keine stillen Annahmen bei Geld-Themen | ja | `pnl_realized=0` und `benchmark_value=None` sind bewusste, hier dokumentierte Auslassungen (fehlende Voraussetzungen), keine erfundenen Platzhalterwerte. |

**Design-Entscheidungen:**
- **Peak-Equity-Berechnung dupliziert (bewusst, minimal) aus F020**, nicht importiert
  — `read_portfolio_risk_state` liefert ein `PortfolioRiskState`-Objekt mit anderer
  Bedeutung (Risk-Gate-Eingabe, nicht Snapshot); ein Import hätte eine künstliche
  Kopplung zwischen Risk-Inputs und Reporting erzeugt. Die eigentliche
  MAX-Query (`select(func.max(PortfolioSnapshot.total_value))`) ist zwei Zeilen —
  eine gemeinsame Helper-Funktion wäre hier mehr Indirektion als Ersparnis.
- **Aufruf am Ende von `analyze_persona_cycle`, kein eigener Graph-Knoten** —
  dieselbe Begründung wie F023 (Branch-lokale Daten über Send-Kanäle sind ohne
  `Annotated`-Reducer kollisionsgefährdet); die Modulgrenze
  (`src/orchestrator/reporting.py`) trägt die Verantwortung, nicht die
  Graph-Topologie.
- **Läuft auch bei leerem Recherche-Pool nicht** (die Funktion `analyze_persona_cycle`
  kehrt dort bereits mit `return None` zurück, bevor der Reporting-Aufruf erreicht
  wird) — bewusste Grenze: ohne jeglichen Zyklus-Fortschritt für diese Persona macht
  ein weiterer Snapshot mit identischen Werten wie der letzte keinen Erkenntnisgewinn,
  würde die Tabelle nur unnötig aufblähen. Sobald ein Zyklen-Scheduler existiert und
  eine Kadenz "immer, auch ohne neue Recherche" gewünscht ist, ist das eine bewusste
  spätere Entscheidung, keine stille Lücke.

**Kosten:** keine LLM-Calls. **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_reporting.py` (Fake-`BrokerAdapter`, echte DB):
1. `generate_portfolio_snapshot` persistiert `portfolio_snapshot` mit
   `total_value=equity`, `cash`, `pnl_unrealized` = Summe der Positions-P&L.
2. Persistiert je offener Position eine `position_snapshot`-Zeile mit korrekten
   Feldern.
3. Keine offenen Positionen → `pnl_unrealized=0`, keine `position_snapshot`-Zeilen.
4. Ohne vorherige Snapshot-Historie → `max_drawdown=0` (aktuelle Equity ist der
   Peak).
5. Mit einer historischen Snapshot-Zeile mit höherem `total_value` →
   `max_drawdown` korrekt berechnet (`(peak - aktuell) / peak`).
6. `pnl_realized` ist immer `0`, `benchmark_value` immer `None` (dokumentierter
   Non-Scope).

`tests/orchestrator/test_persona_analysis.py` (Ergänzung):
7. Nach einer `hold`-Analyse existiert ein `portfolio_snapshot` für diesen Zyklus.
8. Bei leerem Recherche-Pool (Rückgabe `None`) existiert **kein** neuer Snapshot.

## 4. Implementierung

`src/orchestrator/reporting.py` (`generate_portfolio_snapshot`),
`src/orchestrator/persona_analysis.py` (Aufruf am Ende von `analyze_persona_cycle`).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_reporting.py -q` → 6 passed. `uv run pytest
tests/orchestrator -q -m 'not integration'` → 59 passed, 2 deselected (inkl. der 2
neuen Ergänzungen in `test_persona_analysis.py`). `uv run pytest tests/orchestrator
-q -m integration` → 2 passed (unverändert — der Fake-Adapter aus F023 implementiert
bereits `get_positions`/`get_account_balance`). `uv run pytest -q -m 'not
integration'` (Gesamtsuite) → 337 passed, 4 deselected. `uv run ruff check`/`ruff
format --check` → sauber. `uv run mypy src/orchestrator src/llm src/personas
src/risk src/broker src/db src/telegram` → sauber.

**Live-Verifikation (2026-07-07, rein lesend — kein Order-Vorgang, daher ohne
Rückfrage):** `generate_portfolio_snapshot` gegen den echten `AlpacaPaperAdapter`
für VULTURE ausgeführt: `total_value`/`cash` = 4.999,73 USD (spiegelt die zuvor in
F023 live platzierte, noch nicht gefüllte AAPL-Order wider — Buying Power
reserviert, aber noch keine offene Position), `pnl_unrealized=0` (Order noch nicht
gefüllt), `max_drawdown=0` (erster Snapshot überhaupt, aktuelle Equity ist der
Peak).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert (außer dem einen neuen
Aufruf in `persona_analysis.py`), kein Schema (nutzt `portfolio_snapshot`/
`position_snapshot` aus F003). Rollback = Commit zurücknehmen.
