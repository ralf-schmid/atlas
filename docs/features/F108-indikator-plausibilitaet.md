# F108 — Plausibilitätsfilter: keine Indikatoren auf gebrochener Kursreihe

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 4/5 (Datenqualität, wirkt auf F036)
Auslöser: Ralf, nach dem Nebenbefund aus der F103-Backfill-Verifikation

## 1. Zieldefinition

Ein `technical_indicator`-Research-Item darf nicht entstehen, wenn die Kursreihe
des Symbols innerhalb des Indikator-Fensters einen **Niveauwechsel** hat. Über so
eine Reihe gemittelt sind SMA20, SMA50, Bollinger und MACD keine schwachen
Signale, sondern bedeutungslose Zahlen — sie mitteln zwei verschiedene
Preisniveaus. Eine Persona kann darauf eine These bauen, und das Decision Journal
würde diese These sauber dokumentieren, obwohl ihre Datenbasis nie existiert hat.

**Kriterium:** Overnight-Gap = `Open(t) / Close(t-1)` (bzw. der Kehrwert, je
nachdem welcher größer ist) ≥ **2,0**, irgendwo in den letzten **51 Bars** — das
ist das längste Fenster, das überhaupt ein Indikator anfasst
(`_MIN_BARS_FOR_CROSSOVER = _SMA_LONG + 1` in `src/orchestrator/indicators.py`).

**Scope:** genau diese eine Item-Quelle. **Non-Scope:** der Kurs-Sync (die Bars
werden weiter für alle Symbole geholt), die Portfolio-Bewertung, das Risk-Gate,
und alle anderen Research-Quellen.

### Warum das Kriterium nicht „Datenfehler" heißt

Der Auslöser war Alpacas kaputte Split-Historie bei Nano-Caps (F103 §6). Beim
Messen gegen die echte DB zeigte sich: **aus den Bars allein ist nicht
entscheidbar, ob ein Sprung ein Datenartefakt oder eine echte Kapitalmaßnahme
ist.** Eindeutig sind nur die Extremfälle (RCON Faktor 177, YYAI 40 — beide mit
normaler Intraday-Range am Sprungtag, also Handel auf einem neuen Niveau).
Darunter liegen Fälle wie CAPR (19,70 → 5,86) oder XHG (1,10 → 5,73), bei denen
ich es nicht sagen kann.

Für das Ziel ist die Unterscheidung aber **irrelevant**: ein SMA50 über einen
Niveauwechsel ist in beiden Fällen wertlos. Deshalb heißt das Kriterium ehrlich
„die Reihe ist gebrochen" und nicht „die Quelle hat Mist geliefert". Das ist
zugleich der Grund, warum der Filter nichts markiert, meldet oder korrigiert —
er lässt nur einen Impuls weg, den niemand interpretieren könnte.

### Warum nicht im Screener, obwohl Ralf das so gesagt hatte

Ursprüngliche Ansage war „Plausibilitätsfilter im Screener". Die Messung hat das
widerlegt und Ralf hat die Abweichung am 15.08. bestätigt: Das
`screener_result`-Item trägt ausschließlich `price` und `volume` aus dem
**Live-Snapshot** (`vulture_screener.Snapshot`) — beides korrekt gemessen, völlig
unabhängig von der Bar-Historie. Es gibt dort nichts zu filtern. Der Schaden
entsteht erst, wenn die Persona diesen korrekten Kandidaten mit dem gebrochenen
Indikator kombiniert; fällt der Indikator weg, ist der Kandidat harmlos.

Dazu kommt ein Wettbewerbs-Argument: ein Filter im VULTURE-Screener hätte rund
16 von 376 Kandidaten gekostet, und zwar genau in VULTUREs Beuteschema
(Pennystocks). Das hätte sein Spielfeld mitten in der laufenden Wertung
(Stichtag 27.07.) verändert.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate deterministisch | nein | Der Filter ist deterministischer Code und ändert keinen Risk-Parameter. Er entfernt einen Research-Impuls, keine Guardrail. |
| #10 Fairness | ja, geprüft | Der Filter sitzt in der gemeinsamen Synthese, wirkt auf den Shared Pool und damit für alle sechs Personas identisch. Keine Persona bekommt dadurch eine Quelle, die eine andere nicht hat. CHARTIST verliert relativ am meisten (Indikatoren sind sein Kerngeschäft) — aber er verliert nur Impulse, die keine Information trugen. |
| #9 Untrusted Content | nein | Rein numerisch, keine Fremdtexte. |
| #3 kein Pfad zur Order | nein | Research-Ebene. Bestehende Positionen in betroffenen Symbolen bleiben unberührt, werden weiter bewertet und können weiter verkauft werden. |
| Kosten | leicht positiv | Weniger Research-Items ⇒ minimal kürzerer Persona-Prompt. Der Gap-Check ist eine zusätzliche Query je Symbol, kein LLM-Call. |

**Der unangenehme Teil:** Der Filter nimmt Personas Impulse zu Symbolen weg, die
sie **bereits halten**. Ein gehaltenes Symbol mit gebrochener Reihe bekommt kein
`technical_indicator`-Item mehr — die Persona sieht ihre Position dann ohne
technisches Signal. Das ist bewusst so: ein falsches Verkaufssignal aus einem
Zufalls-RSI wäre schlimmer als gar keins, und alle nicht-technischen Quellen
(News, Newsletter, Screener, Musterdepot) bleiben für das Symbol erhalten. Die
Portfolio-Bewertung hängt an `market_bar`/`get_latest_price`, nicht an den
Indikatoren, und ist damit nicht betroffen.

**Selbstheilend:** Das Fenster ist rollierend. Sobald der Sprung älter als 51
Bars ist, liefert das Symbol wieder Indikatoren — ohne Eingriff. Genau deshalb
bleibt der Kurs-Sync unangetastet: würde der Filter Symbole aus dem
Sync-Universum werfen, fröre ihre Historie ein und sie kämen nie zurück.

## 3. Testdefinition (vor der Implementierung geschrieben)

In `tests/orchestrator/test_indicators.py` (Erkennung) und
`tests/orchestrator/test_research_synthesis.py` (Wirkung):

1. `test_detects_upward_overnight_gap` — Reihe mit Gap Faktor 3 nach oben ⇒ Bruch
   erkannt, mit Datum und Faktor.
2. `test_detects_downward_overnight_gap` — derselbe Gap nach unten ⇒ erkannt.
   Das Kriterium ist symmetrisch.
3. `test_gap_below_threshold_is_not_a_break` — Faktor 1,9 bei Schwelle 2,0 ⇒ kein
   Bruch. Die Grenze selbst (exakt 2,0) zählt als Bruch.
4. `test_gap_outside_the_indicator_window_is_ignored` — Gap liegt 60 Bars zurück,
   Fenster ist 51 ⇒ kein Bruch. Das ist der Selbstheilungs-Test.
5. `test_series_without_gap_is_clean` — normale Reihe ⇒ kein Bruch.
6. `test_symbol_without_bars_is_clean` — keine oder zu wenige Bars ⇒ kein Bruch,
   kein Fehler (neue Screener-Kandidaten haben noch keine Historie).
7. `test_zero_prices_do_not_raise` — `Close(t-1) = 0` ⇒ kein ZeroDivisionError,
   kein Bruch.
8. `test_broken_symbol_yields_no_technical_indicator_item` — der Kern: Symbol mit
   Bruch bekommt kein Item, ein sauberes Symbol im selben Lauf schon.
9. `test_broken_symbol_keeps_its_other_research_items` — für dasselbe Symbol
   bleibt das `screener_result`-Item bestehen. Gegenprobe zum Scope.
10. `test_filter_is_off_without_config_value` — ohne
    `technical_indicators.max_overnight_gap_factor` verhält sich alles wie vor
    F108. Das ist der Rollback-Pfad, als Test.

## 4. Umsetzung

| Datei | Änderung |
|---|---|
| `src/orchestrator/indicators.py` | `PriceLevelBreak`-Dataclass + `detect_price_level_break()` |
| `src/orchestrator/research_synthesis.py` | Filter in `_research_items_from_technical_indicators`, Schwelle aus der Config, strukturiertes Log je übersprungenem Symbol |
| `config/ingestion.yaml` | neue Sektion `technical_indicators.max_overnight_gap_factor: 2.0` |

Die Schwelle wird **nicht** in `indicators.py` hart verdrahtet und
`compute_indicator_snapshot()` bleibt unverändert: der Filter ist eine
Entscheidung der Synthese („welcher Impuls geht in den Pool"), nicht der
Berechnung. Wer die Indikatoren direkt berechnet, bekommt weiter unverfälscht,
was in der DB steht.

## 5. Test & Rollout

- `uv run pytest`: **983 passed, 26 deselected** (972 nach F107, also 11 neue —
  die 10 aus §3 plus `test_gap_exactly_at_threshold_is_a_break`, die die Grenze
  selbst festnagelt). `ruff check` / `ruff format --check` / `mypy src`: clean.
- **Smoke-Test gegen die echte DB vor der Livesetzung** (read-only, mit dem
  neuen Image in einem `run --rm`-Container, bevor `up -d` lief):

  | | |
  |---|---|
  | Universum | 378 Symbole |
  | gefiltert | **9** |
  | davon bisher mit Indikator-Item | 9 (also 9 echte Impulse weniger je Zyklus) |
  | behalten ihr Indikator-Item | 368 |

  Betroffen: RCON (177,45), TENX (7,59), XHG (5,23), CISS (3,72), OFAL (3,50),
  CAPR (3,36), GETY (2,20), TTDU (2,20), DFSC (2,09).

- **Die 9 sind weniger als die 16 aus der Vorab-Analyse — und das ist der
  Selbstheilungs-Nachweis.** Die Analyse lief über die gesamte Historie (~125
  Bars), der Filter über die 51 Bars des Indikator-Fensters. YYAI (Gap am
  18.05.) ist bereits herausgewachsen und liefert wieder Indikatoren; bei CISS
  greift jetzt ein jüngerer Sprung (3,72 statt 8,08).
- **Keine offene Position betroffen** (22 offene Positionen, Schnittmenge leer) —
  der in §2 beschriebene unangenehme Fall tritt zum Zeitpunkt des Rollouts
  faktisch nicht ein.
- **Live seit 15.08.2026**, `api` + `scheduler` neu gebaut und gestartet, `api`
  healthy. Kein Schema-Change, keine Migration, keine neue Env-Var.
- **Wirkung nachprüfen:** ab dem nächsten Zyklus im Scheduler-Log nach
  `technical indicators skipped` greppen (eine Zeile je übersprungenem Symbol
  mit Faktor und Datum), und im Decision Journal stichprobenhaft prüfen, dass zu
  RCON & Co. kein `technical_indicator`-Impuls mehr auftaucht.
- **Rollback:** `technical_indicators.max_overnight_gap_factor` in
  `config/ingestion.yaml` entfernen oder auf `null` setzen ⇒ Filter aus,
  Verhalten exakt wie vor F108 (als Test festgehalten,
  `test_filter_is_off_without_config_value`). Weil `config/` ins Image gebacken
  ist, braucht auch dieser Rollback `docker compose build api scheduler` +
  `up -d` — kein Restart allein.

## 6. Offene Punkte

- **Corporate Actions als saubere Quelle.** Der ehrliche Weg, Artefakt von echter
  Kapitalmaßnahme zu unterscheiden, wäre Alpacas `CorporateActionsClient`
  (ADR-0015, auch F103 §6). Damit ließe sich die Historie sogar korrigieren
  statt nur auszulassen. Eigenes Feature, braucht Ralfs Anforderung.
