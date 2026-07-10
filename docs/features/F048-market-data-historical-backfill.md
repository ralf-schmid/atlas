# F048 — Markt-Bar-Backfill (technische Indikatoren waren strukturell unmöglich)

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

CHARTIST wiederholt live: *"Der aktuelle Research-Pool enthält ausschließlich
EDGAR Form-4/144/13F-Insider-Filings und BTC-Dominanz-Daten, jedoch keinerlei
code-berechnete Preis-/Volumenindikatoren (SMA-Crossover, RSI, MACD,
Bollinger, Breakouts) [...]. Ohne valide technische Signale kann ich keine
regelbasierte Entscheidung treffen."* Ralf: alle 6 Personas haben noch nie
gekauft, das macht den Test wertlos — welche zusätzlichen Infoquellen fehlen,
und was braucht CHARTIST konkret an Instrumenten?

Live-Diagnose (Box-DB, 10.07.2026): `market_bar` hatte für alle 92 Symbole
des Universums **exakt 1 Tages-Bar** (08.07.2026) — kein einziger Tag seither
nachsynct, trotz täglich geplantem `market_data_sync`-Job. Grund gefunden:
der Job hat immer nur `[trading_day, trading_day]` gesynct, nie mehr. Selbst
korrekt gelaufen, akkumuliert das nie genug Historie — `src/orchestrator/
indicators.py` braucht 15 Bars für RSI14, 20 für SMA20/Bollinger, 45+ für
MACD, 51 für einen SMA20/50-Crossover. **CHARTISTs Blockade war strukturell
unmöglich zu lösen, nicht zu streng** — die Charter-Kriterien sind unverändert
korrekt, es gab schlicht nie genug Rohdaten, damit sie greifen konnten.

**Scope:** Markt-Bar-Sync auf ein rollierendes Zeitfenster umstellen +
einmaliger Backfill der bestehenden Box-DB. **Non-Scope:** neue
Info-Quellen, Charter-Anpassungen (siehe §6 für die vollständige
Optionsübersicht, die Ralf dazu vorgelegt wurde).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein, gestärkt | `resolve_symbol_universe` + der Sync laufen für den gesamten geteilten Pool, nicht persona-spezifisch — CHARTIST, CONTRA und CRYPTOR (alle mit code-berechneten Momentum-/Trend-Signalen in ihrer Charter) profitieren gleichermaßen. |
| Persona-Charter unverändert | ja, geprüft | Kein `charter_version`-Bump — die Charter verlangten diese Daten immer schon (`src/personas/charters.py`), sie kamen nur nie an. |
| Kosten | ja, geprüft | Ein `StockBarsRequest` für 188 Symbole × 90 Tage ist ein einzelner HTTP-Call (Alpaca batcht serverseitig) — kein Kostenfaktor (keine LLM-Calls), keine erkennbare Rate-Limit-Gefahr auf dem kostenlosen IEX-Feed bei täglicher Kadenz. |

**Design-Entscheidungen:**
- **Rollierendes Fenster statt einmaliger Backfill-Sonderlauf.** `run_daily_sync`
  bekommt einen `lookback_days`-Parameter (Default `1`, rückwärtskompatibel);
  der Scheduler-Job liest `market_data.lookback_days` (neu, `90`) aus
  `config/ingestion.yaml`. Idempotent (`sync_market_bars` upsert-t) — jeder
  tägliche Lauf synct effektiv die letzten 90 Tage neu, nicht nur den
  aktuellen. Das macht den Job **selbstheilend**: der eigentliche Auslöser
  dieses Bugs (der Job feuerte am 09.07. vermutlich nicht, während der
  `scheduler`-Container mehrfach für andere Fixes neu gebaut wurde) kann sich
  nicht wiederholen — ein verpasster Tag wird am nächsten Lauf automatisch
  nachgeholt.
- **Warum nicht "nur neue Symbole backfillen"?** Wäre komplexer (Tracking,
  welche Symbole schon genug Historie haben) für denselben Effekt bei
  vernachlässigbarem Kostenunterschied — ein rollierendes 90-Tage-Fenster ist
  einfacher, robuster und deckt auch das ursprüngliche Symptom (fehlende
  Tage bei bestehenden Symbolen) mit ab.
- **90 Tage** deckt `_MIN_BARS_FOR_CROSSOVER` (51 Handelstage) mit Puffer für
  Wochenenden/Feiertage.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/ingestion/test_market_data_sync.py`:
- `test_run_daily_sync_defaults_to_a_single_day_window` — Default-Verhalten
  unverändert (Regressionsschutz für bestehende Aufrufer).
- `test_run_daily_sync_with_lookback_days_backfills_a_rolling_window` —
  `lookback_days=90` fragt exakt `[trading_day - 89 Tage, trading_day]` an.

## 4. Implementierung

- `src/ingestion/market_data_sync.py`: `run_daily_sync` neuer Parameter
  `lookback_days: int = 1`; berechnet `start = trading_day -
  timedelta(days=lookback_days - 1)`, ruft `sync_market_bars(session,
  provider, watchlist, start, trading_day)`.
- `src/ingestion/scheduler.py`: `_market_data_job` liest
  `market_data_config.get("lookback_days", 1)` und reicht ihn durch.
- `config/ingestion.yaml`: `market_data.lookback_days: 90`.

## 5. Test & Rollout

- `uv run pytest`: 481 passed. `ruff check`/`format --check`, `mypy`: clean.
- Deployment: scp der drei geänderten Dateien (`market_data_sync.py`,
  `scheduler.py`, `config/ingestion.yaml`) + `docker compose build scheduler`
  + `up -d scheduler`.
- **Einmaliger manueller Backfill sofort nach Deploy** (nicht auf den
  nächsten 06:30-ET-Cron warten): `run_daily_sync` manuell mit
  `lookback_days=90` gegen die echte Box-DB ausgeführt — Ergebnis siehe
  `docs/deployment.md` (Datum, Bar-Anzahl, erster erfolgreicher
  `technical_indicator`-Research-Item-Nachweis).
- **Rollback-Pfad:** `market_data.lookback_days` aus der Config entfernen
  (fällt auf Default `1` zurück) oder auf `1` setzen — kein Schema-Change.

## 6. Weitere Optionen, mit Ralf besprochen (nicht in diesem Feature)

Auf Ralfs Frage "welche zusätzlichen Infoquellen können wir anzapfen, wie
können wir die Agenten ändern" — Optionsübersicht, die zu diesem Feature
geführt hat:

1. **Markt-Bar-Backfill (dieses Feature)** — höchste Zuversicht, klarer
   Infrastruktur-Bug, keine Invarianten berührt. Umgesetzt.
2. **EDGAR-Filing-Inhalt (Form 4 Kauf/Verkauf-Code, Stückzahl, Preis)** —
   bereits in F044 §6 als Folge-Feature vorgemerkt (braucht neuen
   Fetch-Schritt gegen die Filing-Primärdokumente + CIK→Ticker-Zuordnung).
   Weiterhin offen, eigenes Feature-Dokument nötig.
3. **Neue geteilte Info-Quellen** (z. B. allgemeiner Finanz-News-Feed) —
   *nicht* umgesetzt, braucht Ralfs Entscheidung (neue Kosten-/
   Wartungslast, eigener Feature-Prozess-Durchlauf).
4. **Charter-Anpassungen** — *bewusst nicht* in Betracht gezogen. Die
   Charter waren korrekt; das Problem war Datenverfügbarkeit, nicht zu
   strenge Kriterien. Eine Charter-Änderung jetzt hätte das eigentliche
   Signal verdeckt statt es zu liefern (und hätte `charter_version`-Bump +
   ADR gebraucht, Invariante 1).
