# F104 — Gemessener Bid/Ask-Spread im Slippage-Malus

Status: umgesetzt (Deploy + Live-Verifikation offen, siehe §5)
Datum: 2026-08-11
Phase: 5 (Feinjustierung des Malus, ARCHITECTURE.md §7.8)

## 1. Zieldefinition

`compute_slippage_malus` rechnet die Spread-Hälfte der Malus-Formel bis hierhin
mit einer **Pauschale je Assetklasse** (`config/review.yaml`: 5 bps Aktien,
15 bps Krypto). Das war am 25.07.2026 eine bewusste Entscheidung (F083 §1):
Bid/Ask-Daten lagen schlicht nicht vor, `market_bar` hat nur OHLCV-Tagesbars.
Die damals geprüfte Live-Quote-Variante wurde verworfen, weil eine Quote zum
*Review*-Zeitpunkt nicht zum Fill passt.

Damit bekommt ein illiquider Penny-Stock (VULTURE) denselben Spread-Ansatz wie
SPY — bei realen Spreads, die um eine Größenordnung auseinanderliegen. Der Malus
ist genau die Größe, die im Leaderboard die adjustierte gegen die rohe
Performance stellt (F085); eine Pauschale begünstigt strukturell die Personas,
die in engen Märkten handeln, und bestraft niemanden für tatsächlich teure
Ausführung.

**Lösung (mit Ralf entschieden, 11.08.2026):** den Spread **zum Orderzeitpunkt
messen** und an der Order persistieren. Damit fällt der Zeitversatz-Einwand von
Option C aus F083 weg — gemessen wird, was die Order wirklich vorgefunden hat,
nicht was Tage später am Markt steht. Der Review liest den gespeicherten Wert;
fehlt er, greift unverändert die Pauschale.

**Scope:** Spread-Messung im Order-Pfad (best effort), neue Spalte
`order_record.spread_bps`, Nutzung in `compute_slippage_malus`, Plausibilitäts-
Grenze, Config-Schalter.
**Non-Scope:** Änderung der Malus-Formel selbst (bleibt
`0,5 × Spread + Volumen-Penalty`), Änderung der Volumen-Penalty, rückwirkende
Neuberechnung bereits geschriebener Reviews (siehe §2), Quote-Ingestion für
Symbole ohne Order.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #2 Privilege Separation | ja, geprüft | Der Order-Pfad wird angefasst, aber nur um einen **lesenden** Marktdaten-Call erweitert. Keine neue Order-Fähigkeit, kein LLM, keine Entscheidung hängt am Ergebnis. Die Messung läuft in `try/except`, das jede Exception loggt und verwirft: eine Quote-Störung darf niemals eine Order verhindern oder verzögern-bis-Fehler. |
| #3 Keine Order ohne Decision | nein | Reihenfolge und Persistenz unverändert; `spread_bps` ist ein zusätzliches Feld auf einer Zeile, die es ohnehin gibt. |
| #1 Risk-Gate | nein | Der Malus ist Reporting, kein Gate (F083 §2). Die Messung passiert *nach* Risk- und HITL-Gate, unmittelbar vor der Broker-Order. |
| #10 Fairness | ja, geprüft | Gemessen wird für **alle** Personas identisch, aus derselben geteilten Marktdatenquelle. Kein Informationsvorteil: der Wert fließt ausschließlich in die Nachbewertung, nie in einen Prompt oder eine Entscheidung. |
| Kosten | nein | Ein Quote-Call je Order (nicht je Zyklus, nicht je Symbol des Universums), keine LLM-Kosten. |

**Bewusst in Kauf genommener Bruch in der Zeitreihe:** Der Wettbewerb läuft seit
03.08.2026. Für Orders davor gibt es keine Quote und damit weiterhin die
Pauschale; ab Deploy gilt der gemessene Wert. Der Malus ist also über die
Wettbewerbsdauer nicht mit einer einheitlichen Methode gerechnet. Das ist
hinnehmbar, weil der Schnitt **zeitlich, nicht persona-bezogen** verläuft: vor
dem Deploy sind alle sechs Personas gleich behandelt, danach ebenfalls
(Invariante #10 bleibt gewahrt). Eine rückwirkende Neuberechnung ist nicht
möglich — historische Quotes zum jeweiligen Orderzeitpunkt haben wir nicht.
Der Schnitt gehört in den Wochenreport-Kommentar, damit die Zahl lesbar bleibt.

**Design-Entscheidungen:**

1. **Messung im Order-Pfad, nicht per Snapshot-Ingestion.** Ralfs Entscheidung
   vom 11.08.2026 gegen eine eigene `market_quote_snapshot`-Tabelle: der
   Orderzeitpunkt ist der einzige Zeitpunkt, an dem der Spread die Ausführung
   tatsächlich betrifft; eine Snapshot-Kadenz träfe ihn nur zufällig und
   kostete deutlich mehr API-Calls.
2. **Spalte auf `order_record`, nicht auf `review`.** Der Wert ist eine
   Eigenschaft der Ausführung, kein Ergebnis der Bewertung; Reviews werden
   wiederholt/neu gerechnet, die Order-Zeile nicht. So bleibt der Malus auch bei
   einem Review-Rerun reproduzierbar.
3. **Plausibilitätsgrenze statt blindem Vertrauen.** Gemessene Werte ≤ 0 oder
   > `max_measured_bps` (Default 500 bps = 5 %) werden verworfen und fallen auf
   die Pauschale zurück. Gekreuzte oder extrem weite Quotes (dünner Handel,
   Auktionsphasen, Halts) sonst direkt in den Malus durchschlagen zu lassen,
   wäre ein Ausreißer-Risiko genau bei den illiquiden Titeln, um die es geht.
4. **Rollback bleibt Config.** `slippage.use_measured_spread: false` in
   `config/review.yaml` schaltet zurück auf reine Pauschalen, ohne Deploy und
   ohne Datenverlust (die Spalte wird weiter befüllt).

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/broker/test_market_data.py` (neu bzw. erweitert):

1. `test_stock_provider_computes_spread_bps_from_latest_quote` — Bid 99,90 /
   Ask 100,10 ⇒ 20 bps (Spread/Mid × 10 000).
2. `test_crypto_provider_computes_spread_bps_from_latest_quote` — gleiche
   Rechnung über den Krypto-Client.
3. `test_spread_bps_returns_none_for_unusable_quote` — Bid oder Ask 0/None ⇒
   `None` statt Division durch Null.

`tests/orchestrator/test_trading.py`:

4. `test_execute_decision_records_measured_spread` — Fake-Provider liefert
   12,5 bps ⇒ `order_record.spread_bps == Decimal("12.5")`.
5. `test_execute_decision_places_order_when_spread_measurement_fails` — Provider
   wirft ⇒ Order wird trotzdem platziert, `spread_bps` bleibt `None`. Der
   Invarianten-Test dieses Features.
6. `test_execute_decision_derives_market_from_symbol` — `BTC/USD` ⇒ Krypto-
   Provider, `AAPL` ⇒ Stock-Provider.

`tests/review/test_slippage.py`:

7. `test_uses_measured_spread_when_present` — `spread_bps=20` auf der Order ⇒
   Spread-Kosten = 0,5 × 20 bps × Ordervolumen, nicht die 5-bps-Pauschale.
8. `test_falls_back_to_config_spread_when_not_measured` — `spread_bps=None` ⇒
   unverändertes Verhalten (Regressionsschutz für alle Alt-Orders).
9. `test_ignores_implausible_measured_spread` — 5 000 bps ⇒ Pauschale.
10. `test_measured_spread_can_be_disabled_via_config` —
    `use_measured_spread: false` ⇒ Pauschale trotz vorhandener Messung.

Bestehende Slippage-Tests bleiben unverändert gültig (Alt-Orders haben
`spread_bps IS NULL` und damit exakt das bisherige Ergebnis).

## 4. Implementierung

- `src/db/models.py`: `OrderRecord.spread_bps` (`Numeric(10,4)`, nullable) +
  Alembic-Migration `f7a1c2d3e4b5` (reines `add_column`, kein Backfill).
- `src/broker/market_data.py`: Protocol `SpreadProvider` mit
  `get_quote_spread_bps(symbol) -> float | None`; beide Alpaca-Provider
  implementieren es über `StockLatestQuoteRequest` bzw.
  `CryptoLatestQuoteRequest`.
- `src/broker/registry.py`: `build_spread_provider(market)` — gleiche
  Key-Auflösung wie `build_market_data_provider`, dessen Rückgabetyp dafür auf die
  konkreten Provider-Klassen verengt wurde (beide erfüllen auch `SpreadProvider`).
  **Nachtrag 12.08.2026:** in CI zunächst rot — `src/broker` hat ein
  100-%-Branch-Coverage-Gate (eigener CI-Schritt neben der 90-%-Hauptsuite), und
  die neue Funktion war ungetestet. Nachgezogen in
  `tests/broker/test_registry.py::test_build_spread_provider_*`.
- `src/orchestrator/trading.py`: `measure_spread_bps(symbol)` (best effort,
  loggt und verwirft jede Exception) wird unmittelbar vor `place_order`
  aufgerufen; Ergebnis landet auf dem `OrderRecord`. Gilt für Entry- und
  Close-Orders.
- `src/review/slippage.py`: `_get_spread_bps(order, decision.instrument, config)`
  bevorzugt `order.spread_bps`, prüft `use_measured_spread` und
  `max_measured_bps`, sonst Pauschale wie bisher.
- `config/review.yaml`: `use_measured_spread: true`, `max_measured_bps: 500`.

## 5. Test & Rollout

- `uv run pytest`: **937 passed, 26 deselected** (Stand 11.08.2026; 922 vor
  F103/F104). Die Migration wird dabei real durchlaufen — die Test-Session fährt
  `alembic upgrade head` hoch und am Ende `downgrade base` wieder herunter, damit
  ist auch der Rückweg der Spalte verifiziert. `ruff check` /
  `ruff format --check` / `mypy src`: clean.
- **Deployment (Ralf, auf der Box):** `alembic upgrade head` (fügt nur eine
  nullable Spalte hinzu, kein Rewrite), dann `docker compose build api scheduler`
  + `up -d api scheduler`.
- **Live-Verifikation nach dem ersten Trade** (hier nachtragen): erste neue
  `order_record`-Zeile auf `spread_bps` prüfen und den Wert gegen den
  Alpaca-Dashboard-Spread des Symbols plausibilisieren; anschließend das
  zugehörige Review auf einen Malus > 0 kontrollieren.
- **Rollback-Pfad:** `slippage.use_measured_spread: false` in
  `config/review.yaml` (sofort wirksam, Spalte bleibt befüllt). Die Migration
  selbst hat ein funktionierendes `downgrade()`, muss für den Rollback aber
  nicht angefasst werden.

## 6. Offene Punkte

- Der gemessene Spread ist der **Quote zum Absendezeitpunkt**, nicht zum
  Fill-Zeitpunkt. Für die Market-Orders dieses Systems liegen die Zeitpunkte eng
  beieinander; für Stop-Fills (GTC, Tage später) wäre die Order-Quote nicht
  repräsentativ — betrifft den Malus aber nicht, weil
  `compute_review_inputs` ihn nur für die Order der Decision rechnet, nicht für
  die Stop-Ausführung.
- Fällt die Quote-Abfrage systematisch aus (Key-Problem, Wochenend-Krypto),
  rutschen die betroffenen Orders still auf die Pauschale. Ein Zähler/Alert
  darauf ist bewusst nicht Teil dieses Features; die `WARNING`-Logzeile
  (`slippage measurement failed`) ist der Einstiegspunkt, falls das auffällt.
