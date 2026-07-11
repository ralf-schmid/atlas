# F068 — aktienfinder-Screener als dynamische Kandidatenquelle

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

Ralfs Auftrag: *"6 aktienfinder Aktien ist viel zu wenig. Eigentlich möchte
ich gar keine Einschränkung, wenn es nicht anders geht brauchen wir min. 100
verschiedene Papiere. Ich habe ein kostenpflichtiges Abo von aktienfinder,
wir haben also genau die Daten, die wir benötigen. Vorherige Aussage ist
widerrufen. Nutze das Tool aktiv für die Suche nach der Anmeldung."*

Widerruft explizit [F037](F037-aktienfinder-candidate-list-and-scheduling.md)s
Begründung ("kein Fundamental-Screener ohne kostenpflichtigen Datenanbieter")
— siehe [ADR-0006](../adr/0006-aktienfinder-screener-instead-of-static-list.md)
für die vollständige Architektur-Entscheidung.

**Scope:** paginierte Discovery über aktienfinder.nets Screener-Tool-Grid
(`/aktienfinder`), Wiring in dieselbe Preis-/Indikator-/Research-Pool-Pipeline
wie F066/F067. **Non-Scope:** vollständiges Abschöpfen aller ~7 800
getrackten Werte (siehe ADR §"Betrachtete Optionen"); die bestehende
6er-`candidate_isins`-Liste (F037, tieferer Profilseiten-Grab inkl.
Dividenden-Historie) bleibt unverändert bestehen, komplementär zu diesem
Feature.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein, gestärkt | Ein gemeinsamer Discovery-/Sync-/Berechnungspfad — alle 6 Personas sehen dieselben 164 neuen `aktienfinder_screener`-Research-Items im Pool, keine Persona bekommt exklusiven Zugriff. |
| Agenten lesen nur aus der DB | nein | Der Discovery-Scrape ist ein Ingestion-Job (wie jeder andere), keine Persona ruft aktienfinder während ihrer Analyse selbst auf. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | nein | Reine DOM-Extraktion aus dem Grid, keine Interpretation im Code. |
| Keine stillen Annahmen bei Geld-Themen | ja, beachtet | Region-Filter ("Nordamerika") ist nur ein Vorfilter, nicht die Freigabe — jeder Kandidat wird zusätzlich gegen Alpacas echtes Tradable-Asset-Verzeichnis geprüft (gleiches Prinzip wie F067), bevor er den Pool erreicht. |
| Kosten | ja, geprüft | Keine LLM-Calls. Scrape-Last gegen aktienfinder.net: 2 Seiten à 100 Zeilen für 164 Treffer (deutlich unter `max_pages=10`) — ein Login + 2 Page-Loads, kein unverhältnismäßiger Traffic. |

**Design-Entscheidungen:**
- **Grid-Zeile statt Profilseiten-Besuch als Datenquelle.** Live geprüft:
  jede Grid-Zeile trägt ISIN *und* Ticker direkt im DOM
  (`<div class="isinSymbol"><a>ISIN</a> | <span>TICKER</span></div>`) plus
  ~65 weitere Spalten (Kurs, Kursziel, Stabilitäts-Scores, KGV,
  Kursgewinn-Historie, ...). Ein separater Profilseiten-Besuch pro Kandidat
  (wie der bestehende Deep-Grab-Pfad) ist für die Breiten-Discovery
  unnötig — ein Grid-Seiten-Load liefert 100 vollständige Kandidaten auf
  einmal.
- **`ticker`, nicht `isin`, als `instruments`-Wert.** Der bestehende
  Deep-Grab-Pfad (`AktienfinderSnapshot`, F012) speichert `symbol=isin` —
  ein latenter, hier entdeckter Mismatch gegenüber `market_bar`/Order-Placement
  (die Ticker erwarten). Für den neuen Discovery-Pfad bewusst korrekt gemacht
  (Ticker direkt aus dem Grid verfügbar); der alte Pfad bleibt unverändert als
  bekannter Folgepunkt (siehe ADR §Konsequenzen).
- **Region-Vorfilter ("Nordamerika") + Alpaca-Tradability als finale,
  autoritative Freigabe** — zwei-stufig, damit nicht Hunderte offensichtlich
  nicht handelbarer internationaler Titel überhaupt erst gesammelt werden,
  aber auch kein "Nordamerika"-Treffer ungeprüft durchgereicht wird (z. B.
  Kanada/TSX ist "Nordamerika", aber nicht zwingend Alpaca-handelbar).
- **`target_candidates`/`max_pages` als Config, nicht Konstanten** — Ralfs
  "eigentlich keine Einschränkung" wird durch Hochsetzbarkeit ohne
  Code-Änderung erfüllt, ohne dass der Job standardmäßig durch alle 78
  Seiten des Grids läuft.
- **Gleiches `screener_fields`-Mapping für beide Screener-Interaktionen**
  (per-ISIN-Suche, F043, und die neue Grid-Discovery) — ein Header-Text, ein
  friendly name, keine doppelte Pflege.
- **Zeitplan vor `market_data_sync`** (06:15 ET, vor 06:30) — die neu
  entdeckten Ticker müssen in der DB stehen, bevor `resolve_symbol_universe`
  für den Markt-Bar-Sync desselben Tages liest.

**Kosten:** keine LLM-Calls. **Fairness:** unverändert, gemeinsamer Pfad.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/ingestion/test_aktienfinder_screener.py`:
1. `_map_screener_grid_row` — Header/Zellen-Zuordnung, Region-Extraktion,
   unbekanntes Feld → `None`, fehlende Region-Spalte → leerer String.
2. `discover_candidates` (gegen eine Fake-`ScreenerGridPage`) — stoppt bei
   Erreichen von `target_candidates`, stoppt bei `max_pages` auch unterhalb
   des Ziels, stoppt an der letzten Seite, filtert nicht-passende Regionen
   heraus.
3. `sync_screener_candidates` — Insert, Upsert auf `(isin, discovered_at)`
   ohne Duplikate.

`tests/orchestrator/test_symbol_universe.py`:
- `test_includes_latest_aktienfinder_screener_tickers_only` — nur der
  jüngste Discovery-Batch zählt (gleiches Muster wie VULTUREs Screener).

`tests/orchestrator/test_research_synthesis.py`:
- `test_aktienfinder_screener_item_mapping_inside_window` — `instruments`
  ist der Ticker (nicht ISIN), Summary enthält Kursziel/Stabilität.
- `test_aktienfinder_screener_item_excluded_outside_window`.

`tests/ingestion/test_scheduler.py`: neuer Job registriert, alertet nach 2
Fehlschlägen in Folge (gleicher Non-Fatal-Vertrag).

## 4. Implementierung

- `src/db/models.py`: `AktienfinderScreenerCandidate` (neu).
- `alembic/versions/1e3b595921ab_add_aktienfinder_screener_candidate.py`
  (neu).
- `src/ingestion/aktienfinder_screener.py` (neu): `ScreenerCandidate`,
  `_map_screener_grid_row`, `PlaywrightScreenerGridPage`,
  `discover_candidates`, `sync_screener_candidates`,
  `run_screener_discovery_live`, `run_screener_discovery_configured`.
- `src/orchestrator/symbol_universe.py`: `_latest_aktienfinder_screener_tickers`
  + Einhängen in `resolve_symbol_universe` (gleiches Muster wie VULTUREs
  Screener).
- `src/orchestrator/research_synthesis.py`: neue
  `_research_items_from_aktienfinder_screener_candidates`,
  `source_type="aktienfinder_screener"`.
- `src/ingestion/scheduler.py`: `_aktienfinder_screener_discovery_job` +
  Registrierung (06:15 ET, vor `market_data_sync`).
- `config/ingestion.yaml`: `aktienfinder.screener_discovery`
  (`target_candidates: 150`, `max_pages: 10`, `regions: [Nordamerika]`),
  `screener_fields` um `price`, `dividend_yield`,
  `quality_score_dividend_stability`, `pe_ratio` erweitert (jetzt von beiden
  Screener-Interaktionen genutzt).
- `docs/adr/0006-aktienfinder-screener-instead-of-static-list.md` (neu).

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'`: 555 passed (14 neue Tests).
  `ruff check`/`format --check`, `mypy src/` (ganzes Repo): clean.
- Live-Reconnaissance **vor** Implementierung (echter Login, Ralfs Account):
  Grid hat 67 Spalten, ~7 800 Aktien über 78 Seiten (Seitenlänge max. 100);
  jede Zeile trägt ISIN + Ticker direkt im DOM
  (`.isinSymbol a` = ISIN, `.isinSymbol span` = Ticker); Beispiel:
  "1-800-FLOWERS.COM" → ISIN `US68243Q1067`, Ticker `FLWS`.
- Migration verifiziert: upgrade → downgrade → upgrade zyklisch getestet
  (lokaler Test-Postgres).
- Deployment: rsync (`models.py`, `aktienfinder_screener.py`,
  `scheduler.py`, `symbol_universe.py`, `research_synthesis.py`,
  `config/ingestion.yaml`, neue Migration) + `docker compose build api
  scheduler` + `up -d` + `alembic upgrade head` auf `atlas-ugreen`.
- **Live verifiziert** (echter Login, echter Scrape, Ralfs bezahlter
  Account):
  - `run_screener_discovery_configured` → **164 Kandidaten entdeckt**
    (deutlich über der geforderten Mindestzahl 100), nach dem
    Alpaca-Tradability-Filter, in 2 Grid-Seiten (weit unter `max_pages=10`).
  - Stichprobe: FLWS (1-800-FLOWERS.COM, Kurs 3.31, Kursziel 4.81,
    Stabilität Gewinn -0.18), ABNB (Airbnb, Kurs 129.87, Kursziel 137.71,
    Stabilität 0.87), ACGL (Arch Capital, Stabilität 0.82) — echte,
    plausible Werte über verschiedene Branchen/Qualitätsniveaus.
  - `resolve_stock_seed_watchlist` + `resolve_symbol_universe`:
    Gesamt-Preis-Universum wuchs von 182 auf **341 Symbole**; **20.940
    Bars** synct.
  - `compute_indicator_snapshot` für 5 zufällige neu entdeckte Ticker
    (ABNB, ACGL, ABG, ACAD, ACEL): alle 5/5 mit vollständigem SMA20 —
    sofort einsatzbereite technische Signale, nicht nur Fundamentaldaten.
  - `_research_items_from_aktienfinder_screener_candidates` (Dry-Run,
    `session.rollback()`, kein DB-Nebeneffekt): 164 Research-Items korrekt
    erzeugt, `instruments` = Ticker (nicht ISIN), Summary enthält
    Kurs/Kursziel/Stabilität.
  - Scheduler-Log nach Neustart bestätigt `_aktienfinder_screener_discovery_job`
    registriert neben allen bestehenden Jobs, keine Fehler.
- **Rollback-Pfad:** `ingestion-aktienfinder-screener-discovery`-Job-Registrierung
  entfernen + die eine Zeile in `resolve_symbol_universe`
  (`_latest_aktienfinder_screener_tickers`-Merge) sowie die eine Zeile in
  `synthesize_research_items`s `items`-Liste zurücknehmen +
  `alembic downgrade -1` (nur die eine neue Tabelle betroffen, keine
  Fremdschlüssel von anderen Tabellen darauf).
