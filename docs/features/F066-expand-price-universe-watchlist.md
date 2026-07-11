# F066 — Preis-Universum erweitert: CHARTIST bekommt mehr als AAPL

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

Live-Rückmeldung: *"Im gesamten Datenpool erfüllt nur AAPL das
Universumskriterium Preis > 10 $."* Bestätigt (siehe auch F048): die
technische-Indikator-Pipeline (F036) ist symbol-agnostisch und funktioniert
korrekt — das Problem ist ausschließlich die Datenbasis. `market_data.watchlist`
(`config/ingestion.yaml`) enthielt seit P3 nur 3 Seed-Symbole
(AAPL/MSFT/SPY, siehe F008), und `resolve_symbol_universe` (F035) ergänzt
zwar offene Positionen + VULTURE-Screener-Kandidaten — letztere sind aber per
Charter/Config hart auf `price < 5 $` gefiltert (`vulture_screener.max_price`,
config/ingestion.yaml), können also strukturell nie CHARTISTs `price > 10 $`
erfüllen. Effektiv blieb nur AAPL (MSFT/SPY hatten zwar Preisdaten, aber
wohl keine frischen Indikator-Items im geprüften Zyklusfenster, F047s
30-Item-Deckel über alle Quellen hinweg).

**Scope:** `market_data.watchlist` von 3 auf einen diversifizierten Korb
bekannter, liquider US-Large-Caps/ETFs erweitern. **Non-Scope:** ein
dynamischer Fundamental-/Liquiditäts-Screener (siehe F037s Präzedenzfall:
für reine Preis-/Volumendaten wäre das zwar technisch machbar, aber ein
zweiter Screener auf derselben `screener_result`-Tabelle würde VULTUREs
sub-5$-Kandidatenliste semantisch verfälschen — außerhalb des Scopes hier;
eine dedizierte zweite Screener-Tabelle wäre ein eigenes Feature).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein, gestärkt | Ein gemeinsamer Watchlist-Seed, ein gemeinsamer Sync-/Berechnungspfad (F036) — alle Personas (nicht nur CHARTIST) sehen die zusätzlichen Indikator-Items im Pool. |
| Persona-Charter unverändert | ja, geprüft | Kein `charter_version`-Bump — CHARTISTs Charter verlangte "> 10 $, > 1 Mio. Volumen" immer schon (F036/F048-Lehre: das Problem war Datenverfügbarkeit, keine zu strenge Regel). |
| Kosten | ja, geprüft | Ein `StockBarsRequest` für jetzt 182 statt 92 Symbole (Watchlist + offene Positionen + Screener) × 90 Tage bleibt ein einziger HTTP-Call (Alpaca batcht serverseitig, siehe F048) — kein Kostenfaktor (keine LLM-Calls). Live gemessen: 11.219 Bars in einem Lauf, keine erkennbare Rate-Limit-Gefahr. |
| Keine stillen Annahmen bei Geld-Themen | ja, beachtet | Kandidatenliste ist keine Order-/Risiko-Regel, sondern reine Datenverfügbarkeit — "Preis > 10 $" bleibt unverändert Prompt-Kriterium der Persona (nicht code-enforced, siehe F036/F048), diese Änderung liefert nur mehr valide Kandidaten dafür. |

**Design-Entscheidungen:**
- **Statische, handverlesene Liste statt dynamischem Screener** — konsistent
  mit F037s Präzedenzfall für aktienfinder. Für Preis/Volumen (anders als
  Fundamentaldaten) wäre ein echter Screener zwar kostenlos über Alpacas
  Asset-Verzeichnis möglich (wie `vulture_screener.py`), aber Wiederverwendung
  derselben `screener_result`-Tabelle mit umgekehrtem Preisfilter (> statt <)
  würde VULTUREs eigene, semantisch anders gemeinte Kandidatenliste
  verfälschen. Eine zweite, dedizierte Tabelle wäre sauberer, aber ein
  eigener Scope — hier zunächst der pragmatische, sofort wirksame Fix.
- **16 statt 3 Symbole, sektorübergreifend** (Tech: AAPL/MSFT/GOOGL/AMZN/NVDA/
  META, Finanzen: JPM, Konsum: HD/DIS/KO, Energie: XOM, Gesundheit: JNJ,
  Auto: TSLA, breite ETFs: SPY/QQQ/IWM) — bewusst nicht auf einen Sektor
  konzentriert, damit CHARTISTs SMA-Crossover-/RSI-/MACD-Signale über
  unterschiedliche Marktregime hinweg differenzieren können, statt zufällig
  mit einem einzelnen Sektor-Beta zu korrelieren.
- **Live gegen Alpacas Snapshot-Endpunkt verifiziert, nicht angenommen** —
  jedes der 16 Symbole vor Aufnahme gegen den echten Preis geprüft (siehe
  §5), keine Symbole "vom Namen her" für liquide/teuer gehalten.
- **Dokumentierter Vorbehalt: IEX-only-Feed.** Der Alpaca-Marktdaten-Key hat
  kein SIP-Entitlement (`market_data_sync.py`, F035-Fund). IEX bildet nur
  einen Teil des konsolidierten US-Handelsvolumens ab — bekannte
  Blue-Chips wie MSFT/JPM/HD zeigen dadurch in der DB ein niedrigeres
  Volumen, als ihr tatsächliches Marktvolumen ist. Gleicher Vorbehalt wie
  bei `vulture_screener.min_volume` (bereits im Code als "Datenqualitäts-,
  kein Verbotsfilter" dokumentiert) — der Preisfilter ist davon nicht
  betroffen (Preis ist unabhängig vom Feed-Anteil korrekt) und war das
  eigentlich blockierende Kriterium.

**Kosten:** kein LLM-Call, kein neuer Anbieter. **Fairness:** unverändert,
gemeinsamer Pfad für alle Personas.

## 3. Testdefinition

Kein neuer Test nötig — die generische Mechanik
("ein Watchlist-Symbol mit genug Bars erzeugt ein `technical_indicator`-Item")
ist bereits durch `test_technical_indicator_item_emitted_for_seed_watchlist_symbol_with_enough_bars`
(AAPL) und die F064-Ergänzung (BTC/USD) abgedeckt; eine reine Config-Erweiterung
um weitere Symbole prüft keine neue Logik, nur neue Daten (siehe stattdessen
die Live-Verifikation in §5, analog zu F048).

## 4. Implementierung

- `config/ingestion.yaml`: `market_data.watchlist` von `[AAPL, MSFT, SPY]` auf
  16 Symbole erweitert (siehe Liste oben).
- Kein Code-, kein Schema-Change.

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'`: 538 passed (unverändert, reine
  Config-Änderung). `ruff`/`mypy`: nicht relevant (kein Code geändert).
- Live-Preis-/Volumen-Check **vor** Aufnahme (Alpaca-Snapshot-Endpunkt, echte
  Paper-Marktdaten): alle 16 Kandidaten mit Preis $83–$755 bestätigt, weit
  über der 10-$-Schwelle.
- Deployment: rsync `config/ingestion.yaml` + `docker compose build api
  scheduler` + `up -d` (Config ist ins Image gebacken, kein Volume-Mount —
  Rebuild nötig).
- **Live verifiziert** (echter `run_daily_sync` gegen die erweiterte
  `resolve_symbol_universe`, echte Box-DB):
  - **11.219 Bars synct** über 182 Symbole (16 Watchlist + offene Positionen
    + VULTURE-Screener-Kandidaten).
  - Alle 16 Watchlist-Symbole mit aktuellem Schlusskurs $83,49 (KO) bis
    $754,94 (SPY) — jedes einzelne über der 10-$-Schwelle, gegenüber vorher
    nur AAPL.
  - `compute_indicator_snapshot` bestätigt: **alle 16/16 Symbole** haben
    inzwischen genug Historie für SMA20 (und damit RSI14/MACD/Bollinger) —
    CHARTIST hat jetzt eine echte, diversifizierte Entscheidungsbasis statt
    eines einzelnen Symbols.
- **Rollback-Pfad:** `market_data.watchlist` in `config/ingestion.yaml` auf
  die ursprünglichen 3 Symbole zurücksetzen + Rebuild/Redeploy — reiner
  Config-Revert, kein Schema-/Code-Change. Bereits gesyncte `market_bar`-Zeilen
  für die zusätzlichen Symbole bleiben harmlos liegen.
