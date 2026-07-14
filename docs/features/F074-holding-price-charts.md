# F074 — Kurs-Charts für Bestandswerte auf der Persona-Detailseite

Status: umgesetzt, live verifiziert (Backend + Browser-Rendering, siehe §5)
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
- **Coverage (nachträglich geprüft, Ralfs Auftrag "prüfe... ob die neue
  Funktion ausreichend mit Tests versorgt ist"):** `src/api/routes.py`,
  `src/broker/registry.py`, `src/ingestion/market_data_sync.py` — alle drei
  **100 % Line- und Branch-Coverage**. `src/broker` und `src/risk` insgesamt
  weiterhin **100 %** (Pflicht laut CLAUDE.md: ≥ 90 % Lines) — durch dieses
  Feature nicht verschlechtert.
- `web`: `npm run lint` (ESLint) und `npx tsc --noEmit` (TypeScript strict):
  beide clean, keine Fehler.
- **Backend live gegen echte lokale Daten geprüft:** lokaler Uvicorn gegen
  den Test-Postgres, Demo-Persona VULTURE mit echten `OrderRecord`/`Decision`-
  Fills und ~4 Wochen `market_bar`-Historie für AAPL/SOUN seed-eingespielt
  (temporäres, nicht committetes Skript). `GET /api/personas/VULTURE/chart?
  instrument=AAPL` liefert das erwartete JSON: Tages-Bars ab dem korrekten
  Start-Datum (erster Fill minus 2 Tage, Wochenenden korrekt ausgelassen),
  beide Buy-Fills mit korrektem Preis/Menge, `live_price: null` (kein
  Alpaca-Key lokal gesetzt) — bestätigt den Graceful-Degradation-Pfad live,
  nicht nur im Mock-Test.
- **Browser-Rendering live verifiziert.** Erster Versuch über
  `preview_start` scheiterte an zwei getrennten Problemen: (1) die lokale
  Maschine hat `/usr/local/bin/node` (20.5.1, altes Standalone-Install) vor
  `/opt/homebrew/bin/node` (25.5.0, Homebrew) im PATH — Next.js 16.2.10
  verlangt ≥ 20.9.0, `next dev` brach sofort mit der Versionsmeldung ab;
  behoben durch PATH-Präfix `/opt/homebrew/bin` in `.claude/launch.json`s
  `web`-Config (lokal, kein globaler PATH-/Shell-Rc-Eingriff). (2) Danach
  hing der `preview_start`-Tool-eigene Sandbox-Wrapper (`disclaimer`-Helper)
  beim Spawnen des Dev-Servers unabhängig davon dauerhaft (weder Turbopack
  noch `--webpack` halfen) — isoliert durch Vergleich: identischer Befehl
  über die Bash-Tool direkt gestartet lief sofort fehlerfrei
  (`✓ Ready in 344ms`), über `preview_start` nie. Das ist ein Problem der
  Preview-Tool-Infrastruktur selbst, nicht des Repos — nicht weiter verfolgt.
  **Tatsächliche Verifikation:** API + Web-Dev-Server direkt per Bash im
  Hintergrund gestartet (bypassed `preview_start`), Ralf hat
  `http://localhost:3000/personas/VULTURE` selbst im Browser geöffnet und
  bestätigt ("funktioniert") — AAPL/SOUN-Charts mit Kauf-Markern sichtbar,
  Live-Preis-Punkt korrekt abwesend (kein lokaler Alpaca-Key).
- **Test-DB-Hygiene (wiederholt aufgetreten, festgehalten für künftige
  Sessions):** das Demo-Seed-Skript committet echte Zeilen (kein
  Test-Rollback) in denselben lokalen Test-Postgres, den `pytest` nutzt.
  `_migrated_schema`s `upgrade("head")` ist bei bereits aktuellem Schema ein
  No-Op — vorhandene Seed-Daten überleben dadurch in die nächste
  `pytest`-Session und kollidieren dort (u. a. Unique-Constraint auf
  `persona.name`, ~55-63 Testfehler, abhängig vom Seed-Umfang). Erst der
  Session-Teardown (`downgrade("base")`, am Ende eines vollständigen
  `pytest`-Laufs) räumt auf. Wer lokal sowohl Demo-Daten für den Browser
  *als auch* `pytest` gegen dieselbe DB braucht: erst `pytest` fertig laufen
  lassen (räumt selbst auf), dann `alembic upgrade head` + Seed-Skripte
  *danach* — nicht dazwischen wechseln, ohne das Seeding zu wiederholen.

## 6. Rollback-Pfad

Rein additiv: neuer Endpoint, neue Schemas, neue Frontend-Komponente, zwei
umbenannte (aber sonst unveränderte) Funktionen in `registry.py`. Kein
Schema-/Migrations-Change, keine Änderung an bestehenden Endpoints oder
UI-Sektionen außerhalb der neuen Chart-Einfügung. Revert = Commit
zurücknehmen.

## 7. Offener Punkt für Ralf

`/usr/local/bin/node` (20.5.1) verdeckt weiterhin systemweit
`/opt/homebrew/bin/node` (25.5.0) im PATH — der Fix in `.claude/launch.json`
behebt das nur für die dortige `web`-Launch-Config, nicht für ein manuelles
`npm run dev` in einem normalen Terminal (das würde weiterhin die alte
20.5.1 zuerst finden und mit derselben Versionsmeldung abbrechen, sofern
nicht `PATH=/opt/homebrew/bin:$PATH` vorangestellt wird). Falls das den
normalen lokalen Workflow stört: `/usr/local/bin/node` entfernen/aktualisieren
oder PATH-Reihenfolge in der Shell-Konfiguration dauerhaft anpassen —
absichtlich nicht automatisch gemacht (globale Shell-Konfiguration, siehe
CLAUDE.md "keine stillen Annahmen").
