# F008 — Marktdaten-Sync

Status: umgesetzt
Datum: 2026-07-05
Phase: 3

## 1. Zieldefinition

Erster P3-Baustein (ARCHITECTURE.md §8, P3-DoD Punkt "Marktdaten-Sync"): tägliche
OHLCV-Bars für ein konfigurierbares Symbol-Universum von Alpaca Market Data holen und
idempotent persistieren, als Grundlage für spätere, im Code berechnete technische
Indikatoren (§3.5.3 — "nie vom LLM"). Kein Agenten-/LLM-Code, reine Ingestion.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness/Shared Research Pool | ja | Genau ein Sync-Pfad, ein Datensatz pro Symbol/Tag — keine Persona bekommt eigene oder frühere Daten. `market_bar` ist keine Persona-Tabelle. |
| #6 Secrets nie im Repo | ja | `ALPACA_MARKET_DATA_KEY_ID`/`_SECRET_KEY` aus Environment, wie schon in `config/broker.yaml`/`registry.py` etabliert — hier dieselbe Konvention in `config/ingestion.yaml`. |
| Idempotenz aller Ingestion-Jobs (P3-DoD Punkt 6) | ja | `sync_market_bars` upsertet über `UniqueConstraint(symbol, timeframe, ts)` (`ON CONFLICT DO UPDATE`) — ein erneuter Lauf für denselben Tag erzeugt keine Duplikate, überschreibt nur mit den aktuellen Werten (z. B. nach Crash-Recovery). |

**Design-Entscheidungen:**
- **Neue Tabelle `market_bar`**, nicht Teil der ursprünglichen §3.6-Liste (die vor P3
  entstand) — ergänzt hier direkt im Feature-Dokument (kein separates ADR nötig, da
  keine Invariante/Entscheidung revidiert wird, nur eine in §3.5.3 vorgesehene, aber
  noch nicht spezifizierte Tabelle nachgezogen wird — gleiches Vorgehen wie bei den
  in F003 dokumentierten Status-Enums).
- **Watchlist statt volles Alpaca-Universum:** `market_data_sync` bedient ein
  konfigurierbares Symbol-Set (`config/ingestion.yaml`), nicht die 10.000+ Symbole des
  gesamten Alpaca-Verzeichnisses — das wäre unnötige Last für Bars, die (noch) niemand
  anfragt. Das volle Universum durchsucht stattdessen der VULTURE-Screener (F010) über
  eine separate, günstigere Snapshot-Abfrage. Die Watchlist wird in P4 durch offene
  Positionen + Screener-Kandidaten ersetzt (aktuell eine statische Seed-Liste).
- **`AlpacaBarsProvider`/`BarsProvider`-Protocol** spiegelt das bestehende
  `MarketDataProvider`-Pattern aus `src/broker/market_data.py` — Sync-Logik bleibt ohne
  echten Alpaca-Client testbar.

**Kosten:** keine LLM-Calls. **Fairness:** ein Sync-Pfad für alle Personas.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/ingestion/test_market_data_sync.py`), Alpaca-Client gemockt für die
Provider-Tests, echte (lokale) Postgres-Instanz für die Sync-Tests (`tests/conftest.py`
-Pattern, wie in `tests/db`):

1. `AlpacaBarsProvider.get_daily_bars` mappt ein `BarSet` korrekt auf `Bar`-Dataclasses.
2. `AlpacaBarsProvider.get_daily_bars` liefert `[]` für Symbole ohne Bars (kein Crash).
3. `sync_market_bars` mit leerer Symbolliste → `0`, kein DB-Zugriff nötig.
4. `sync_market_bars` fügt neue Bars ein, per DB-Query verifiziert.
5. `sync_market_bars` zweimal mit unterschiedlichen Werten für denselben
   `(symbol, timeframe, ts)` → genau eine Zeile, mit den Werten des zweiten Laufs
   (Idempotenz-Nachweis).
6. `run_daily_sync` liest Watchlist + Env-Var-Namen aus einer Config-Datei und ruft den
   Sync korrekt auf.
7. `run_daily_sync` wirft eine klare `ValueError`, wenn die konfigurierte Env-Var fehlt.

## 4. Implementierung

`src/ingestion/market_data_sync.py` (`Bar`, `BarsProvider`, `AlpacaBarsProvider`,
`sync_market_bars`, `run_daily_sync`), `src/db/models.py` (`MarketBar`,
`MarketBarTimeframe`), Migration `alembic/versions/71687961eb9f_add_market_bar.py`,
`config/ingestion.yaml`.

## 5. Testdurchlauf

`uv run pytest tests/ingestion tests/db -q` → alle Tests grün (gegen lokal gestartete
Postgres-Instanz, `pgvector/pgvector:pg17`). `uv run pytest -q` (Gesamtsuite) → 193
passed. `uv run ruff check`/`ruff format --check` → sauber. `uv run mypy src/ingestion`
→ sauber. Migration manuell im upgrade→downgrade→upgrade-Zyklus verifiziert (ENUM-Typ
`market_bar_timeframe` wird beim Downgrade explizit gedroppt, gleiches Muster wie in
`03bc1183d4b5`).

**Noch offen (P4/Ops-Folgearbeit):** `run_daily_sync` ist noch nirgends automatisch
geplant — das Scheduling folgt mit dem Orchestrator (P4) bzw. einem einfachen Cron auf
der UGREEN, bis der Orchestrator steht.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert. Rollback = Commit
zurücknehmen + `alembic downgrade -1` (getestet, s. o.).
