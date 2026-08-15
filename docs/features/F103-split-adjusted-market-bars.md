# F103 — Split-adjustierte Markt-Bars (Indikatoren rechneten auf Roh-Kursen)

Status: live auf der Box (15.08.2026), Backfill gelaufen — Nachweise §5
Datum: 2026-08-11
Phase: 4/5 (Datenqualität, wirkt auf F036/F048)

## 1. Zieldefinition

`AlpacaBarsProvider.get_daily_bars` (`src/ingestion/market_data_sync.py`) hat
`StockBarsRequest` nie ein `adjustment` mitgegeben. Damit gilt der API-Default
**`raw`**: Alpaca liefert die historisch tatsächlich gehandelten Kurse, ohne
Rückrechnung über Kapitalmaßnahmen. Ein 4:1-Split im Lookback-Fenster
erscheint in `market_bar` als −75 %-Tagessprung im Close.

Genau diese Serie ist die Eingabe von `src/orchestrator/indicators.py` (F036):
SMA20/SMA50 und der Crossover-Vergleich, RSI14, MACD(12/26/9), Bollinger(20, 2σ)
— alle rechnen auf `MarketBar.close`. Ein Roh-Split erzeugt dort

* einen SMA-Crossover, den es nie gab (der lange SMA hängt ~50 Tage im alten
  Kursniveau fest),
* ein RSI14 nahe 0 (der Split-Tag zählt als extremer Verlusttag),
* ein MACD-Histogramm mit falschem Vorzeichen,
* ein Bollinger-Band, dessen σ von einem künstlichen Ausreißer dominiert wird.

Diese Werte gehen als `research_item` mit `source_type='technical_indicator'` in
den geteilten Pool und sind für CHARTIST die Entscheidungsgrundlage; CONTRA und
CRYPTOR nutzen dieselben Signale. `compute_atr14` (`market_pricing.py`) — die
Basis der Stop-Loss-Distanz — leidet identisch: der Split-Tag wird zur größten
True Range des Fensters und bläht den ATR auf.

Aufgefallen bei der Bewertung von Alpacas Agent-Research-Tooling (ADR-0015): die
Run-Considerations-Checkliste der Alpaca-Backtest-Skill führt „adjustment mode"
und „corporate actions" als Pflichtpunkte — der Abgleich gegen unseren Sync
förderte die fehlende Angabe zutage.

**Scope:** `adjustment` beim Bars-Request explizit setzen, per Config
umschaltbar, plus einmaliger Re-Sync der bestehenden Historie.
**Non-Scope:** Krypto-Sync (`crypto_market_data_sync.py` — Kryptowährungen kennen
keine Splits/Dividenden, `CryptoBarsRequest` hat kein `adjustment`), eigene
`corporate_action`-Ingestion (`alpaca-py` hätte dafür einen
`CorporateActionsClient` — eigenes Feature, wenn es je gebraucht wird),
Dividenden-Adjustierung (siehe §2).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein, gestärkt | Der Sync füllt den geteilten Pool, nicht persona-spezifische Daten. Korrekte Indikatoren nutzen allen Personas mit code-berechneten Signalen gleichermaßen (CHARTIST, CONTRA, CRYPTOR); keine Persona bekommt eine Quelle, die die anderen nicht haben. |
| #4 Stop-Loss | indirekt, verbessert | `compute_atr14` liefert ohne Split-Artefakt einen realistischen ATR ⇒ realistischere Stop-Distanz. Die Stop-Pflicht selbst und die Risk-Regeln bleiben unverändert. |
| Persona-Charter | nein | Kein `charter_version`-Bump: die Charter verlangen dieselben Signale wie vorher, sie werden nur korrekt berechnet. |
| Kosten | nein | Unverändert ein `StockBarsRequest` pro Sync-Lauf, keine LLM-Calls. `adjustment` ist ein Query-Parameter, kein zusätzlicher Call. |
| #6 Secrets | nein | Keine neue Credential, keine neue Env-Var. |

**Design-Entscheidungen:**

1. **`split`, nicht `all`.** `all` adjustiert zusätzlich Dividenden und verschiebt
   damit alle historischen Kursniveaus unter den tatsächlich gehandelten Kurs. Das
   ist für reine Indikatorik vertretbar, kollidiert aber mit zwei anderen Nutzern
   derselben Tabelle: `get_latest_price`/`benchmark.py` vergleichen Kursniveaus mit
   Portfoliowerten, und das Decision Journal soll den Kurs zeigen, zu dem eine
   Persona wirklich hätte handeln können (Lineage-Anspruch). Splits sind reine
   Stückelungsartefakte und müssen weg; Dividenden sind echte Kursbewegungen und
   bleiben drin.
2. **Config-Schalter statt Konstante.** `market_data.bar_adjustment` in
   `config/ingestion.yaml`, Default `split`, wenn der Key fehlt. Das ist der
   Rollback-Pfad nach §10 (Config-Flag bevorzugt): auf `raw` setzen, Container neu
   starten, nächster Sync schreibt wieder Roh-Bars. Ein unbekannter Wert wird beim
   Providerbau abgelehnt (`ValueError`), nicht still auf einen Default gebogen —
   ein Tippfehler in der Config darf keine falschen Kurse in die DB schreiben.
3. **Ein Provider-Konstruktor-Parameter, kein zweiter Codepfad.** Sowohl der
   Scheduler-Job (`run_daily_sync`) als auch der On-Demand-Chart-Backfill
   (`src/api/routes.py:_try_backfill` über `build_default_provider`) hängen an
   `AlpacaBarsProvider` — beide bekommen das Verhalten automatisch.
4. **Re-Sync statt Migration.** `sync_market_bars` upsertet auf
   `(symbol, timeframe, ts)` und überschreibt OHLCV — ein Sync mit großem
   `lookback_days` schreibt die bestehende Historie auf die adjustierte Basis um.
   Kein Schema-Change, keine Alembic-Migration. **Wichtig:** ohne diesen
   einmaligen Lauf bleibt nur das rollierende 90-Tage-Fenster adjustiert und die
   ältere Historie (Backfill vom 10.07.2026 ab 13.04.2026) behält Rohbasis — an
   der Nahtstelle stünde ein Mischbestand. Deshalb ist der Backfill in §5 Teil des
   Features, nicht optional.

## 3. Testdefinition (vor Implementierung geschrieben)

Alle in `tests/ingestion/test_market_data_sync.py`, gleiches Muster wie die
bestehenden Request-Parameter-Tests (`..._uses_iex_feed`):

1. `test_alpaca_bars_provider_requests_split_adjusted_bars` — Default-Provider
   schickt `adjustment == Adjustment.SPLIT`. Der Kern-Regressionstest.
2. `test_alpaca_bars_provider_honours_explicit_adjustment` — expliziter
   Konstruktor-Parameter (`Adjustment.RAW`) landet im Request.
3. `test_build_default_provider_reads_adjustment_from_config` — `bar_adjustment:
   raw` in der Config wirkt bis in den Request durch (Rollback-Pfad verifiziert).
4. `test_build_default_provider_defaults_to_split_without_config_key` — fehlender
   Key ⇒ `split` (bestehende Configs ohne den Key bleiben korrekt).
5. `test_build_default_provider_rejects_unknown_adjustment` — `bar_adjustment:
   nonsense` ⇒ `ValueError` mit dem Wert in der Meldung.

Bestehende Tests bleiben unverändert gültig (kein Verhalten außerhalb des
Request-Parameters geändert).

## 4. Implementierung

- `src/ingestion/market_data_sync.py`:
  - `AlpacaBarsProvider.__init__` bekommt `adjustment: Adjustment =
    Adjustment.SPLIT` und reicht es an `StockBarsRequest` durch.
  - `_resolve_adjustment(value: str | None) -> Adjustment` — Config-String →
    Enum, `None` ⇒ `SPLIT`, unbekannt ⇒ `ValueError`.
  - `build_default_provider` liest `market_data.bar_adjustment`.
- `config/ingestion.yaml`: `market_data.bar_adjustment: split` mit Begründung.

## 5. Test & Rollout

- `uv run pytest`: **922 passed, 26 deselected** (Stand 11.08.2026, inkl. der
  5 neuen Tests; gegen eine lokale Postgres-17-kompatible Instanz mit pgvector).
  `ruff check` / `ruff format --check` / `mypy src`: clean.
- **Deployment (Ralf, auf der Box):** geänderte Dateien deployen,
  `docker compose build api scheduler` + `up -d api scheduler`.
- **Einmaliger Re-Sync direkt nach dem Deploy** — nicht auf den 06:30-ET-Cron
  warten, und mit einem Fenster, das die *gesamte* bestehende Historie abdeckt
  (ältester Bar 13.04.2026, F048), sonst bleibt Mischbestand stehen:

  ```python
  # im api- oder scheduler-Container; Universum exakt wie in
  # scheduler.py::_market_data_job aufgelöst
  import datetime
  from pathlib import Path

  import yaml

  from src.db.base import get_session_factory
  from src.ingestion.market_data_sync import run_daily_sync
  from src.orchestrator.symbol_universe import (
      resolve_stock_seed_watchlist,
      resolve_symbol_universe,
  )

  config_path = Path("config/ingestion.yaml")
  config = yaml.safe_load(config_path.read_text())
  with get_session_factory()() as session:
      seed = resolve_stock_seed_watchlist(config)
      symbols = sorted(s for s in resolve_symbol_universe(session, seed) if "/" not in s)
      print(
          run_daily_sync(
              session,
              datetime.date.today(),
              config_path=config_path,
              watchlist_override=symbols,
              lookback_days=180,
          )
      )
      session.commit()
  ```

- **Deployt und gebackfillt am 15.08.2026** (Box, `api`/`scheduler` neu gebaut).
  Der Re-Sync aus dem Snippet oben lief über 375 Symbole und schrieb **46.444
  Bars**; `market_bar` wuchs von 49.079 auf 64.836 Zeilen, der älteste Bar der
  Universums-Symbole reicht jetzt bis **2026-02-17** zurück (vorher 2026-04-13).
  Damit stammt das gesamte Fenster dieser Symbole aus einem einzigen
  split-adjustierten Lauf — die Nahtstelle aus §2 Punkt 4 existiert nicht mehr.
- **Adjustment nachgewiesen** (Direktvergleich gegen die Alpaca-API, RCON,
  27.07.–04.08.2026): `raw` liefert `0,4607`, `split` liefert `92,14` für den
  27.07. — der Faktor 200 der Anpassung ist also wirklich im Request wirksam.
- **`compute_indicator_snapshot` gegen die echte DB** (15.08.2026):

  | Symbol | SMA20 | SMA50 | RSI14 | MACD-Histogramm |
  |---|---|---|---|---|
  | AAPL | 318,384 | 309,118 | 25,93 | −3,277 |
  | MSFT | 450,292 | 412,737 | 84,83 | +2,697 |
  | SPY | 756,151 | 748,890 | 75,58 | +2,189 |

- **Nebenbefund, nicht von F103 verursacht:** ein Sprung-Check über das
  Universum (größter Tages-Close-Faktor je Symbol) zeigt 22 von 376 Symbolen mit
  Faktor > 2, 5 davon > 5 (RCON 157, HAO 104, GMM 50 …). Die Blue Chips sind
  sauber (AAPL 1,08 / MSFT 1,16 / SPY 1,03 / NVDA 1,07 / TSLA 1,17). Ursache ist
  Alpacas eigene Datenlage bei Nano-Caps: bei RCON adjustiert Alpaca die Historie
  mit Faktor 200 hoch, lässt die Kurse ab dem Split-Datum aber unverändert bei
  ~0,39 stehen — die Lücke steckt in der Quelle, nicht in unserem Sync. Für
  solche Symbole sind Indikatoren wertlos. Offen als eigenes Thema: entweder ein
  Plausibilitätsfilter im Screener-Universum oder ein Ausschluss unterhalb einer
  Mindest-Marktkapitalisierung. Braucht Ralfs Entscheidung, siehe §6.
- **Rollback-Pfad:** `market_data.bar_adjustment: raw` in `config/ingestion.yaml`,
  Container neu starten, Re-Sync wie oben. Kein Schema-Change, kein Deploy nötig
  außer dem Config-Reload.

## 6. Offene Punkte

- Bars, die älter sind als das gewählte Re-Sync-Fenster, behalten Rohbasis. Mit
  `lookback_days=180` ist zum Deploy-Zeitpunkt die komplette Historie erfasst;
  bei künftigen Splits hält das tägliche 90-Tage-Fenster die relevante
  Indikator-Historie automatisch konsistent.
- Kein Alarm auf Kapitalmaßnahmen. Wenn das gewünscht ist, wäre der
  `CorporateActionsClient` von `alpaca-py` der Ansatz — eigenes Feature
  (ADR-0015, Folgearbeit).
- ~~**Nano-Caps mit kaputter Split-Historie bei Alpaca**~~ (Nebenbefund aus der
  Backfill-Verifikation, §5) → **erledigt als
  [F108](F108-indikator-plausibilitaet.md)** (15.08.2026). Ralf hat sich gegen
  die Mindest-Marktkapitalisierung und für den Plausibilitätsfilter entschieden.
  Beim Messen zeigte sich, dass „Datenfehler" gar nicht das brauchbare Kriterium
  ist — aus den Bars ist eine echte Kapitalmaßnahme nicht von einem Artefakt zu
  unterscheiden, und für die Frage „darf man über diese Closes mitteln?" ist die
  Ursache egal. F108 lässt deshalb das `technical_indicator`-Item weg, sobald die
  Reihe im Indikator-Fenster einen Niveauwechsel hat.
