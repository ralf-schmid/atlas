# F100 — Portfolio-Verlauf der 6 Personas in der Web-Übersicht

**Status:** in Umsetzung (02.08.2026)
**Phase:** 5, Block 3 (UI-Ausbau) — Vorzieher aus [F085](F085-leaderboard-view.md)
**Auslöser:** Ralf, 02.08.2026 — „Verlauf der 6 Agenten im Zeitverlauf, Gesamtsumme
und Depotwert je Agent in einem Diagramm".
**Abhängigkeiten:** `portfolio_snapshot` (existiert seit P4),
`config/competition.yaml` (F081/F090 — Stichtag als Zeitachsen-Start).

## 1. Zieldefinition

Die Startseite (`web/src/app/page.tsx`) zeigt heute nur den **letzten** Snapshot je
Persona. Der Wettbewerb läuft seit 27.07.2026 — der Verlauf steckt vollständig in
`portfolio_snapshot` (ca. 5 Zeilen/Persona/Tag), war aber nirgends sichtbar.

**Scope:**
- API: `GET /api/portfolios/history?mode=paper` — je aktivem Portfolio die
  Snapshot-Zeitreihe ab Wettbewerbs-Stichtag mit drei Werten je Punkt:
  `total_value` (Gesamtsumme = Cash + Positionen, entspricht Broker-Equity),
  `position_value` (Depotwert = `total_value − cash`) und `cash`.
- UI: zwei Liniendiagramme (SVG, server-gerendert) über der Persona-Liste —
  oben Gesamtsumme, darunter Depotwert; je 6 Linien mit Legende, mobile-first
  (~390 px), Startkapital-Referenzlinie (5.000 USD) im Gesamtwert-Chart.

**Non-Scope (bewusst):**
- Kein Leaderboard/Ranking, keine Kennzahlen (Sortino, Drawdown, adjustiert) —
  das bleibt F085.
- Keine SPY-Benchmark-Linie (Daten lägen in `benchmark_value` bereit, gehört aber
  zur Leaderboard-Story F085; hier würde sie den Vergleich der 6 Personas nur
  überlagern).
- Keine Zeitraum-Filter, kein Zoom, keine Client-Interaktivität (YAGNI; der
  Chart bleibt eine reine Server-Component ohne JS-Bundle).

## 2. Kritische Betrachtung

- **Invarianten:** reiner Read-Pfad. Kein LLM, kein Broker-Call, keine
  Order-Rechte, keine Risk-Berührung. Kosten: 0 USD (kein LLM-Call).
- **Fairness:** identische Datenquelle und identische Darstellung für alle 6
  Personas; kein Informationsvorsprung, da die UI nur aggregierte Eigenwerte des
  jeweiligen Portfolios zeigt und Personas ohnehin nicht aus der UI lesen.
- **Berechnung im Code, nicht im Frontend/LLM:** `position_value` wird
  serverseitig als `Decimal(total_value) − Decimal(cash)` gerechnet
  (CLAUDE.md-Verbot: keine Finanz-Kennzahlen im LLM; Frontend zeichnet nur).
- **Archivierte Vorsaison:** der Endpoint filtert `Portfolio.archived_at IS NULL`
  (F090) **und** `ts >= competition.start_date`. Ohne beides würde der Chart die
  Vorsaison (08.–26.07.) mit dem Wettbewerb vermischen.
- **Datenlage-Risiko:** aktuell (02.08.) halten alle 6 Portfolios 0 Positionen,
  d. h. der Depotwert-Chart ist über die gesamte Achse 0. Das ist korrekt
  dargestellt, aber ein Hinweis auf ein separates Thema (geringe Trade-Aktivität
  seit Wettbewerbsstart) — kein Grund, die Darstellung zu schönen.

## 3. Design

- `PortfolioHistoryOut { start: date, series: [PortfolioHistorySeriesOut] }`,
  `PortfolioHistorySeriesOut { persona, display_name, points: [{ts, total_value,
  position_value, cash}] }`.
- Serien alphabetisch nach Persona-Name (deterministisch, keine Wertung durch
  Reihenfolge). Personas ohne Snapshot im Zeitraum liefern eine leere
  `points`-Liste und werden im Chart übersprungen.
- X-Achse **zeitproportional** (echter Timestamp, nicht Index) — die Snapshots
  liegen unregelmäßig (4–5 Zyklen werktags, 2 am Wochenende); eine Index-Achse
  würde Wochenenden künstlich strecken.
- Y-Achse: gemeinsamer Min/Max über alle Serien eines Charts, damit die 6 Linien
  vergleichbar sind. Beim Depotwert-Chart wird 0 immer eingeschlossen.
- Farben: feste Zuordnung Persona → Farbe in `web/src/lib/personaColors.ts`,
  damit Legende und Linien in beiden Charts konsistent bleiben.

## 4. Tests

Vor der Umsetzung definiert (Feature-Prozess §10):

**API (`tests/api/test_routes.py`, echtes Postgres-Schema):**
1. `test_get_portfolio_history_returns_series_per_persona` — zwei Personas mit
   je zwei Snapshots → zwei Serien, Punkte chronologisch aufsteigend.
2. `test_get_portfolio_history_computes_position_value` — `total_value 5200`,
   `cash 1200` → `position_value == 4000.0`.
3. `test_get_portfolio_history_excludes_archived_portfolios` — Vorsaison-
   Portfolio (`archived_at` gesetzt) taucht nicht auf.
4. `test_get_portfolio_history_starts_at_competition_start_date` — Snapshot vor
   dem Stichtag wird ausgefiltert.
5. `test_get_portfolio_history_defaults_to_paper_mode` — Live-Portfolio-Snapshot
   erscheint nicht in der Default-Antwort.
6. `test_get_portfolio_history_without_snapshots_returns_empty_series`.

**Frontend:** `npm run lint` + `npm run build` (Type-Check) — der Chart ist eine
reine Render-Funktion ohne Zustand; für die Punktberechnung gibt es keinen
Testrunner im Web-Teil (Bestand, kein neuer Aufbau in diesem Feature).

## 5. Live-Verifikation (02.08.2026)

Deployment: `rsync` auf die Box, `docker compose build api web scheduler
telegram-bot` + `up -d`. Keine Migration (kein Schema-Change).

- **Tests:** `pytest tests/api` → 39 passed (6 davon neu, F100). `ruff`,
  `mypy src/api`, `eslint`, `tsc --noEmit` grün.
- **Endpoint live:** `GET http://192.168.178.116:8000/api/portfolios/history`
  → `start: 2026-07-27`, `start_capital: 5000.0`, 6 Serien à ~35 Punkte,
  erster Punkt `2026-07-27T00:00:23` — d. h. Stichtag-Cutoff und
  `archived_at`-Filter greifen (die Vorsaison ab 08.07. taucht nicht auf).
- **UI live:** `http://192.168.178.116:3001/` liefert 200; im server-gerenderten
  HTML stehen beide Charts mit je **6** `<path>`-Linien, Achsenbeschriftung
  `5.000 $ / 4.992 $` bzw. `357 $ / 0 $` und `27.07. → 02.08.`, Legende mit
  Ist-Wert je Persona (5× 5.000 $, CONTRA 4.992 $; Depotwert aktuell 6× 0 $).
- **Datenbefund (kein Bug):** seit Wettbewerbsstart gibt es nur 5 Orders
  (CHARTIST 2, CONTRA 3) und aktuell 0 offene Positionen — die Gesamtwert-Linien
  liegen deshalb exakt übereinander (alle 5.000, CONTRA 4.992 nach realisiertem
  Verlust), der Depotwert zeigt nur einen kurzen Ausschlag auf 357 $. Die
  Darstellung ist korrekt; die geringe Handelsaktivität ist ein separates Thema.
- **Offen:** Sichtprüfung auf Ralfs Smartphone (~390 px) — Teil des
  P5-DoD-Punkts „UI … auf realem Smartphone getestet".

## 6. Rollback

Additiv: neuer Endpoint + neue Komponente + ein Block in `page.tsx`. Rollback =
`git revert` des Commits und Rebuild von `api`/`web`. Kein Schema-Change, keine
Migration, keine Config-Änderung, kein Datenverlust.
