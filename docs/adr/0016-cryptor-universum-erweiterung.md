# ADR-0016: CRYPTORs Universum von 3 auf 10 liquide USD-Paare

* Status: accepted — entschieden von Ralf am 15.08.2026
* Deciders: Ralf Schmid
* Datum: 2026-08-15
* Betrifft Invariante(n): **#10** (Fairness / Charter-Änderung mit
  `charter_version`-Bump)
* Betrifft ARCHITECTURE.md **§4.6** (CRYPTOR), **§7.8** (Slippage)
* Umsetzung: `charter_version` 2 → 3, siehe F115

## Kontext und Problemstellung

Der Backtest-Lauf vom 15.08.2026 (F111) lieferte für `cryptor-proxy` **null
Trades**. Die Ursachenanalyse ergab zwei Schichten:

1. **Warmup-Ausschluss.** Das gemeinsame Simulationsfenster wird aus der längsten
   Bar-Reihe im Universum bestimmt — seit dem F103-Backfill eine Aktie mit
   Historie ab 17.02.2026, Fensterstart also 13.05. Die Krypto-Bars beginnen erst
   am 13.04. (der F103-Backfill sparte Krypto aus, weil der Stock-Provider an
   Krypto-Symbolen scheitert), womit vor dem Fensterstart nur ~30 der geforderten
   60 Warmup-Bars lagen. Alle drei Symbole fielen aus dem Universum.
2. **Signalarmut.** Auch im Einzellauf mit eigenem Fenster (12.06.–15.08., alle
   drei Symbole drin) kam nur **ein einziger Einstieg** zustande. Ein
   SMA-20/50-Golden-Cross feuert auf drei Symbolen in zwei Monaten kaum. Selbst
   mit perfekter Datenlage bliebe der Lauf unter der 10-Trade-Schwelle und damit
   `insufficient_data`.

Punkt 1 ist ein Datenproblem und über einen Backfill lösbar. Punkt 2 ist ein
**Universumsproblem** — und es betrifft nicht nur den Backtest: CRYPTOR handelt
auch live auf diesen drei Symbolen.

**Der Auslöser für diesen ADR:** `config/personas/cryptor.yaml` ist Charter. Eine
Erweiterung des Universums ist damit keine Konfigurationspflege, sondern eine
Charter-Änderung mitten in der laufenden 8-Wochen-Wertung — CLAUDE.md verlangt
dafür `charter_version`-Bump **und** ADR.

## Entscheidungstreiber

* **ARCHITECTURE.md §4.6 sah die Breite immer schon vor:** „Universum: via Alpaca
  handelbare Krypto-Paare, Fokus Top-Liquidität (BTC, ETH, SOL + wenige weitere)."
  Die 3-Symbol-Liste war eine **Verengung** gegenüber der Architektur, kein
  bewusster Charter-Kern. Die Erweiterung stellt den vorgesehenen Zustand her.
* **§4.6 verbietet zugleich ausdrücklich:** „Keine Meme-Coin-Jagd — das
  Extremrisiko deckt VULTURE bei Aktien ab." Das ist eine harte Auswahlgrenze.
* Fairness (#10): die Änderung betrifft nur CRYPTOR, weil nur sie Krypto handelt.
  Sie verschafft ihr keinen Vorteil gegenüber den Aktien-Personas — die haben ein
  Universum von ~375 Symbolen, CRYPTOR hatte drei.
* Vergleichbarkeit: CRYPTORs Ergebnisse vor und nach dem 15.08. sind nicht mehr
  auf derselben Grundlage entstanden. Das ist der Preis und war Ralf bewusst.

## Betrachtete Optionen

* **A** — Nur Backfill, Universum unverändert (3 Symbole)
* **B** — Datenbasis verbreitern, Charter unangetastet; die breite Variante läuft
  als eigene, klar benannte Backtest-Strategie
* **C** — Charter erweitern, Datenbasis und Backtest-Proxy ziehen mit
* **D** — Charter erweitern *und* Meme-Coins aufnehmen (maximale Signalfrequenz)

## Entscheidung

Gewählt: **C**, mit einer datengetriebenen Auswahlregel.

**A** löst nur das Datenproblem; CRYPTOR bliebe mit einem Einstieg pro Quartal
sowohl live als auch im Backtest praktisch unbewertbar.

**B** war meine Empfehlung, weil sie den laufenden Wettbewerb nicht anfasst. Ralf
hat sich dagegen entschieden: ein Backtest, der eine andere Strategie testet als
die, die live läuft, beantwortet nicht die Frage, ob **CRYPTOR** taugt. Das ist
nachvollziehbar — der Erkenntniswert von B wäre begrenzt gewesen.

**D** ist durch §4.6 ausgeschlossen und wurde nicht ernsthaft erwogen.

### Auswahlregel (gemessen, nicht geschätzt)

Grundlage ist Alpacas **eigenes** Tagesvolumen über 30 Tage (Stand 15.08.2026),
nicht das globale Handelsvolumen — denn es ist die Liquidität, die ATLAS
tatsächlich zur Verfügung steht, und exakt die Größe, gegen die die
Volumen-Penalty des Slippage-Modells rechnet (`config/review.yaml`).

Aus den 36 handelbaren USD-Paaren fliegen raus:

| Ausschluss | Symbole | Grund |
|---|---|---|
| Stablecoins | USDC, USDT, USDG | kein Trend — eine Trendfolge-Regel hat darauf keinen Gegenstand |
| Meme-Coins | DOGE, SHIB, PEPE, BONK, WIF, TRUMP | ARCHITECTURE.md §4.6 ausdrücklich |
| Rohstoff-Token | PAXG (tokenisiertes Gold) | kein Krypto-Major im Sinne des Charters, trotz Rang 8 nach Volumen |

Aus dem Rest die **Top 10 nach gemessenem Volumen**:

| # | Symbol | Ø Tagesvolumen (USD) |
|---|---|---|
| 1 | BTC/USD | 85.329 |
| 2 | ETH/USD | 36.705 |
| 3 | SOL/USD | 12.353 |
| 4 | XRP/USD | 12.044 |
| 5 | AVAX/USD | 8.486 |
| 6 | AAVE/USD | 5.726 |
| 7 | UNI/USD | 4.870 |
| 8 | LINK/USD | 4.804 |
| 9 | ADA/USD | 2.420 |
| 10 | DOT/USD | 1.864 |

Der Schnitt bei 10 ist nicht magisch, aber begründet: darunter fällt das Volumen
unter ~1.400 USD/Tag, und bei einer Positionsgröße von bis zu 1.000 USD wäre eine
einzelne Order dort mehr als zwei Drittel des Tagesumsatzes — handelbar nur auf
dem Papier.

### Konsequenzen

* **Gut:** CRYPTOR bekommt ein Universum, das ihrer Charter-Beschreibung
  entspricht, und der Backtest-Proxy kann sie erstmals ernsthaft prüfen.
* **Gut:** die drei Config-Listen (Charter, Ingestion-Watchlist,
  Backtest-Universum) sind jetzt deckungsgleich und im Kommentar aneinander
  gebunden — vorher konnten sie unbemerkt auseinanderlaufen.
* **Schlecht, und das ist der ernste Punkt: CRYPTORs Orders liegen an der
  Slippage-Volumenschwelle, die neuen Symbole deutlich darüber.** Die
  1-%-Schwelle aus `config/review.yaml` misst die Ordergröße am Tagesvolumen.
  Alpacas Krypto-Bars melden dabei nur das Volumen der **eigenen** Börse — für
  BTC/USD rund 85.000 USD im 30-Tage-Mittel. Bei voller Positionsgröße (20 % von
  5.000 USD = 1.000 USD) wären das ~1,2 %; die parallel entstandene F114-Messung
  kommt bei realer Ordergröße auf 0,61 %. BTC liegt also **knapp unter bis knapp
  über** der Schwelle, je nach Ordergröße — und die neuen Symbole am unteren Ende
  der Liste (DOT: 1.864 USD Tagesvolumen) reißen sie um ein Vielfaches.

  **Das ist keine Folge dieser Entscheidung** — es galt schon für die drei alten
  Symbole —, aber die Erweiterung verschiebt den Schwerpunkt zu dünneren Werten
  und macht es dadurch relevanter. F114 hat die Krypto-Deckungsquote bewusst auf
  `1.0` gelassen (keine Hochskalierung wie bei IEX-Aktien), weil der echte
  Deckungsgrad unbekannt ist und ein geratener Faktor genau hier eine
  Live-Kennzahl auf nichts lockern würde. Das ist richtig so.

  Offen zur Entscheidung, bevor nach acht Wochen ein Gewinner gekürt wird:
  entweder eine krypto-eigene Volumenschwelle, oder eine kleinere
  `max_position_pct` für CRYPTOR, oder die bewusste Feststellung, dass Alpacas
  dünnes Krypto-Buch ein reales Handelshemmnis ist und in die Wertung gehört.
  Ich habe hier nichts entschieden — die Zahlen liegen jetzt auf dem Tisch.
* **Schlecht:** CRYPTORs Zahlen vor und nach dem 15.08.2026 sind nicht
  vergleichbar. Der `charter_version`-Bump macht das im Datenmodell sichtbar.
* **Neutral:** ~7 zusätzliche `technical_indicator`-Items je Zyklus im geteilten
  Pool, sichtbar für alle sechs Personas. Von Ralf akzeptiert; gemessen an ~1.400
  Items je Zyklus liegt das im Promillebereich.
