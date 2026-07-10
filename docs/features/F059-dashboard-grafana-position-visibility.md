# F059 — Depot-Käufe in Dashboard und Grafana sichtbar machen

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Ralf: "Weder im Dashboard noch in Grafana kann ich die Käufe im Depot sehen."
Zwei getrennte Ursachen gefunden:

1. **Web-Dashboard (`/personas/{name}/holdings`):** liest ausschließlich die
   **letzte** `PortfolioSnapshot`/`PositionSnapshot`-Zeile. `generate_portfolio_
   snapshot` wird normalerweise am Ende jeder `analyze_persona_cycle`-Ausführung
   aufgerufen — aber F050s neuer `retry_stuck_decisions`-Sweep (der Weg, über
   den die beiden echten AAPL-/ALDX-Käufe heute Abend tatsächlich ausgeführt
   wurden) rief ihn **nicht** auf. Die Positionen waren real bei Alpaca
   vorhanden, aber ohne einen frischen Snapshot dauerhaft unsichtbar — bis
   irgendwann der nächste planmäßige Zyklus für diese Persona lief (in diesem
   Fall zufällig ~3 Minuten später der reguläre C4-Zyklus, aber im
   ungünstigen Fall wären das Stunden gewesen).
2. **Grafana:** Die "Portfolio"-Reihe im Dashboard hat nur aggregierte
   Ansichten (Wertverlauf, Leaderboard) — es gab überhaupt kein Panel, das
   zeigt, welche Positionen eine Persona aktuell tatsächlich hält.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #3 Keine Order ohne persistierte Decision | nein | Reine Sichtbarkeits-/Reporting-Lücke — die Decisions/Orders selbst waren immer korrekt persistiert, nur ihre Auswirkung auf den Portfolio-Zustand blieb unsichtbar. |
| Fairness | nein | Betrifft alle Personas gleich (gemeinsamer Snapshot-/Dashboard-Code). |

**Kosten:** keine.

## 3. Testdefinition

`tests/orchestrator/test_stuck_decision_sweep.py`: erweitert — eine
erfolgreich nachgeholte Decision erzeugt jetzt eine `PortfolioSnapshot`-Zeile
(vorher keine Prüfung); ein weiterhin fehlschlagender Broker-Aufruf erzeugt
weiterhin **keine** neue Snapshot-Zeile (Delta-Vergleich vor/nach, da die
Test-Persona über mehrere Testfunktionen hinweg denselben Portfolio-Datensatz
teilt — kein `session`-Rollback-Fixture in diesen `integration`-Tests, siehe
Moduldocstring).

## 4. Implementierung

- `src/orchestrator/scheduler.py`: `retry_stuck_decisions` ruft nach jedem
  erfolgreichen `execute_decision` zusätzlich `generate_portfolio_snapshot`
  auf (gleiches Muster wie `analyze_persona_cycle`).
- `config/grafana/atlas-overview-dashboard.json`: neues Panel "Aktuelle
  Positionen (Depot je Persona)" in der "Portfolio"-Reihe — `position_snapshot`
  gejoint auf die jeweils neueste `portfolio_snapshot.ts` je Portfolio.
  Nachfolgende Reihen/Panels um die neue Panel-Höhe nach unten verschoben,
  Dashboard-`uid` unverändert (Update, kein Duplikat).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_stuck_decision_sweep.py -q -m
integration` → 3 passed. `uv run pytest -q -m 'not integration'` → 502
passed, 10 deselected. `uv run pytest -q -m integration` → 8 passed, 2
skipped (unverändert). `uv run ruff check`/`ruff format --check` → sauber.
`uv run mypy src/orchestrator` → sauber. Grafana-SQL live gegen die echte
Box-DB verifiziert (siehe §6) — liefert exakt die beiden echten Positionen
(CHARTIST/AAPL, VULTURE/ALDX).

## 6. Live-Verifikation (2026-07-10, UGREEN)

- Web-API `GET /api/personas/CHARTIST/holdings` → liefert AAPL (qty 1,
  market_value 315.97). Gerenderte Seite `/personas/CHARTIST` enthält "AAPL"
  und "315,97" im "Bestand"-Abschnitt — bestätigt per `curl` gegen die echte
  laufende Next.js-Instanz.
- Grafana-Dashboard per `POST /api/dashboards/db` (`overwrite: true`)
  importiert → `200`, Version 2 → 3, gleiche `uid`. Neues Panel liefert live
  beide Positionen.

## 7. Rollback-Pfad

Scheduler-Änderung: Commit zurücknehmen (additiv, ein zusätzlicher Aufruf).
Grafana-Panel: alten Dashboard-JSON-Stand erneut importieren (`overwrite:
true`) oder Panel manuell in der UI löschen — keine Datenänderung, rein
darstellend.
