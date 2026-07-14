# F074 — Kurs-Charts für Bestandswerte auf der Persona-Detailseite

Status: umgesetzt, Backend live gegen echte lokale Daten geprüft;
Browser-Rendering des Frontends **nicht** visuell verifiziert (Umgebungs-
Blocker, siehe §5)
Datum: 2026-07-14
Phase: 5

## 1. Zieldefinition

Ralfs Auftrag: auf den Persona-Detailseiten soll jeder Bestandswert
("Bestand"-Sektion) einen Kurschart des jeweiligen Wertpapiers zeigen —
Zeitraum von 2 Tagen vor dem (ersten) Kaufzeitpunkt bis heute, Kauf- **und**
Verkaufszeitpunkte grafisch markiert, plus einem **live gelesenen aktuellen
Kurs** (nicht nur dem letzten Tages-Close). Vorschlag zur Datenquelle:
onvista.de, ariva.de oder "einen anderen Dienst, den du gut automatisieren
kannst — vermutlich ist alpaca.markets eine gute Wahl."

**Recherche vor der Umsetzung:** Alpaca wird bereits als Marktdatenquelle
genutzt — kein Grund, onvista/ariva zu scrapen. `market_bar`
(`src/ingestion/market_data_sync.py`) wird täglich mit 90 Tagen Historie
gefüllt, deckt über `resolve_symbol_universe()` bereits alle offenen
Positionen ab. `MarketDataProvider.get_last_price()`
(`src/broker/market_data.py`) — Alpacas Latest-Trade-Endpoint — wird bereits
für die Fill-Preis-Simulation in `InternalLedgerAdapter` genutzt; ein
direkter Alpaca-Call aus Anwendungscode ist damit bereits etabliertes Muster,
kein Neuland. Details siehe Plan-Datei dieser Session (Architektur-
Entscheidungen, Datenmodell-Recherche zu Fills/Top-ups/F071).

**Scope:** ein neuer Read-Endpoint + eine neue, abhängigkeitsfreie
SVG-Chart-Komponente. **Non-Scope:** Zoom/Pan/Tooltip-Interaktivität (reine
Anzeige reicht für die Anforderung), Crypto-Backfill bei Datenlücken (siehe
§2), ein neues Frontend-Test-Framework (existiert für `web/` noch nicht,
kein Anlass, es für dieses eine Feature einzuführen).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein | Reine Anzeige-Funktion für Ralf, kein Persona-Prompt-/Entscheidungspfad berührt. |
| #7 Kosten-Caps | nein | Alpaca Market-Data-Calls (Bars + Latest-Trade) sind IEX/Free-Tier, laufen nicht durch `cost_ledger` — das betrifft ausschließlich LLM-Calls. |
| "Agenten lesen ausschließlich aus der DB" | teilweise, bewusst | Der Endpoint bleibt primär ein DB-Read (`market_bar`); der On-Demand-Live-Preis- und Backfill-Call ist ein *expliziter, dokumentierter* Ausnahmefall für einen reinen Anzeige-Endpoint (nicht für einen Agenten/Entscheidungspfad) — beide Calls sind `try/except`-gekapselt, ein Ausfall degradiert zu unvollständigen Chart-Daten statt zu einem 500er. |

**Design-Entscheidungen (Details siehe Plan-Datei):**
- `instrument` als Query-Parameter, nicht Path-Segment — Crypto-Symbole
  (`"BTC/USD"`) würden sonst das Routing brechen.
- Chart-Start = `MIN(filled_at)` über **alle** Fills (Buy und Sell) minus 2
  Tage; ohne Fills (Demo-/Seed-Positionen ohne `OrderRecord`) Fallback auf
  die letzten 30 Tage.
- On-Demand-Backfill bei Bar-Lücke ist **Stock-only** (kein `/` im Symbol) —
  Crypto-Lücken werden nicht automatisch nachgezogen, weil F064s
  Crypto-Watchlist offene Positionen ohnehin schon abdeckt (akzeptiertes
  Restrisiko, keine beobachtete Lücke).
- `build_market_data_provider`/`load_market_data_config` in
  `src/broker/registry.py` von `_`-privat auf öffentlich umbenannt (jetzt
  ein zweiter Aufrufer neben `get_adapter`) statt die Key-Lade-Logik zu
  duplizieren — gleiches Muster wie `build_default_provider` in
  `market_data_sync.py`.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/api/test_routes.py` (neue Factory `make_market_bar` in
`tests/db/factories.py`):
- Bars + gemischte Buy/Sell-Marker korrekt zurückgegeben, Start = erster
  Fill − 2 Tage, Fast-Path bestätigt (`build_default_provider` wird **nicht**
  aufgerufen, wenn die Bars die Range schon abdecken).
- Ohne Fills → 30-Tage-Fallback, leere `fills`-Liste.
- Bar-Lücke → Backfill-Pfad wird aufgerufen (Fake-Provider).
- Backfill- bzw. Live-Preis-Fehler → Endpoint liefert trotzdem 200 mit den
  vorhandenen Daten, kein 500.
- Unbekanntes/nicht gehaltenes Instrument → 404.
- Crypto-Symbol (`"BTC/USD"`) als Query-Param funktioniert, nutzt den
  Crypto-Provider für den Live-Preis.

## 4. Implementierung

- `src/ingestion/market_data_sync.py`: `build_default_provider()` — Key-Lade-
  Logik aus `run_daily_sync` extrahiert, jetzt von zwei Stellen genutzt.
- `src/broker/registry.py`: `_build_market_data_provider` → öffentlich
  `build_market_data_provider`; neue `load_market_data_config()`.
- `src/api/schemas.py`: `ChartBarOut`, `ChartFillMarkerOut`,
  `ChartLivePriceOut`, `HoldingChartOut`.
- `src/api/routes.py`: neuer Endpoint `GET /api/personas/{name}/chart?instrument=...`
  (`get_persona_holding_chart`) + Helfer `_read_market_bars`, `_try_backfill`,
  `_try_live_price`.
- `web/src/lib/api.ts`: `HoldingChart`-Typen + `getHoldingChart()`
  (`encodeURIComponent` für den Instrument-Query-Param — deckt `BTC/USD`).
- `web/src/components/PriceChart.tsx`: neue, abhängigkeitsfreie SVG-Line-
  Chart-Komponente (Server Component) — Linienpfad aus Bars + optionalem
  Live-Punkt, Dreieck-Marker für Buy (grün, aufwärts) / Sell (rot, abwärts),
  Live-Punkt als blauer Kreis, Achsenbeschriftung (Datum/Preis), Leerzustand
  ohne Kursdaten.
- `web/src/app/personas/[name]/page.tsx`: lädt pro Holding zusätzlich
  `getHoldingChart()` (parallel über alle Holdings), rendert `<PriceChart>`
  unterhalb der bestehenden Kennzahlen-`<dl>` je Bestandswert.
- `.claude/launch.json`: neue `api`-Launch-Config (lokaler Uvicorn gegen den
  lokalen Test-Postgres) für Preview/lokale Entwicklung.
- Kein Alembic-Migrations-Bedarf (keine Schema-Änderung).

## 5. Test & Verifikation

- `uv run pytest -q` (lokaler Test-Postgres): **592 passed** (7 neue Tests).
  `ruff check`/`format --check`, `mypy src/api src/broker src/ingestion`:
  clean.
- `web`: `npm run lint` (ESLint) und `npx tsc --noEmit` (TypeScript strict):
  beide clean, keine Fehler.
- **Backend live gegen echte lokale Daten geprüft:** lokaler Uvicorn gegen
  den Test-Postgres, Demo-Persona VULTURE mit echten `OrderRecord`/`Decision`-
  Fills und ~4 Wochen `market_bar`-Historie für AAPL/SOUN seed-eingespielt
  (temporäres, nicht committetes Skript). `GET /api/personas/VULTURE/chart?
  instrument=AAPL` liefert das erwartete JSON: 17 Tages-Bars ab dem
  korrekten Start-Datum (erster Fill minus 2 Tage, Wochenenden korrekt
  ausgelassen), beide Buy-Fills mit korrektem Preis/Menge, `live_price: null`
  (kein Alpaca-Key lokal gesetzt) — bestätigt den Graceful-Degradation-Pfad
  live, nicht nur im Mock-Test.
- **Nicht verifiziert: das tatsächliche Chart-Rendering im Browser.**
  `web/AGENTS.md`/Next.js 16.2.10 verlangt Node ≥ 20.9.0; die lokale
  Umgebung hat Node 20.5.1 installiert — `next dev` startet nicht
  (`npm run dev` bricht mit dieser Versionsmeldung ab, Port 3000 bleibt ohne
  Listener). Als Ersatz wurde die reine Skalierungs-/Marker-Mathematik der
  Komponente (Punktberechnung, Nearest-Bar-Zuordnung für Marker,
  SVG-Pfad-String) in einem eigenständigen Node-Skript gegen die echte
  API-Antwort nachgerechnet: keine NaN/Infinity-Werte, korrekte Punktzahl
  (17), korrekte Marker-Zuordnung (`2026-06-22`-Fill → Bar-Index 0,
  `2026-07-01`-Fill → Bar-Index 7), gültiger SVG-Pfad. Das prüft die Logik,
  aber **nicht** das tatsächliche visuelle Ergebnis (Layout, Lesbarkeit,
  Mobile-Darstellung ~390 px) — das braucht entweder ein Node-Upgrade auf
  ≥ 20.9.0 oder eine Prüfung durch Ralf selbst.
- **Test-DB-Hygiene:** das Seed-Skript hat versehentlich committete Demo-
  Daten im lokalen Test-Postgres hinterlassen (Kollision mit 55 Tests beim
  nächsten `pytest`-Lauf, u. a. Unique-Constraint auf `persona.name`) — via
  `alembic downgrade base` bereinigt, danach erneut **592 passed** bestätigt.

## 6. Rollback-Pfad

Rein additiv: neuer Endpoint, neue Schemas, neue Frontend-Komponente, zwei
umbenannte (aber sonst unveränderte) Funktionen in `registry.py`. Kein
Schema-/Migrations-Change, keine Änderung an bestehenden Endpoints oder
UI-Sektionen außerhalb der neuen Chart-Einfügung. Revert = Commit
zurücknehmen.

## 7. Offener Punkt für Ralf

Node-Version auf dieser Maschine (20.5.1) ist zu alt für `next dev`
(Next.js 16.2.10 verlangt ≥ 20.9.0) — betrifft nicht nur diese Session,
sondern jeden lokalen `npm run dev`-Start. Bitte Node aktualisieren (z. B.
via `nvm install 20.9.0` oder neuer), dann kann das Chart-Rendering visuell
geprüft werden. Bis dahin ist dieses Feature backend-seitig vollständig
verifiziert, frontend-seitig nur durch Typecheck/Lint/Logik-Nachrechnung,
nicht durch tatsächliches Rendering.
