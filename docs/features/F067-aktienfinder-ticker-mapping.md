# F067 — aktienfinder-Kandidaten an die Preis-Pipeline anbinden

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

Live-Rückmeldung: *"Gerade hier kann aktienfinder genau die richtigen Impulse
liefern. Wieso nutzt der Agent das Tool nicht aktiv [...]. Setze die
besprochene Maßnahme endlich um."* Diagnose (siehe auch F045, das die vom
Nutzer erinnerte "besprochene Maßnahme" bereits einmal adressierte): das
Problem ist nicht fehlende Tool-Nutzung — `search_research_pool` (F045)
funktioniert und ist read-only per Architekturentscheidung (CLAUDE.md:
"Agenten lesen ausschließlich aus der DB", kein Live-Screener-Tool ist
vorgesehen). Das eigentliche strukturelle Loch: aktienfinders 6
ISIN-Kandidaten (`config/ingestion.yaml` `aktienfinder.candidate_isins`,
F037) liefern zwar Snapshot-Research-Items (Kursziel, Qualitäts-Scores), aber
**diese Symbole waren nie Teil von `resolve_symbol_universe`** — also nie im
täglichen Markt-Bar-Sync (`market_data_sync.py`) und nie in der
technischen-Indikator-Berechnung (F036) enthalten. `get_latest_price`
lieferte für sie `None`, ein Kauf wäre für keine Persona sizebar gewesen —
die aktienfinder-Daten "kamen an", waren aber praktisch nicht handelbar.

**Scope:** ISIN→Ticker-Zuordnung für die aktienfinder-Kandidaten + Einhängen
in dieselbe Preis-/Indikator-Pipeline wie jedes andere Symbol.
**Non-Scope:** ein aktives Live-Screener-Tool, das die Persona während ihrer
Analyse triggert (F045 hat diese Option bereits geprüft und bewusst gegen
"Tools, die neue externe Quellen anzapfen" entschieden — CLAUDE.md-Grenze
"Agenten lesen ausschließlich aus der DB" bleibt in diesem Feature
unverändert bestehen).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein, gestärkt | `resolve_stock_seed_watchlist` ist ein gemeinsamer Helper, genutzt von genau derselben Stelle wie F066 (Markt-Bar-Sync + Indikator-Berechnung) — keine Persona-exklusive Anbindung, alle Personas sehen dieselben zusätzlichen Preis-/Indikator-Items. |
| Agenten lesen nur aus der DB | nein | Reine Config-/Wiring-Änderung im bereits bestehenden Sync-Pfad — kein neuer Live-Zugriff während der Analyse. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | nein | Reine Code-Berechnung (F036, unverändert). |
| Keine stillen Annahmen bei Geld-Themen | ja, beachtet | Nicht angenommen, dass jede ISIN einen brauchbaren Alpaca-Ticker hat — jede einzelne live gegen Alpacas Asset-/Snapshot-Endpunkt geprüft (§5), Munich Re bewusst ausgeschlossen statt geraten. |

**Design-Entscheidungen:**
- **`aktienfinder.ticker_by_isin`-Mapping statt automatischer ISIN→Ticker-
  Auflösung.** Ein automatischer ISIN→Ticker-Resolver (z. B. über einen
  Fundamentaldaten-Anbieter) wäre der in F037 bewusst vertagte
  "echte Screener" — hier reicht eine von Ralf mitgepflegte Zuordnungstabelle
  direkt neben `candidate_isins`, gleiches Wartungsmuster wie F037 selbst
  ("Ralf pflegt die Liste manuell").
- **Nur live bestätigte, tatsächlich handelbare Ticker aufgenommen — nicht
  alle 6 ISINs.** Live gegen Alpacas `TradingClient`/`StockSnapshotRequest`
  geprüft:
  - SAP (DE-ISIN) → Ticker `SAP`, NYSE, `tradable=True`, echte Kursdaten
    ($157,81) — trotz deutscher ISIN als ADR handelbar.
  - Apple/Microsoft/Johnson & Johnson → AAPL/MSFT/JNJ, bereits über F066s
    erweiterte `market_data.watchlist` abgedeckt, hier zusätzlich explizit
    der ISIN zugeordnet (Konsistenz, kein Duplikat dank Dedup in
    `resolve_stock_seed_watchlist`).
  - Procter & Gamble → `PG`, NYSE, `tradable=True`, echte Kursdaten
    ($147,02) — bisher nicht in der Watchlist.
  - **Munich Re bewusst nicht gemappt:** kein NYSE-Listing (`MUV2` nicht bei
    Alpaca auffindbar), die einzige Alpaca-Alternative (`MURGY`, OTC-ADR)
    ist zwar `tradable=True`, hat aber **keine Snapshot-Kursdaten** im
    IEX-Feed (kein jüngster Trade) — ein gemappter Ticker ohne verwertbare
    Kursdaten wäre schlechter als gar keiner (stille Fehlannahme). Munich Re
    bleibt weiterhin als reines Snapshot-Research-Item im Pool sichtbar,
    nur ohne Preis-/Indikator-Anbindung.
- **Ein gemeinsamer Helper (`resolve_stock_seed_watchlist`) statt getrennter
  Logik in Sync-Job und Research-Synthese.** Vorher las sowohl
  `scheduler.py::_market_data_job` als auch
  `research_synthesis.py::synthesize_research_items` unabhängig
  `config["market_data"]["watchlist"]` — ein künftiges Hinzufügen einer
  weiteren Quelle hätte leicht an einer der beiden Stellen vergessen werden
  können (genau das ursprüngliche Symptom hier: aktienfinder-ISINs waren nur
  an der Ingestion-Seite bekannt, nie an der Preis-Seite). Ein Single Point
  of Truth verhindert dieses erneute Auseinanderdriften.

**Kosten:** keine (gleicher Sync-Pfad, marginal mehr Symbole).
**Fairness:** unverändert, gemeinsamer Pfad.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/orchestrator/test_symbol_universe.py`:
1. `test_resolve_stock_seed_watchlist_merges_market_data_and_aktienfinder_tickers`
   — Watchlist + ISIN-Ticker-Werte werden vereinigt.
2. `test_resolve_stock_seed_watchlist_deduplicates_overlap` — ein ISIN-Ticker,
   der bereits in der Watchlist steht, erzeugt kein Duplikat.
3. `test_resolve_stock_seed_watchlist_without_aktienfinder_section` —
   rückwärtskompatibel ohne `aktienfinder`/`ticker_by_isin`-Sektion.

## 4. Implementierung

- `src/orchestrator/symbol_universe.py`: neue Funktion
  `resolve_stock_seed_watchlist(config)`.
- `src/orchestrator/research_synthesis.py`: `synthesize_research_items`
  nutzt `resolve_stock_seed_watchlist` statt direkt
  `config["market_data"]["watchlist"]`.
- `src/ingestion/scheduler.py`: `_market_data_job` nutzt denselben Helper.
- `config/ingestion.yaml`: neue `aktienfinder.ticker_by_isin`-Sektion (SAP,
  AAPL, MSFT, JNJ, PG — Munich Re bewusst ausgelassen, siehe §2).
- Kein Alembic-Migrations-Bedarf.

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'`: 541 passed (3 neue Tests).
  `ruff check`/`format --check`, `mypy src/` (ganzes Repo): clean.
- Live-Prüfung **vor** Aufnahme in die Zuordnung (Alpaca `TradingClient` +
  `StockSnapshotRequest`, echte Paper-Marktdaten): AAPL/MSFT/JNJ/PG/SAP alle
  `tradable=True` mit echten Kursdaten; `MUV2` nicht auffindbar, `MURGY`
  zwar `tradable=True` aber ohne Snapshot-Kursdaten — daher ausgeschlossen.
- Deployment: rsync (`symbol_universe.py`, `research_synthesis.py`,
  `scheduler.py`, `config/ingestion.yaml`) + `docker compose build api
  scheduler` + `up -d` auf `atlas-ugreen`.
- **Live verifiziert** (echter `run_daily_sync` gegen die erweiterte
  `resolve_stock_seed_watchlist`, echte Box-DB): SAP und PG — vorher ohne
  jede Preis-/Indikator-Anbindung — haben jetzt beide echte
  `market_bar`-Daten (`get_latest_price`: SAP 157,81 $, PG 147,02 $) **und**
  vollständige technische Indikatoren (SMA20 vorhanden). 11.343 Bars
  insgesamt synct (gegenüber 11.219 vor diesem Feature, +2 neue Symbole ×
  ~62 Handelstage). Scheduler-Log nach Neustart fehlerfrei.
- **Rollback-Pfad:** `aktienfinder.ticker_by_isin` aus `config/ingestion.yaml`
  entfernen (der Helper fällt automatisch auf die reine
  `market_data.watchlist` zurück, rückwärtskompatibel getestet) — reiner
  Config-Revert, kein Schema-/Code-Change nötig für einen vollständigen
  Rollback.
