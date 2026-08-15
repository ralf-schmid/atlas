# F115 — Krypto-Universum auf 10 Paare, Historie auf gemeinsamen Stand

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 5+ (Datenbasis + Charter, wirkt auf F111)
Auslöser: Ralf, nach der Ursachenanalyse zu `cryptor-proxy` (0 Trades)
Charter-Entscheidung: [ADR-0016](../adr/0016-cryptor-universum-erweiterung.md)

## 1. Zieldefinition

Zwei Dinge, die im selben Befund zusammenhängen:

1. **Krypto-Historie nachziehen.** Der F103-Backfill hatte Krypto ausgespart
   (`if "/" not in s`, weil der Stock-Provider an Krypto-Symbolen scheitert).
   Dadurch begannen die Krypto-Bars erst am 13.04., die Aktien am 17.02. — im
   gemeinsamen Backtest-Fenster fielen alle Krypto-Symbole durch den
   Warmup-Filter.
2. **Universum verbreitern.** Drei Symbole erzeugen zu wenige Signale, um eine
   Trendfolge-Strategie überhaupt bewerten zu können (ein Einstieg in 65 Tagen).

Die Charter-Seite von Punkt 2 ist in ADR-0016 entschieden und begründet; dieses
Dokument hält die Umsetzung und die Nachweise fest.

## 2. Umsetzung

| Datei | Änderung |
|---|---|
| `config/personas/cryptor.yaml` | `universe_screen` 3 → 10 Paare, `charter_version` 2 → 3 |
| `config/ingestion.yaml` | `crypto_market_data.watchlist` deckungsgleich gezogen |
| `config/backtest/strategies/cryptor-proxy.yaml` | `universe.symbols` deckungsgleich gezogen |
| `tests/personas/test_charters.py` | Charter-Version je Persona statt global „2" |
| `tests/backtest/test_spec.py` | Proxy-Universum gegen die Charter-Datei geprüft statt gegen eine zweite Liste |

Die beiden Teständerungen sind bewusst so gebaut, dass sie den nächsten Fall
abfangen: Die Charter-Versionen stehen jetzt als Map da (ein stiller Bump fällt
auf), und das Backtest-Universum wird gegen `config/personas/cryptor.yaml`
verglichen, statt die Liste ein drittes Mal zu wiederholen. Vorher wären
Charter und Proxy bei genau dieser Änderung auseinandergelaufen, ohne dass ein
Test es gemerkt hätte.

## 3. Backfills

**Krypto, 180 Tage:** `run_daily_crypto_sync(..., lookback_days=180)`,
**1.800 Bars** über 10 Symbole. Alle zehn stehen jetzt auf **180 Bars ab
2026-02-17** — demselben Startpunkt wie die Aktien nach F103.

**Aktien, 250 Tage — der Nachtrag, den ich nicht vorhergesehen hatte.** Der
Krypto-Backfill allein hat das Problem nicht gelöst, sondern **gespiegelt**:

- Krypto handelt 7 Tage/Woche, Aktien 5. Nach dem Backfill war die *längste*
  Bar-Reihe im Universum eine Krypto-Reihe (180 Bars gegen ~125).
- `_auto_start` in `src/backtest/data.py` leitet den Fensterstart aus der
  längsten Reihe ab — er rutschte damit auf den 18.04.
- Vor dem 18.04. hatten die Aktien ab 17.02. nur ~42 Handelstage, gefordert sind
  60. **Alle Aktien fielen aus dem Universum**: der Sammellauf zeigte
  10 Symbole und 675 Ausschlüsse, `chartist-proxy` und `baseline` kamen auf null
  Einstiege.

Behoben durch `run_daily_sync(..., lookback_days=250)` über 355 Aktien-Symbole,
**59.767 Bars**. Die Aktien reichen jetzt bis 2025-12-09 zurück und tragen das
gemeinsame Fenster.

**Das ist eine Datenlösung für ein strukturelles Problem** — siehe §5.

## 4. Nachweis

Sammellauf `--all --no-save`, vorher/nachher:

| | vor F115 (heute früh) | nach F115 |
|---|---|---|
| Fenster | 13.05.–14.08. (65 Tage) | **18.04.–15.08. (120 Tage)** |
| Bar-Historie | ab 2026-02-17 | **ab 2025-12-09** |
| Universum | 325 Symbole | 315 Symbole |
| baseline-sma-crossover | insufficient (10 Trades) | insufficient (8) |
| chartist-proxy | insufficient (10 Trades) | **ok — 20 Trades, Sortino 1,56, +7,74 %** |
| contra-proxy | ok (116 Trades) | ok — 87 Trades, +12,03 % |
| cryptor-proxy | **insufficient (0 Trades, leeres Universum)** | **insufficient (8 Trades, 10/6 Symbole)** |
| vulture-proxy | ok (106 Trades) | ok — 73 Trades, −5,56 % |

SPY-Referenzlinie: +9,52 %.

**cryptor-proxy ist von 0 auf 8 Einstiege gekommen, bleibt aber unter der
10-Trade-Schwelle.** Der Grund ist nicht mehr Signalarmut, sondern Kapital: der
Lauf meldet **10 Risk-Gate-Ablehnungen** (5× `insufficient_cash_no_margin`, 5×
`min_cash_pct_violated`). Bei 20 % Positionsgröße sind nach fünf Positionen die
Mittel gebunden — von 18 Signalen wurden 8 ausgeführt. Mehr Symbole helfen also
nur bis zu dieser Grenze; die nächste Stellschraube wäre `max_position_pct`, und
das ist wieder Charter.

**Nebenwirkung, positiv:** `chartist-proxy` ist durch das längere Fenster von
`insufficient_data` auf `ok` gesprungen. Das war kein Ziel dieses Features,
sondern fällt beim längeren Aktien-Backfill mit ab.

## 5. Offener Punkt: `_auto_start` ignoriert die Kalenderdichte

Der Aktien-Backfill hat den Symptomdruck genommen, nicht die Ursache. `_auto_start`
wählt den Fensterstart aus der Bar-**Anzahl** der längsten Reihe. Solange Krypto
(7 Bars/Woche) und Aktien (5) im selben Universum stehen, ist diese Reihe
strukturell eine Krypto-Reihe, und das Fenster ist für Aktien immer ~40 % zu eng
— bis die Aktien-Historie entsprechend länger ist. Heute passt es; beim nächsten
Krypto-Backfill kippt es wieder.

Sauberer wäre, den Start so zu wählen, dass ein definierter Anteil des Universums
den Warmup besteht (z. B. der Median der symbolweisen Frühest-Starts), statt sich
an einem einzelnen Extremwert zu orientieren. Das ist ein Eingriff in
`src/backtest/data.py` und gehört in den Backtest-Block (F111), nicht hierher —
deshalb hier nur notiert, nicht gebaut.

## 6. Rollback

- **Universum/Charter:** `config/personas/cryptor.yaml` auf die drei Paare und
  `charter_version: 2` zurück, die beiden anderen Listen mitziehen. Der
  `charter_version`-Bump ist der Marker, an dem sich die Saison später
  auseinanderdividieren lässt.
- **Backfills:** nicht rückgängig zu machen und auch nicht nötig — mehr Historie
  schadet nichts. Die Indikatoren im Live-Pfad rechnen unverändert auf den
  letzten 51 Bars, die aktuellen Werte ändern sich durch die Verlängerung nicht.
- Tests: 1074 passed, `ruff`/`mypy` clean.
