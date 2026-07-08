# F036 — Technischer-Indikator-Research-Items

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

CHARTISTs erster Live-Zyklus: *"Der gesamte Research-Pool besteht ausschließlich
aus [...] ohne jegliche code-berechneten Indikatorwerte (kein SMA-Crossover,
kein RSI, kein MACD, keine Bollinger-Werte, keine Breakout-Level)."* Zurecht —
eine Code-Prüfung ergab: **es gibt im gesamten Repo keine einzige
Indikator-Implementierung**, nur Charter-Text-Erwähnungen. CHARTISTs komplettes
Signal-Set (ARCHITECTURE.md §4.4) und ein Teil von CONTRAs (RSI < 30) hängen
vollständig von dieser fehlenden Stufe ab. `research_synthesis.py` (F017)
schloss `market_bar` bewusst aus dem Research-Pool aus — mit dem Kommentar
"Basis-Marktdaten für spätere technische-Indikator-Berechnung". Diese "spätere"
Stufe wird hier gebaut.

**Scope:** SMA(20/50, mit Crossover-Erkennung), RSI(14), MACD(12/26/9),
Bollinger-Bänder(20, 2σ) — reines Python über bereits ingestierte
`market_bar`-Zeilen (F008/F035), als 6. Quelle in
`research_synthesis.py::synthesize_research_items`, für den per F035 neu
verfügbaren dynamischen Symbol-Universum. **Non-Scope:** Breakout-Level
(brauchen eine Definition, welche Hochs/Tiefs als "Ausbruchsniveau" gelten —
nicht Teil dieses Features, siehe Design-Entscheidungen), Backtesting/
Signalqualitäts-Bewertung.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Alle 5 Indikatoren sind reine Code-Berechnung (`src/orchestrator/indicators.py`, kein LLM-Call) — die Persona bekommt fertige Zahlen, keine Rohdaten zum Selbstrechnen. |
| #10 Fairness / Shared Research Pool | ja | Ein gemeinsamer Symbol-Universum-Helper (`resolve_symbol_universe`, F035), eine Berechnung pro Symbol/Zyklus, im selben `research_item`-Pool wie jede andere Quelle — keine Persona bekommt eine exklusive Vorberechnung. |
| #9 Untrusted Content | nein | Reine Zahlen aus eigenen Marktdaten, kein Fremdtext. |

**Design-Entscheidungen:**
- **Ungefenstert, nicht über `synced_at` wie die anderen 5 Quellen:** ein
  Indikatorwert ist keine neu eintreffende Rohtatsache, sondern eine
  Ableitung über bereits vorhandene `market_bar`-Zeilen. "SMA20 weiterhin
  unter SMA50" ist beim zweiten Auftreten kein Rauschen wie ein wiederholter
  EDGAR-Eintrag, sondern ein legitimes, fortlaufendes Signal — deshalb wird
  `_research_items_from_technical_indicators` jeden Zyklus frisch für den
  aktuellen Symbol-Universum berechnet, nicht gefenstert.
- **Reines Python statt pandas-ta:** ARCHITECTURE.md §3.5.3 nennt "pandas/
  pandas-ta" als Option, ist aber nicht bindend. `market_pricing.py::compute_atr14`
  macht bereits exakt das (Hand-Implementierung, kein numpy/pandas irgendwo im
  Repo) — dieselbe Handschrift wird hier fortgeführt statt eine erste schwere
  Abhängigkeit einzuführen.
- **RSI: vereinfachte (nicht Wilder-geglättete) 14-Perioden-Berechnung** über
  genau die letzten 15 Closes (einfacher Mittelwert von Gewinnen/Verlusten
  statt rekursiver Wilder-Glättung über die gesamte Preishistorie) — bewusste
  Vereinfachung, per Hand verifiziert (siehe Testdefinition), nicht gegen
  `pandas-ta`s Wilder-RSI abgeglichen (andere Formel, erwartungsgemäß andere
  Werte).
- **MACD/Bollinger gegen `pandas-ta` kreuzvalidiert** (ephemer via
  `uv run --with pandas-ta`, keine neue Projekt-Abhängigkeit) — dabei fiel auf,
  dass Bollinger die **Stichproben-Standardabweichung** (N-1) nutzt, nicht die
  Populations-Standardabweichung (N) — TradingView-/pandas-ta-Konvention,
  entsprechend implementiert.
- **`compute_macd` liest bewusst nur ein festes Fenster** (`_MIN_BARS_FOR_MACD`
  = 45 Bars), nicht die komplette verfügbare Historie — deterministisches,
  gleichbleibendes Ergebnis unabhängig davon, wie viel `market_bar`-Historie
  über die Zeit anwächst.
- **Jedes Feld in `IndicatorSnapshot` ist einzeln optional:** ein Symbol mit 20
  Bars bekommt SMA20/Bollinger, aber noch kein MACD/Crossover — graceful
  Teilverfügbarkeit statt Alles-oder-Nichts, analog zu `compute_atr14`s
  bestehendem `None`-Contract.
- **Keine Charter-Änderung nötig:** CHARTISTs/CONTRAs Charter-Text beschreibt
  die Signale bereits generisch ("code-berechnete Indikatoren") und verweist
  nicht auf `source_type`-Strings — kein `charter_version`-Bump erforderlich.

**Kosten:** keine LLM-Calls, keine neue Abhängigkeit. **Fairness:** ein
gemeinsamer Berechnungspfad für alle Personas.

## 3. Testdefinition

`tests/orchestrator/test_indicators.py` (13 Tests):
1. SMA20/SMA50 stimmen exakt mit einer `pandas-ta`-Referenzberechnung überein
   (60-Bar-Synthetik-Serie).
2. Bollinger (Mitte/Ober-/Unterband) stimmt mit `pandas-ta` überein
   (Stichproben-Stddev).
3. MACD (Linie/Signal/Histogramm) stimmt mit einer unabhängig geschriebenen
   Referenzimplementierung überein (gleiches 45-Bar-Fenster wie die echte
   Funktion nutzt).
4. RSI: von Hand durchgerechnetes Beispiel (10 Gewinne/4 Verluste à 1 Punkt →
   RSI = 500/7), plus Randfälle (nur Gewinne → 100, nur Verluste → 0).
5. Crossover: konstruierte Golden-Cross-/Death-Cross-Serien, neutraler Fall
   (kein frischer Cross) und zu wenig Bars → `None`.
6. Jede Funktion liefert `None` bei zu wenig Bars (Contract-Parität zu
   `compute_atr14`).

`tests/orchestrator/test_research_synthesis.py` (3 neue Tests):
1. Ein Symbol aus der statischen Watchlist mit genug Bars erzeugt genau ein
   `technical_indicator`-Research-Item mit korrektem `source_ref`/
   `instruments`/`published_at`.
2. Ohne `market_bar`-Daten wird kein Indikator-Item erzeugt (kein Crash, kein
   leeres Item).
3. Zwei aufeinanderfolgende Zyklen erzeugen beide je ein Indikator-Item
   (Beleg für "ungefenstert").

## 4. Implementierung

- `src/orchestrator/indicators.py` (neu): `compute_sma`, `compute_rsi14`,
  `compute_macd`, `compute_bollinger`, `detect_sma_crossover`,
  `compute_indicator_snapshot`.
- `src/orchestrator/research_synthesis.py`: 6. Quelle
  `_research_items_from_technical_indicators` + Formatierungs-/Raw-Helper;
  `synthesize_research_items` lädt jetzt `config/ingestion.yaml`s
  `market_data.watchlist` und ruft `resolve_symbol_universe` (F035) auf.
- Kein Alembic-Migrations-Bedarf (kein Schema-Change).

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 408 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Deployment: rsync + `docker compose build api scheduler` + `up -d`.
- Verifikation nach Deploy: nächster echter Zyklus zeigt `technical_indicator`-
  Research-Items im Pool (per Persona-Detailseite/F034 sichtbar) — CHARTIST
  sollte darauf erstmals reagieren können.
- **Rollback-Pfad:** die neue Zeile in `synthesize_research_items`s `items`-
  Liste entfernen — ein Zeilen-Revert, kein Schema-/Config-Rollback nötig.
