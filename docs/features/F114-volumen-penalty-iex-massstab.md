# F114 — Volumen-Penalty auf den IEX-Maßstab korrigieren

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 5 (Wettbewerbskennzahl, wirkt auf F083/F085/F089/F113/F111)
Auslöser: Ralfs Auftrag nach dem IEX-Befund aus [F111](F111-backtest-modul.md) §9.2

## 1. Zieldefinition

Die Volumen-Penalty des Slippage-Malus soll gegen eine Schätzung des
**konsolidierten** Tagesvolumens rechnen, nicht gegen den IEX-Ausschnitt.

ARCHITECTURE.md §7.8 definiert die Penalty als Aufschlag „bei Ordergröße > 1 %
des Tagesvolumens". Gemeint ist das Marktvolumen. Gerechnet wird bisher gegen
`market_bar.volume × market_bar.close`, und `market_bar.volume` enthält nur den
IEX-Anteil: `market_data_sync.py` holt Bars mit `feed=DataFeed.IEX`, weil der
Alpaca-Paper-Key kein SIP-Entitlement hat. Gemessen am 15.08.2026 meldet AAPL
1.870.038 Stück gegen real ~50 Mio., META 746k, JPM 237k.

Die Penalty schlägt dadurch **zu früh** zu: der Nenner ist um Faktor ~25–50 zu
klein, also erscheint jede Order entsprechend größer relativ zum Volumen.

**Scope:** ein Deckungsgrad-Faktor je Assetklasse, angewandt an genau einer
Stelle, geteilt von Live-Pfad und Backtest.
**Non-Scope:** die Malus-Formel (F083/F104), der Spread-Anteil, der Review-Takt,
und die Beschaffung echter Volumendaten (SIP-Abo).

## 2. Kritische Betrachtung — der Faktor ist eine Schätzung, keine Messung

**Der wichtigste Punkt dieses Features:** In ATLAS existiert **keine Quelle für
konsolidiertes Volumen**, gegen die sich der Faktor kalibrieren ließe.

Geprüft am 15.08.2026:
- `market_bar` — IEX, das ist ja das Problem.
- `screener_result` (Alpaca-Snapshots, `vulture_screener.py`) — der Faktor
  gegenüber `market_bar` schwankt über zwölf Symbole zwischen **0,88 und 3,87**
  (MSTU 2,24, HTZ 3,87, DAMD 0,89, TSLG 0,88). Das ist kein systematischer
  Deckungsunterschied, sondern ein anderer Erfassungszeitpunkt derselben
  IEX-Quelle. Als Kalibrierung unbrauchbar.
- `market_mover` — enthält für Large Caps keine Zeilen.

Der Wert 0,035 für Aktien stammt daher aus **externem Wissen** (IEX-Marktanteil
am US-Handel, grob 2–4 %), gestützt nur durch den Plausibilitätsvergleich oben
(AAPL 1,87 Mio. gemeldet gegen ~50 Mio. real ⇒ ~3,7 %). Er steht deshalb
ausdrücklich als benannter Config-Parameter in `config/review.yaml` und nicht als
Konstante im Code, und dieser Absatz ist Teil des Features.

**Krypto bekommt bewusst 1,0, also keine Korrektur.** Der Grund ist ein anderer
als bei Aktien: Alpacas Krypto-Bars melden das Volumen der *eigenen* Handelsplatz,
nicht den Weltmarkt — BTC/USD kam am 14.08.2026 auf ein Tagesvolumen von rund
1 BTC (100.584 USD). Der Deckungsgrad ist damit unbekannt und mit Sicherheit
nicht 3,5 %. Ein geratener Faktor würde die Penalty für die einzige Assetklasse
lockern, bei der sie überhaupt in Reichweite ist (BTC-Order vom 15.08.: 0,61 %
gegen die 1-%-Schwelle). 1,0 hält den Status quo und ist die konservative
Richtung: die Kennzahl schönt nichts.

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Der Faktor wirkt auf alle Personas mit derselben Formel. Er entlastet tendenziell, wer in dünnen Werten handelt (VULTURE) — genau dort war die Verzerrung am größten. |
| #1 Risk-Gate | nein | Kein Risk-Parameter, keine Order-Entscheidung. |
| #7 Kosten-Caps | nein | Reine Arithmetik, kein LLM. |
| Wertung mitten in der Saison | **nein, nachweisbar** | Siehe §3. |

## 3. Effekt auf die laufende Saison: nachweislich null

Vor der Umsetzung gemessen, über **alle** gefüllten Orders der Saison
(`order_value / (volume × close)`, absteigend):

| Instrument | Order USD | IEX-$-Volumen | Anteil |
|---|---:|---:|---:|
| BTC/USD | 616,89 | 100.584 | **0,6133 %** |
| ATS | 276,41 | 491.653 | 0,0562 % |
| AMPH | 222,66 | 569.318 | 0,0391 % |
| LUNG | 54,72 | 142.663 | 0,0384 % |

Die Schwelle liegt bei 1 %. **Keine einzige Order der Saison erreicht sie**, die
Penalty ist also derzeit durchgehend 0 und jeder Malus besteht ausschließlich aus
dem Spread-Anteil. Die Korrektur vergrößert den Nenner, macht die Penalty also
noch seltener — sie kann per Konstruktion keinen Bestandswert ändern.

Das ist der Grund, warum diese Änderung mitten in der Saison unbedenklich ist:
sie repariert einen **latenten** Fehler, der erst greift, wenn eine Persona
später einmal eine relativ große Position in einem dünnen Wert eingeht. Der
Nachweis „vorher = nachher" ist Teil der Verifikation (§5).

## 4. Testdefinition (vor der Implementierung geschrieben)

In `tests/review/test_slippage.py`:

1. `test_volume_coverage_scales_the_penalty_denominator` — dieselbe Order, einmal
   mit `coverage=1.0` und einmal mit `0.035`: die Penalty sinkt entsprechend.
2. `test_penalty_below_threshold_stays_zero_after_correction` — eine Order, die
   schon vorher unter der Schwelle lag, bleibt bei 0 (kein Vorzeichenfehler).
3. `test_coverage_of_one_reproduces_the_old_behaviour` — Neutralwert 1,0 liefert
   exakt die alten Zahlen. Das ist der Rollback-Pfad.
4. `test_crypto_uses_its_own_coverage` — ein BTC-Symbol zieht den Krypto-Wert,
   kein Aktien-Symbol zieht ihn.
5. `test_missing_coverage_config_defaults_to_uncorrected` — fehlt der Block in
   `config/review.yaml`, wird nicht korrigiert (1,0). Ein fehlender Parameter
   darf eine Wettbewerbskennzahl nicht still verschieben.
6. `test_coverage_zero_or_negative_is_ignored` — ein unsinniger Wert (0) führt
   nicht zu Division durch null, sondern zu „keine Korrektur" plus Warnung.

In `tests/backtest/test_engine.py`:

7. `test_backtest_and_live_slippage_agree` — Anti-Drift: die Backtest-Engine und
   `compute_slippage_malus` müssen für dieselbe Order denselben Malus liefern,
   inklusive Coverage. Beide Pfade rufen dieselbe Hilfsfunktion; ohne diesen Test
   könnten sie auseinanderlaufen.

## 5. Verifikation

**Tests:** 1089 passed, 26 deselected. `ruff`, `ruff format`, `mypy src` (98
Dateien) sauber. Neu: die sieben Tests aus §4, dazu drei aus dem unten
beschriebenen Fund.

**Laufende Saison — dreimal gemessen, dreimal unverändert.** Vor der Änderung,
nach dem F114-Deploy und nach dem Folge-Deploy liefert `/api/leaderboard`
identische Werte:

| Persona | Malus USD | adjustierte Rendite |
|---|---:|---:|
| CONTRA | 0,5904 | 0,018302 |
| CHARTIST | 0,6343 | 0,005873 |
| VULTURE | 0,0271 | 0,005877 |
| HYPE | 0,2634 | 0,000731 |

Das ist der in §3 vorhergesagte Nulleffekt, nicht ein glücklicher Zufall: keine
Order der Saison erreicht die 1-%-Schwelle, und die Korrektur vergrößert den
Nenner.

**Backtest — hier wirkt die Änderung.** A/B auf identischem Data-Fingerprint
(`96c78e6711aa6900`, 53.875 Bars) und identischen Specs, einziger Unterschied
`volume_coverage.equities`:

| Strategie | A: 1,0 (vorher) | B: 0,035 (F114) |
|---|---|---|
| baseline-sma-crossover | −0,66 %, Slippage 1,50 | unverändert |
| chartist-proxy | +7,53 %, Slippage 4,69 | unverändert |
| **contra-proxy** | **−14,17 %**, Slippage 20,27, 63 Einstiege | **+10,15 %**, Slippage 18,79, 78 Einstiege |
| cryptor-proxy | −4,61 %, Slippage 78,87 | unverändert (Krypto-Coverage 1,0) |
| vulture-proxy | −5,73 %, Slippage 5,43 | unverändert |

Nur CONTRA ist betroffen — als einzige Aktien-Strategie kauft sie stark
abgestürzte und damit oft dünn gehandelte Werte, deren gemeldetes IEX-Volumen die
1-%-Schwelle reißt. Der Unterschied ist groß, weil die Penalty Cash verbraucht und
damit über die Pfadabhängigkeit auch die Folge-Einstiege verschiebt (63 → 78).
Fachlich ist B die richtige Seite: A hat Market-Impact bepreist, als wäre jede
Order rund 29-mal größer im Verhältnis zum Markt, als sie war.

### 5.1 Zwei Fehler, die erst diese Verifikation gezeigt hat

**(a) Vier Krypto-Paare wurden als Aktien bepreist.** ADR-0016 hat CRYPTORs
Universum von drei auf zehn Paare erweitert, `slippage.crypto_symbols` in
`config/review.yaml` blieb bei der alten Liste: **AVAX, AAVE, UNI und LINK**
fielen auf `equities` und bekamen 5 statt 15 bps Spread — seit F114 zusätzlich den
Aktien-Deckungsgrad auf ein Börsenvolumen, für das er nicht gilt. Bestandsfehler,
durch F114 verstärkt. Behoben; der Test
`test_every_cryptor_pair_is_classified_as_crypto` hält Charter und Slippage-Config
ab jetzt zusammen. Live folgenlos, weil CRYPTOR bisher nicht gehandelt hat.

**(b) Die Aktien-Proxys handelten Krypto** — ein Fehler in F111, nicht in F114.
Eine Spec ohne `universe.symbols` sieht *alle* Symbole in `market_bar`, seit
ADR-0016 also auch zehn Krypto-Paare. `contra-proxy` hat davon fünf gekauft
(AAVE, ADA, AVAX, DOT, SOL — 22 Trades), obwohl CONTRA laut ARCHITECTURE.md §4.5
US Mid/Large Caps handelt. Behoben über ein neues Pflichtfeld
`universe.asset_class` (`equities` | `crypto`) in allen fünf Specs; die Zuordnung
hängt an der Paar-Notation `BASE/QUOTE`, nicht an der Substring-Liste des
Spread-Modells, damit ein Eintrag dort nicht Universen verschiebt. Zwei Tests
sichern das ab.

Diese beiden Funde sind der Grund, warum die A/B-Tabelle oben erst im dritten
Anlauf belastbar war: die ersten beiden Vergleiche hatten je einen der Fehler nur
auf einer Seite und zeigten dadurch Sprünge, die nichts mit F114 zu tun hatten
(CONTRA schien zwischenzeitlich von 35 auf 87 Einstiege zu springen). Erst mit
beiden Fixes auf beiden Seiten misst der Vergleich wirklich nur den
Coverage-Faktor.

## 6. Rollback

`volume_coverage.equities: 1.0` in `config/review.yaml` — das reproduziert exakt
das alte Verhalten (Test 3). Config ist ins Image gebacken, ein Rollback braucht
also `docker compose build api scheduler telegram-bot` + `up -d`, keine
Migration und keinen Codeeingriff.
