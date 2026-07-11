# F064 — Krypto-OHLCV-Sync für CRYPTORs Momentum/Trend-Signale

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

CRYPTORs Live-Rückmeldung: *"Der aktuelle Research-Pool liefert für mein
Krypto-Universum (BTC/ETH/SOL) keine verwertbaren Momentum- oder
Trend-Signale [...]. Ohne ein echtes Momentum-/Sentiment-Signal auf BTC/ETH/SOL
sehe ich keine belastbare Handelsidee und bleibe bei Cash/Hold."* Bestätigt:
CRYPTORs Charter verspricht explizit "Momentum/Trend (code-berechnet)"
(`src/personas/charters.py`), aber es gab im gesamten Repo keine
OHLCV-Ingestion für Krypto — nur die BTC-Dominanz als Regime-Filter (F040).

**Scope:** neue Ingestion-Quelle für tägliche BTC/USD-, ETH/USD-, SOL/USD-Bars
+ Einhängen in die bereits vorhandene, symbol-agnostische
Technische-Indikator-Pipeline (F036: SMA-Crossover, RSI14, MACD, Bollinger).
**Non-Scope:** neue Sentiment-Quelle (Reddit existiert bereits, F039, nur noch
ohne Zugangsdaten), Krypto-spezifische Indikatoren.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Ein gemeinsamer Sync-Pfad, dieselbe `market_bar`-Tabelle, dieselbe symbol-agnostische Indikator-Berechnung (F036) wie jede Aktie — keine Persona bekommt exklusiven Zugriff; alle 6 Personas sehen dieselben Krypto-Indikator-Items im Pool (auch wenn nur CRYPTOR sie handeln darf). |
| #6 Secrets nie im Repo | nein | Wiederverwendet den bereits vorhandenen `ALPACA_MARKET_DATA_KEY_ID`/`_SECRET_KEY` (Paper-Key) — kein neues Secret. Live verifiziert: Krypto-Marktdaten brauchen kein separates Entitlement. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Reine Code-Berechnung über `src/orchestrator/indicators.py` (unverändert von F036) — die Persona bekommt fertige SMA/RSI/MACD/Bollinger-Werte. |
| Kosten | nein | Keine LLM-Calls, kein neuer Anbieter/keine neuen Kosten (gleicher Alpaca-Paper-Marktdaten-Zugang). |

**Design-Entscheidungen:**
- **Eigener Provider (`AlpacaCryptoBarsProvider`, `CryptoHistoricalDataClient`)
  statt Erweiterung des Stock-Providers.** `AlpacaBarsProvider` nutzt
  `StockHistoricalDataClient`/`StockBarsRequest` mit `DataFeed.IEX` — das
  würde für Krypto-Symbole fehlschlagen. Live verifiziert: Krypto-Bars
  brauchen keinen `feed`-Parameter (kein IEX/SIP-Unterschied). `Bar`-Dataclass
  und `sync_market_bars`-Upsert (`market_data_sync.py`) werden unverändert
  wiederverwendet — `market_bar` hat keine Asset-Klassen-Spalte, ein Symbol
  ist nur ein String ("BTC/USD" wie "AAPL").
- **Eigene Config-Sektion `crypto_market_data` statt Erweiterung von
  `market_data.watchlist`.** Getrennter Sync-Job (anderer Provider), aber
  `research_synthesis.py::synthesize_research_items` vereinigt beide
  Watchlists vor `resolve_symbol_universe`, sodass die bereits bestehende,
  unveränderte `_research_items_from_technical_indicators`-Funktion (F036)
  Krypto-Symbole genau wie Aktien verarbeitet — kein Code-Zweig für
  Asset-Klassen nötig.
- **Intervall-Scheduling (60 Min) statt fixer ET-Zeit** — CRYPTOR hat "keinen
  Börsenschluss" (Charter), Krypto-Zyklen laufen 00/06/12/18 UTC
  (`config/cycles.yaml`); ein stündlicher Sync stellt sicher, dass vor jedem
  Zyklus frische Bars vorliegen.
- **90 Tage Lookback von Anfang an** (nicht `lookback_days=1` mit späterem
  F048-Nachbessern) — die Lehre aus F048 (technische Indikatoren brauchen bis
  zu 51 Bars) wird hier direkt eingebaut, kein Backfill-Sonderlauf nötig.

**Kosten:** keine. **Fairness:** unverändert (gleicher gemeinsamer
Sync-/Berechnungspfad).

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/ingestion/test_crypto_market_data_sync.py`:
1. `AlpacaCryptoBarsProvider` mappt `BarSet` korrekt auf `Bar`-Dataclass.
2. Inklusive Tagesende-Grenze bei Start==End (gleiche Vorsicht wie beim
   Stock-Provider).
3. Symbole ohne Bars werden übersprungen.
4. `run_daily_crypto_sync` liest Config/Env korrekt.
5. Default-Lookback ist 90 Tage (nicht 1 wie beim Stock-Sync).
6. Fehlende Env-Var wirft `ValueError`.

`tests/ingestion/test_scheduler.py`: neuer Job `ingestion-crypto-market-data`
registriert, alertet nach 2 Fehlschlägen in Folge (gleicher Non-Fatal-Vertrag).

`tests/orchestrator/test_research_synthesis.py`:
`test_technical_indicator_item_emitted_for_crypto_watchlist_symbol_with_enough_bars`
— BTC/USD aus `crypto_market_data.watchlist` erzeugt genau ein
`technical_indicator`-Research-Item mit SMA20/RSI14 im Summary, identisch zum
bestehenden Test für AAPL.

## 4. Implementierung

- `src/ingestion/crypto_market_data_sync.py` (neu): `AlpacaCryptoBarsProvider`,
  `run_daily_crypto_sync`.
- `src/ingestion/scheduler.py`: `_crypto_market_data_job` + Registrierung
  (60-Minuten-Intervall).
- `src/orchestrator/research_synthesis.py`: `synthesize_research_items`
  vereinigt `market_data.watchlist` und `crypto_market_data.watchlist` vor
  `resolve_symbol_universe`.
- `config/ingestion.yaml`: neue `crypto_market_data`-Sektion
  (`watchlist: [BTC/USD, ETH/USD, SOL/USD]`, `lookback_days: 90`) +
  `schedule.crypto_market_data_sync.interval_minutes: 60`.
- Kein Alembic-Migrations-Bedarf (keine Schema-Änderung, `market_bar` nimmt
  Krypto-Symbole ohne Änderung auf).

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'` (lokaler Test-Postgres): 533
  passed. `ruff check`/`format --check`, `mypy`: clean.
- Deployment: rsync (`crypto_market_data_sync.py`, `scheduler.py`,
  `research_synthesis.py`, `config/ingestion.yaml`) + `docker compose build
  api scheduler` + `up -d` auf `atlas-ugreen`.
- **Live verifiziert** (echte Alpaca-API, echter Paper-Key):
  `run_daily_crypto_sync` synct **270 Bars** (90 Tage × 3 Symbole,
  13.04.–11.07.2026) beim ersten Lauf.
  `compute_indicator_snapshot` direkt gegen die echte DB + `render_charter`
  gegen CRYPTORs tatsächlichen Systemprompt geprüft — die Charter verlangt
  "Momentum/Trend (code-berechnet)", geliefert wird exakt das:
  ```
  BTC/USD -> SMA20 unter SMA50 (61853.09 vs 65139.11), RSI14 67.5,
             MACD -112.64 (Signal -630.42, Histogramm 517.79),
             Bollinger-Baender [58162.53, 65543.66]
  ETH/USD -> SMA20 unter SMA50 (1687.52 vs 1767.60), RSI14 76.6,
             MACD 16.55 (Signal -2.41, Histogramm 18.96),
             Bollinger-Baender [1504.42, 1870.62]
  SOL/USD -> SMA20 über SMA50 (75.85 vs 74.56), RSI14 68.3,
             MACD 1.95 (Signal 1.97, Histogramm -0.02),
             Bollinger-Baender [65.92, 85.77]
  ```
  SOL/USD zeigt einen echten Golden-Cross (SMA20 > SMA50) bei RSI14 68.3 —
  ein konkretes, handlungsfähiges Trendsignal, das vor diesem Feature nicht
  existierte. Scheduler-Log nach Neustart bestätigt `_crypto_market_data_job`
  registriert neben allen bestehenden Jobs.
- **Rollback-Pfad:** `ingestion-crypto-market-data`-Job-Registrierung aus
  `register_ingestion_jobs` entfernen + die eine Zeile in
  `synthesize_research_items` (`crypto_watchlist`-Merge) zurücknehmen — reiner
  Code-Revert, kein Schema-Change. `market_bar`-Zeilen für Krypto-Symbole
  bleiben harmlos liegen (werden nur nicht mehr aktualisiert/gelesen).
