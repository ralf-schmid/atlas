# F111 — Deterministisches Backtest-Modul im Review-Zweig

Status: **umgesetzt** (Entscheidungen §5 geklärt am 15.08.2026)
Datum der Beauftragung: 2026-08-15 (Ralf)
Phase: 5+ (Erweiterung — ARCHITECTURE.md §8 kennt Backtesting in keiner Phase)
Grundlage: [ADR-0015](../adr/0015-alpaca-agent-research-tooling.md), dort als
„geparkt" geführt und am 15.08.2026 mit dem ADR-Accept freigegeben

## 1. Auftrag und Herkunft

ADR-0015 hat die Alpaca-Backtest-Skill bewertet und drei Wege abgelehnt: die
Skill im Persona-Zyklus (Option A), den MCP-Server (B) und die CLI (C). Der Grund
war nie „Backtesting ist schlecht", sondern **wo** es stattfinden sollte. Wörtlich
aus dem ADR:

> Falls Backtesting je gewünscht wird, gehört es als **deterministisches
> Code-Modul in den Review-Zweig (P5+)**, nicht in den Persona-Pfad — sonst
> entstehen Kosten- und Fairness-Asymmetrien.

Genau das ist jetzt gebaut.

**Zweck aus Projektsicht:** ATLAS erkennt heute ausschließlich über den laufenden
Wettbewerb, ob eine Persona-Strategie taugt — acht Wochen, ~40 Handelstage, was
laut §4.7 selbst zu wenig ist, um Können von Zufall zu trennen. Ein Backtest im
Review-Zweig liefert eine **zweite, unabhängige Erkenntnisquelle**: hätte die
Regelmenge einer Persona über einen längeren historischen Zeitraum getragen? Das
Ergebnis ist ein Diagnose-Artefakt für Ralf und für die Meta-Review — **kein
Eingabewert für Handelsentscheidungen**.

## 2. Nicht verhandelbare Leitplanken

Diese Punkte sind keine Designvorschläge, sondern Bedingungen. Bei Konflikt:
nachfragen, nicht aufweichen.

1. **Kein LLM im Rechenweg.** Returns, Drawdown, Sortino, Fills, Slippage — alles
   Code. CLAUDE.md verbietet ausdrücklich, Finanz-Kennzahlen vom LLM „ausrechnen"
   zu lassen. Ein LLM darf höchstens ein fertiges Ergebnis *kommentieren*, so wie
   der Review-Agent ein fertig berechnetes Ergebnis beurteilt.
2. **Kein Zugriff aus dem Persona-Pfad** (Invariante #2 und #10). Keine Persona
   darf einen Backtest anstoßen oder sein Ergebnis als Research-Item sehen —
   sonst hat die eine Persona einen Vorteil, den die andere nicht hat, und die
   Kosten je Zyklus werden unvergleichbar. Das Modul läuft im Review-Zweig oder
   on demand, nie in `persona_analysis`.
3. **Keine Order-Fähigkeit.** Das Modul liest historische Daten und schreibt
   Ergebnisse. Es fasst `BrokerAdapter` nicht an.
4. **Keine neuen Credentials, kein neues Deployment-Artefakt.** Datenbasis ist
   `market_bar` in der eigenen DB (siehe §3). Kein CLI-Binary, kein MCP-Server,
   keine Go-Toolchain — das ist die ausdrückliche Absage aus ADR-0015.
5. **Reproduzierbarkeit ist Teil des Features, nicht Kür.** Ein Backtest, dessen
   Zahlen sich beim zweiten Lauf ändern, ist wertlos. Dazu §4.
6. **Kosten-Caps gelten unverändert.** Falls doch ein LLM-Kommentar dazukommt,
   läuft er über `guarded_complete` und landet im `cost_ledger`.

**Umsetzungsnachweis zu jeder Leitplanke** steht in §9 (Invarianten-Tests) —
Punkt 1–3 sind als automatische Tests verdrahtet, nicht nur als Vorsatz.

## 3. Ist-Stand — was wiederverwendet wurde

| Baustein | Ort | Nutzung im Backtest |
|---|---|---|
| Tages-Bars | Tabelle `market_bar` | einzige Datenquelle; **split-adjustiert seit F103**, Historie ab 2026-02-17 |
| Kennzahlen | `src/metrics/performance.py` | `sortino_ratio`, `max_drawdown`, `simple_return`, `daily_returns`, `adjusted_return` — unverändert übernommen |
| Wettbewerbs-Score | `src/metrics/competition_score.py` | `score_personas` über die Backtest-Strategien; Thesen-Qualität und Zuverlässigkeit existieren im Backtest nicht und fallen über die vorhandene Logik automatisch heraus (Gewichte werden umverteilt) |
| Slippage-Modell | `src/review/slippage.py` + `config/review.yaml` | dieselbe Formel (0,5 × Spread + Volumen-Penalty), dieselben Parameter |
| Indikatoren | `src/orchestrator/indicators.py` | `_rsi_from_closes` / `_macd_from_closes` direkt importiert — identische Mathematik ist hier Korrektheitsbedingung, nicht Bequemlichkeit |
| Persona-Regeln | `config/personas/*.yaml` | Risk-Parameter, nicht dupliziert, sondern per `persona:`-Verweis geladen |
| Risk-Gate | `src/risk/gate.py` | `evaluate_decision` wird für **jeden** simulierten Kauf aufgerufen |

**Gemessene Datenlage am 15.08.2026** (produktive DB auf der UGREEN):
64.836 Tagesbars, 656 Symbole, 2026-02-17 bis 2026-08-15 (~125 Handelstage).
371 Symbole haben ≥120 Bars, 281 nur 40–89 (später ins Universum gerutscht).
Nach 60 Bars Warmup bleiben ~65 simulierbare Handelstage — knapp über der
Mindestschwelle aus §5.4. Das ist kein Rechenfehler, sondern der ehrliche Stand;
das Modul weist ihn in jedem Lauf aus.

## 4. Artefakt-Kontrakt

Aus ADR-0015 übernommen, 1:1 als Spalten der Tabelle `backtest_run`:

| Kontrakt-Punkt | Umsetzung |
|---|---|
| `strategy_spec` | JSONB, die geladene Spec als Daten (nicht als Prosa) |
| `config` | JSONB: Zeitraum, Universumsgröße, Startkapital, Schwellen, Slippage-Parameter |
| Data-Fingerprint | JSONB: SHA-256 über alle Bars des Fensters, Zeilenzahl, Symbolzahl, erster/letzter Bar-Zeitstempel |
| Run-Lineage | `parent_run_id` (letzter Lauf derselben Spec) + `lineage` JSONB mit dem Feld-Diff gegenüber diesem Vorlauf |
| Pflicht-Disclaimer | `DISCLAIMER` in jedem Artefakt und in jeder Report-Ausgabe, nicht abschaltbar |

## 5. Getroffene Entscheidungen (15.08.2026, Ralf)

1. **Testgegenstand: Charter-Proxy je Persona + Regel-Baseline.** Eine
   spec-getriebene Engine; je Persona eine deterministische, in Config
   beschriebene *Näherung* der Charter-Regeln. Ehrlich möglich nur dort, wo das
   Signal in `market_bar` steckt: **CHARTIST, CONTRA, VULTURE, CRYPTOR**.
   **HYPE** (Zeitschriften-Tipps) und **GUARDIAN** (Fundamentaldaten, Fair Value)
   haben historisch keine Datenbasis und werden explizit als *nicht backtestbar*
   ausgewiesen, statt mit einer erfundenen Ersatzregel geschönt zu werden.
   Dazu eine neutrale Regel-Baseline (`baseline-sma-crossover`) und die
   SPY-Buy-&-Hold-**Referenzlinie** (siehe §6.4).
2. **Trigger: Modul-Entrypoint von Hand.** `python -m src.backtest.run …`.
   Kein Scheduler-Job, kein Telegram-Kommando, kein neues Deployment-Artefakt.
   Begründung: die Datenbasis wächst pro Woche um 5 Bars; ein Wochenlauf
   produzierte fast dieselbe Zahl neu.
3. **Ablage: Tabelle `backtest_run` (Alembic) + Markdown auf stdout.**
   Keine UI in v1. Datei-Artefakte wären beim nächsten Container-Rebuild weg
   (der Vorfall vom 10.07.2026), die DB ist gemountet.
4. **Aussagekraft: harte Schwelle.** Unter 60 simulierten Handelstagen oder
   unter 10 Trades bekommt der Lauf den Status `insufficient_data`: das Artefakt
   entsteht, aber **ohne** Sortino und **ohne** §4.7-Score. Dazu Pflicht-Caveats
   in jedem Lauf (§6.6).
5. **LLM-Kommentar: nein in v1.** Das Zahlenwerk ist das Artefakt. Ein Kommentar
   kostet je Lauf und bringt einen zusätzlichen Fehlerpfad (F110). Nachrüsten
   ist billig, weil das Review-Muster steht.

## 6. Entwurf

### 6.1 Module

```
src/backtest/
├── spec.py       StrategySpec/Rule/Condition, Laden + Validierung aus Config
├── data.py       Bar-Fenster laden, Fingerprint, Datenqualitäts-Gate (F108)
├── signals.py    Indikatorwerte je Handelstag über ein rollendes Fenster
├── engine.py     die Simulation (Fill-Modell, Stops, Risk-Gate, Slippage)
├── artifact.py   Ergebnis-Zusammenbau, Caveats, Schwellen, Persistenz
├── report.py     Markdown-Rendering
└── run.py        CLI-Entrypoint (python -m src.backtest.run)
config/backtest/
├── engine.yaml               Startkapital, Schwellen, Warmup, Datenqualität
└── strategies/*.yaml         eine Datei je Strategie
```

### 6.2 Spec-Sprache (bewusst klein)

Eine Bedingung ist `{signal, op, value}`. Einstieg = **alle** Bedingungen wahr,
Ausstieg = **irgendeine** wahr (Stop-Loss immer zusätzlich). Signale:
`close`, `dollar_volume`, `sma20`, `sma50`, `rsi14`, `macd_histogram`,
`sma_crossover`, `drawdown_20d`, `close_vs_sma20`, `return_5d`, `return_20d`,
`atr14_pct`. Operatoren: `lt|lte|gt|gte|eq|ne`.

Unbekanntes Signal oder unbekannter Operator → Fehler **beim Laden**, nicht
mitten im Lauf.

Die Spec verweist per `persona:` auf die Risk-Parameter (keine Duplikation) und
deklariert ihr Universum explizit. Enthält der `universe_screen` der Persona
Schlüssel, die die Spec nicht abbildet (z. B. VULTUREs `market_cap_max` — die
Marktkapitalisierung liegt nicht in `market_bar`), erzeugt der Loader dafür
automatisch einen Caveat. Damit fällt Drift zwischen Charter und Proxy auf,
statt still zu bleiben.

### 6.3 Fill-Modell (geldnah, deshalb konservativ und explizit)

- Signale werden aus Bars **bis einschließlich Tag t−1** berechnet.
- Ein- und Ausstiege füllen zum **Open von Tag t**. Damit ist Look-ahead
  konstruktiv ausgeschlossen, nicht nur „beabsichtigt".
- Reihenfolge an Tag t: **Stops zuerst** (sie liegen seit gestern als GTC beim
  Broker), dann regelbasierte Ausstiege, dann Einstiege.
- Stop-Fill: zum Stop-Preis, wenn `low ≤ stop`; bei Eröffnungs-Gap unter den
  Stop zum **Open** (schlechterer Preis, nie geschönt).
- Slippage nach der F083-Formel bei **jedem** Fill, Kauf wie Verkauf, mit den
  Flat-Sätzen aus `config/review.yaml` (historische Quotes existieren nicht —
  `use_measured_spread` greift hier prinzipbedingt nicht).
- Positionsgröße: `max_position_pct × Equity`, abgerundet auf ganze Stücke;
  `qty < 1` → kein Trade.
- Stop-Preis nach der Persona-Policy: `fixed` → `entry × (1 − max_loss_pct)`;
  `atr` (CHARTIST) → `entry × (1 − max(atr_mult × ATR14/entry, min_loss_pct))`.
- Mehrere Kandidaten am selben Tag werden **alphabetisch** abgearbeitet, bis
  `max_trades_per_day` oder das Kapital greift. Eine echte Persona wählt nach
  Überzeugung; das ist der ehrlichste neutrale Ersatz und steht als Caveat drin.

### 6.4 SPY-Referenzlinie statt Buy-&-Hold-Strategie

Ein Buy-&-Hold-SPY *als simuliertes Portfolio* wäre irreführend: das Risk-Gate
deckelt jede Einzelposition auf `max_position_pct_ceiling` (0,25), das „100 %
SPY"-Ergebnis käme also nie zustande. Deshalb erscheint SPY — genau wie im
Live-Leaderboard (F081) — als **reine Preis-Referenzlinie**: Rendite der
Kursreihe über dasselbe Fenster, ohne Portfolio, ohne Risk-Gate, ohne Score,
klar so beschriftet.

### 6.5 Kennzahlen und Score

Equity-Kurve = Tages-Mark-to-Market auf Schlusskurse. Daraus über die
**bestehenden** Funktionen: `simple_return`, `daily_returns`, `sortino_ratio`,
`max_drawdown`, `adjusted_return` (Rendite nach Slippage-Summe).

Der §4.7-Score kommt aus `score_personas`. Thesen-Qualität und operative
Zuverlässigkeit gibt es im Backtest nicht (keine Reviews, keine `agent_run`s);
die vorhandene Logik lässt beide Kriterien fallen und verteilt die Gewichte auf
Sortino (40→57 %), Rendite nach Kosten (25→36 %) und Drawdown (15→21 %) um.
Weil die Normalisierung feldrelativ ist, hängt der Score davon ab, **welche
Strategien im selben Lauf stehen** — das ist ein Pflicht-Caveat.

### 6.6 Pflicht-Caveats in jedem Lauf

1. Survivorship Bias: das Universum stammt aus dem **heutigen** Screener.
2. Charter-Proxy ≠ Charter: die Persona entscheidet live per LLM-Urteil.
3. Feldrelativer Score (§6.5).
4. Alphabetische Kandidatenreihenfolge (§6.3).
5. Flat-Spread statt gemessener Quotes.
6. Dynamisch: ausgeschlossene Symbole (Preisniveau-Bruch F108, zu wenig Bars),
   nicht abbildbare Screen-Kriterien, `insufficient_data`.

Plus der nicht abschaltbare Disclaimer, dass ein Backtest keine Aussage über
die Zukunft ist.

## 7. Kritische Betrachtung

- **Invarianten:** #1 (Risk-Gate deterministisch) wird nicht berührt, sondern
  benutzt — der Backtest ruft dieselbe Funktion wie der Live-Pfad. #2/#10
  (Privilege Separation, Fairness) sind per Test verdrahtet (§9). #3/#4
  (Decision/Stop-Pflicht) betreffen echte Orders; der Backtest erzeugt keine.
- **Kosten:** null LLM-Kosten. Laufzeit ist reine CPU auf der Box.
- **Fairness:** Das Modul liest nur `market_bar` und Config; es schreibt
  ausschließlich `backtest_run`. Keine Persona kann das Ergebnis sehen.
- **Größtes inhaltliches Risiko:** Der Proxy könnte für die Charter gehalten
  werden. Gegenmittel: Caveat #2, die Namensgebung (`*-proxy`) und die
  Weigerung, HYPE/GUARDIAN überhaupt zu simulieren.

## 8. Testdefinition (vor der Implementierung festgelegt)

`tests/backtest/`, plus DB-Tests im vorhandenen Postgres-Muster.

**Signale** (`test_signals.py`)
1. Rollende SMA/RSI/MACD/Crossover-Werte stimmen am letzten Tag exakt mit
   `src/orchestrator/indicators.py` überein (Anti-Drift zum Live-Pfad).
2. `drawdown_20d`, `return_5d/20d`, `close_vs_sma20` gegen von Hand gerechnete
   Referenzwerte.
3. Zu kurze Reihe → `None`, kein Absturz.

**Daten** (`test_data.py`)
4. Fingerprint ist deterministisch und ändert sich, wenn ein Bar sich ändert.
5. `find_price_level_breaks` liefert dasselbe Urteil wie die DB-gebundene
   `detect_price_level_break` auf derselben Reihe (Anti-Drift zu F108).
6. Symbole unter der Warmup-Grenze fallen mit Begründung aus dem Universum.

**Engine** (`test_engine.py`) — Referenzwerte von Hand, nicht gegen sich selbst
7. Einzelsymbol-Szenario: Einstieg Tag t, Fill zum Open t+1, Ausstieg auf Signal;
   Endkapital von Hand nachgerechnet.
8. **Kein Look-ahead:** Ändern der Bars *nach* dem Entscheidungstag verändert die
   bis dahin getroffenen Fills nicht.
9. Stop-Loss greift bei `low ≤ stop` und füllt zum Stop; Gap-Down füllt zum Open.
10. Risk-Gate wirkt wirklich: `max_position_pct` deckelt die Größe,
    `max_trades_per_day` deckelt die Einstiege, `min_cash_pct` (GUARDIAN-Profil,
    20 %) wird eingehalten, Cash wird nie negativ (kein Margin).
11. Circuit Breaker: nach >15 % Drawdown kein neuer Kauf mehr.
12. Slippage wird bei Kauf **und** Verkauf abgezogen, Betrag = F083-Formel.
13. Determinismus: zwei Läufe auf identischen Daten ⇒ identisches Artefakt
    (ohne `id`/`created_at`).

**Artefakt/Schwellen** (`test_artifact.py`)
14. < 60 Handelstage ⇒ `insufficient_data`, kein Sortino, kein Score.
15. < 10 Trades ⇒ dasselbe.
16. Pflicht-Caveats und Disclaimer sind immer enthalten.
17. Nicht abbildbare Screen-Kriterien landen namentlich in den Caveats.

**Spec** (`test_spec.py`)
18. Alle ausgelieferten Strategie-Dateien laden und validieren.
19. Unbekanntes Signal/Operator ⇒ Fehler beim Laden.
20. HYPE und GUARDIAN haben keine Spec; die CLI nennt sie mit Begründung.

**Score** (`test_score.py`)
21. §4.7-Score über Backtest-Strategien zählt genau Sortino/Rendite/Drawdown und
    verteilt die Gewichte korrekt um.

**Persistenz** (`test_persistence.py`, DB)
22. Migration `upgrade`/`downgrade` läuft.
23. Speichern schreibt alle Kontraktfelder; ein zweiter Lauf verlinkt
    `parent_run_id` und protokolliert das Feld-Diff.

**Invarianten** (`test_isolation.py`)
24. Kein Modul unter `src/orchestrator`, `src/agents`, `src/personas` importiert
    `src.backtest` (Leitplanke 2).
25. `src/backtest` importiert weder `src.broker` noch einen LLM-Client
    (Leitplanken 1 und 3).

## 9. Ergebnis des Testdurchlaufs und Verifikation

**Automatische Tests:** 60 neue Tests in `tests/backtest/`, alle 25 Punkte aus §8
abgedeckt. Volle Suite mit `DATABASE_URL`: **1074 passed**, ruff und
mypy (inkl. `src/db` strict) sauber.

**Drei Fehler, die erst der Lauf gegen echte Daten gezeigt hat:**

1. **Leeres Universum (blockierend).** Der automatische Fensterstart indexierte in
   die *Vereinigung* aller Bar-Daten. Krypto handelt am Wochenende, Aktien nicht —
   der 61. Kalendereintrag war für eine Aktie erst ihr ~43. Handelstag, also
   scheiterten **alle 656 Symbole** am 60-Bar-Warmup und der Lauf lieferte ein
   leeres Universum. Der Start kommt jetzt aus der *längsten* Reihe.
   Regressionstest: `test_auto_start_is_not_confused_by_weekend_bars`.
2. **Wochenend-Verwässerung.** Die Equity-Kurve bekam auch an Tagen einen Punkt, an
   denen das eigene Universum gar nicht handelte — Null-Renditen, die direkt in den
   Sortino-Nenner liefen. Der Kalender kommt jetzt aus den teilnehmenden Symbolen.
   Test: `test_trading_days_come_from_participating_symbols_only`.
3. **MACD wich vom Live-Pfad ab.** Der Backtest rechnete über die volle Historie,
   `compute_macd` über ein 45-Bar-Fenster: Histogramm 2,02 statt 1,60 auf derselben
   Reihe. Genau dafür ist der Anti-Drift-Test da (§8 Test 1); der Backtest nutzt
   jetzt dasselbe Fenster.

**Lauf vom 15.08.2026** (Produktivdaten, `--all --no-save`, Fenster 2026-05-13 bis
2026-08-14, 65 Handelstage, 325 Symbole, 331 wegen Datenqualität ausgeschlossen):

| Strategie | Status | Rendite netto | Sortino | Max DD | Einstiege |
|---|---|---:|---:|---:|---:|
| contra-proxy | ok | +25,28 % | 4,30 | 15,48 % | 58 |
| vulture-proxy | ok | −10,29 % | −2,51 | 16,27 % | 53 |
| chartist-proxy | insufficient_data | −0,07 % | — | 0,73 % | 5 |
| baseline-sma-crossover | insufficient_data | −0,07 % | — | 0,73 % | 5 |
| cryptor-proxy | insufficient_data | — | — | — | 0 |

SPY-Referenzlinie im selben Fenster: +4,58 %.

**Reproduzierbarkeit verifiziert:** derselbe Lauf zweimal ⇒ identischer Fingerprint,
identische Zahlen, `lineage.changed == {}`. Eine einzelne veränderte Bar ⇒ neuer
Fingerprint, und das Lineage benennt genau diese Änderung (Regel und Config
unverändert).

### 9.1 Befunde für Ralf — wichtiger als die Renditezahlen

- **CHARTIST hat im Backtest praktisch kein Universum.** Nur **3 von 325** Symbolen
  erfüllen seinen Charter-Screen (Preis ≥ 10 USD *und* ≥ 1 Mio. Stück Tagesvolumen).
  Von 212 Golden Crosses im Fenster überleben **6** den Liquiditätsfilter. Deshalb
  sind `chartist-proxy` und die Baseline zahlengleich: dieselben 6 Signale, bei
  allen war MACD > 0, kein Stop wurde ausgelöst. Kein Bug — aber der Backtest kann
  über CHARTIST nichts aussagen. Das ist zugleich ein Hinweis auf die
  *Datenabdeckung* des Wettbewerbs: `market_bar` ist screener-getrieben und
  dominiert von Werten unter 10 USD (195 von 325) bzw. zu dünnen (124).
- **CONTRAs +25,28 % sind mit Vorsicht zu lesen.** Genau diese Konstellation —
  Mean Reversion auf ein Universum, das aus dem *heutigen* Screener stammt — ist
  der Lehrbuchfall für Survivorship Bias: gekauft werden Werte nach 15 % Rückgang,
  und im Universum stehen nur die, die es bis heute gegeben hat. Der Caveat steht
  im Artefakt, aber die Zahl gehört nicht ohne ihn zitiert.
- **CRYPTOR braucht einen eigenen Lauf.** BTC/ETH/SOL werden erst seit 13.04.2026
  ingestiert und handeln täglich; im gemeinsamen Lauf (Fenster von den Aktien
  bestimmt) haben sie 30 der nötigen 60 Warmup-Bars. Einzeln
  (`--strategy cryptor-proxy`) ergibt sich ein eigenes Fenster 2026-06-12 bis
  2026-08-15 — dort 1 Einstieg, also weiterhin `insufficient_data`. Das Artefakt
  sagt das seit dem Fix ausdrücklich, statt eine Null auszuweisen, die wie ein
  Ergebnis aussieht.
- **Erledigt:** `src/backtest/run.py` liest die Slippage-Config seit dem Merge von
  F113 über das öffentliche `load_slippage_config` statt über `_load_config`.

## 10. Betrieb, Rollback, Livesetzung

**Aufruf** (lokal oder im Container):

```
python -m src.backtest.run --list
python -m src.backtest.run --all --from 2026-05-13 --to 2026-08-15
python -m src.backtest.run --strategy chartist-proxy --no-save
```

`--no-save` rechnet ohne DB-Schreibzugriff. Ohne `--from/--to` nimmt der Lauf
das maximal mögliche Fenster aus den vorhandenen Bars.

**Rollback:** Das Modul hat keinen Scheduler-Job und keinen API-Endpoint — es
läuft nur, wenn jemand es aufruft. Ein Rollback ist daher „nicht aufrufen";
die Tabelle kann per `alembic downgrade` entfernt werden. Kein Config-Flag
nötig, weil nichts automatisch startet.

**Deploy:** `rsync` auf die Box, `sudo docker compose build api` + `up -d`,
danach `alembic upgrade head` (Migration `d7e8f9a0b1c2`). Die Migration muss
laufen, **bevor** ein Lauf mit `--save` startet. `config/` ist ins Image gebacken,
eine reine Spec-Änderung braucht also trotzdem einen Rebuild.

**Stand 15.08.2026: noch nicht produktiv deployt.** Die Verifikation gegen die
echten Daten lief über einen Wegwerf-Container mit Bind-Mount
(`docker compose run --rm --no-deps -v .../src:/app/src ... api uv run --no-sync
python -m src.backtest.run …`), also ohne Rebuild und ohne Schema-Änderung an der
Produktions-DB. Grund: zum selben Zeitpunkt lag F113 unfertig im Working Tree, und
ein Image-Rebuild hätte diesen Zwischenstand mitgebacken. Reihenfolge beim
späteren Deploy beachten — erst `build`, dann `alembic upgrade head`: eine
migrierte DB mit einem Image ohne diese Revision lässt den nächsten
`alembic upgrade` auflaufen.

## 11. Was dieses Feature ausdrücklich nicht ist

- Kein Weg, doch noch die Alpaca-CLI, den MCP-Server oder die Skill einzuführen
  (ADR-0015, Optionen A–C bleiben abgelehnt).
- Kein Eingriff in den laufenden Wettbewerb. Der Backtest ändert keine Charter,
  keine Risk-Parameter und keine Decision. Wenn er zeigt, dass eine Persona-Regel
  schlecht ist, ist das eine Erkenntnis für Ralf — eine Charter-Änderung wäre ein
  eigener Vorgang mit `charter_version`-Bump und ADR.
- Kein Ersatz für den Wettbewerb als Erkenntnisweg. ADR-0015 nennt ihn
  ausdrücklich „den einzigen Erkenntnisweg, so ist das Projekt angelegt" — F111
  stellt eine zweite Quelle daneben, nicht davor.
