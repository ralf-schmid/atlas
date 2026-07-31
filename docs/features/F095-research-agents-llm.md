# F095 — Market- und News-Recherche als echte LLM-Agenten

**Status:** Implemented
**Phase:** 5 (Härtung)
**Deployed:** 2026-07-31
**Abhängigkeiten:** `src/orchestrator/research_agents.py` (neu),
`src/orchestrator/graph.py`, `src/llm/config.py`, `config/llm.yaml`
Berührt Invarianten **#2** (Privilege Separation), **#7** (Kosten-Caps),
**#9** (Untrusted Content), **#10** (Fairness).

## 1. Zieldefinition

ARCHITECTURE.md §5.1 beschreibt einen Market-Recherche- und einen
News-Recherche-Agenten, beide Haiku, beide shared. Beide existierten nur als
Einträge in `config/llm.yaml`.

Ralfs Auftrag: *„baue es so um, dass die rollen implementiert sind, wie es
dokumentiert ist."*

## 2. Kontext / Ist-Zustand (gemessen, 31.07.2026)

Der Befund, der das Feature ausgelöst hat:

```
cost_ledger, alle Zeiten:
 claude-sonnet-5       | PERSONA | 1749
 claude-haiku-4-5-groq | PERSONA |    5
```

`claude-haiku-4-5` wurde **nie** aufgerufen. Ursachen:

* `guarded_complete` wird ausschließlich aus `persona_analysis.py` gerufen.
* Nur `llm_config.roles["persona_analysis"]` wird je nachgeschlagen.
* `research_synthesis.py` sagt in seinem Docstring selbst: *„Deliberately no LLM
  calls: every `summary` is a deterministic text template"*.

Die sichtbare Folge in den Daten:

```
      agent      |      source_type      |   n   | mit_sentiment | mit_instruments
-----------------+-----------------------+-------+---------------+-----------------
 market_research | technical_indicator   | 43284 |             0 |           43284
 news_research   | edgar_filing          | 30443 |             0 |               0
 news_research   | market_news           | 27320 |             0 |               0
 news_research   | publication_article   |  6196 |             0 |               0
```

**`sentiment` ist auf allen 127.689 Items NULL**, und **alle 64.057 News-Items
haben kein Instrument-Tagging** — genau die zwei Dinge, die §5.1 der
News-Recherche zuschreibt („Extraktion, Sentiment, Instrument-Tagging").

## 3. Kritische Betrachtung (vor der Umsetzung)

### 3.1 Kosten (Invariante #7) — der bestimmende Faktor

Pro Zyklus entstehen ~1.050 News- und ~740 Market-Items. Ein LLM-Call je Item
wären bei 8 Zyklen/Tag ~14.400 Calls/Tag — gegen einen Cap von 10 USD/Tag
aussichtslos. Gemessener Ist-Verbrauch heute: ~100 Calls, ~2,85 USD/Tag.

Daraus folgen zwei Design-Zwänge: **Batching** und ein **Item-Budget je Zyklus**,
das in der Config steht, nicht im Code.

### 3.2 Untrusted Content (Invariante #9)

Der News-Agent liest Zeitschriften- und Web-Text — potenziell feindlich. Er
bekommt deshalb **keine Tools** (kann also weder Orders noch Decisions berühren,
Invariante #2), und Fremdtext erreicht ihn nur in getaggten Datenblöcken.

### 3.3 Fairness (Invariante #10)

Beide Rollen sind `shared: true` und laufen einmal je Zyklus — das Ergebnis ist
für alle sechs Personas identisch. Kein Persona-spezifischer Pfad.

### 3.4 Keine Berechnungen durch das LLM

CLAUDE.md verbietet, Finanz-Kennzahlen vom LLM ausrechnen zu lassen. Der
Market-Agent bekommt ausschließlich **bereits berechnete** Indikatoren und
benennt nur Auffälligkeiten; der System-Prompt sagt das explizit („Rechne NICHTS
aus"), und ein Test hält das fest.

## 4. Design

### 4.1 Anreicherung statt Ersetzung

`synthesize_research_items` bleibt **unverändert**. Der LLM-Pass läuft danach und
füllt nur Felder, die der deterministische Pass leer gelassen hat:

* Fällt der LLM aus oder ist er abgeschaltet, kostet das die Anreicherung —
  **nie den Research-Pool**. `persona_analysis` bekommt in jedem Fall Daten.
* Ein bereits gesetztes `instruments` (aus strukturierten Quellen) wird **nicht**
  überschrieben: das ist Ground Truth und schlägt eine Modell-Vermutung.
* Der quellenabgeleitete `summary` bleibt stehen → Lineage zur Ingestion-Zeile
  hält.

### 4.2 Die beiden Rollen

| Rolle | Aufruf-Muster | Ergebnis |
|---|---|---|
| `news_research` | gebatcht, Budget-gedeckelt | `sentiment` + `instruments` je Item |
| `market_research` | genau 1 Call je Zyklus | ein zusätzliches `market_overview`-Item mit den Auffälligkeiten |

Auswahl der News-Items: nur solche, denen der deterministische Pass etwas
schuldig geblieben ist, neueste zuerst, gedeckelt auf
`news_max_items_per_cycle`.

### 4.3 Config (`config/llm.yaml`)

```yaml
research_agents:
  enabled: true
  news_max_items_per_cycle: 200
  news_batch_size: 25
  market_enabled: true
```

`enabled: false` stellt exakt den Zustand vor F095 wieder her — das ist der
Rollback-Pfad.

### 4.4 Fehlerverhalten

`enrich_research_items` wirft **nie**. Ein Provider-Ausfall wird geloggt und als
`AgentRun(status=FAILED)` persistiert, der Zyklus läuft weiter. Begründung: ein
Pool ohne Sentiment ist besser als ein Zyklus, der vor `persona_analysis` stirbt
— dieselbe Lehre wie F047.

Eine unparsebare Antwort kostet ihren Batch, nicht den Zyklus (F073: eine leere
oder abgeschnittene Completion ist ein normaler Betriebszustand, keine Ausnahme).

## 5. Testdefinition (vor der Umsetzung festgelegt)

23 Tests in `tests/orchestrator/test_research_agents.py`, u. a.:

| Bereich | Test |
|---|---|
| Auswahl | nur News-Source-Types; bereits getaggte Items werden übersprungen; neueste zuerst + Limit; **Items ohne `published_at` lassen den Sort nicht crashen** |
| Invariante #9 | Fremdtext landet in `<untrusted_document>`-Blöcken; ein Injection-Versuch wird in einen JSON-String escaped |
| CLAUDE.md | Market-Prompt verbietet Rechnen |
| Parsing | Sentiment/Instrumente werden gesetzt und normalisiert; fenced JSON toleriert; leere/kaputte Antwort wirft nie (parametrisiert); unbekannte `ref` ignoriert; ungültiges Sentiment abgelehnt; Prosa-„Symbole" verworfen; bestehende `instruments` bleiben |
| Invariante #7 | es wird gebatcht, nicht ein Call je Item |
| Robustheit | Provider-Ausfall → `AgentRun(FAILED)`, kein Abbruch |
| Invariante #10 | `AgentRun.portfolio_id` bleibt NULL (Cycle-, nicht Portfolio-Ebene) |
| Rollback | `enabled: false` gibt 0 Calls |

Nach dem Smoke-Test ergänzt: `AgentRun` zählt jetzt Tokens mit (Test 24). Der
erste Live-Lauf schrieb `tokens_in/out = 0` auf die beiden neuen Rollen — die
Abrechnung stimmte (`cost_ledger`), aber die Agent-Trace-Ansicht liest `agent_run`
und hätte einen echten Call als kostenlos dargestellt.

**Ergebnis:** 751 passed (vorher 727), `ruff` sauber,
`mypy src/risk src/broker` sauber.

Beim Schreiben der Tests gefunden und behoben: `select_news_items` sortierte über
`published_at`, das nullable ist — `None` ist gegen `datetime` nicht ordnbar, ein
einziges undatiertes EDGAR-Filing hätte den Sort mit `TypeError` gerissen.

## 5.1 Live-Verifikation (Paper-Smoke-Test, 31.07.2026)

Ein vollständiger Zyklus, 0 Tracebacks:

```
      agent       |  status   |  usd
------------------+-----------+--------
 market_research  | SUCCEEDED | 0.0316
 news_research    | SUCCEEDED | 0.0349
 persona_analysis | SUCCEEDED | 0.0572   (6x, alle SUCCEEDED)
```

Erstmals überhaupt Haiku-Verbrauch im `cost_ledger`:

```
 claude-haiku-4-5 | SYSTEM  | 7 Calls | $0.0665
```

Wirkung auf den Research-Pool desselben Zyklus:

```
     source_type     |  n  | mit_sentiment | mit_instr
---------------------+-----+---------------+-----------
 edgar_filing        |  99 |            99 |        12
 market_news         |  50 |            50 |        31
 market_overview     |   1 |             0 |         0
```

**149 von 149 News-Items mit Sentiment** — vorher 0 von 127.689 über die gesamte
Projektlaufzeit. 43 Items bekamen zusätzlich ein Instrument-Tagging, und der
Market-Agent schrieb sein Auffälligkeiten-Item.

Kosten des Zyklus: ~0,067 USD für beide Recherche-Rollen zusammen. Hochgerechnet
auf 8 Zyklen/Tag ≈ 0,54 USD/Tag — nah an der Schätzung aus §3.1 (~0,6 USD/Tag).

## 6. Rollback

`research_agents.enabled: false` in `config/llm.yaml` + Rebuild der App-Services
(die Datei ist ins Image gebacken, nicht gemountet). Der deterministische Pfad
ist unangetastet, es geht also nichts verloren außer der Anreicherung.

## 7. Offene Punkte

1. **Kosten über mehrere Tage beobachten.** Die 200-Items-Grenze ist eine
   Schätzung (~0,6 USD/Tag). Erst der Mehrtage-Verlauf zeigt den echten Wert;
   `news_max_items_per_cycle` ist der Stellhebel.
2. **Review-Agent (F084) und Reporting-Freitext** fehlen weiterhin — nächste
   Schritte derselben Aufräumaktion.
3. **Handels-Agent bleibt deterministisch** (Ralfs Entscheidung, 31.07.2026).
   ARCHITECTURE.md §5.1 sagt dort „toolgesteuert, minimal-LLM"; der Code ist
   bewusst strenger und setzt Invariante #2/#3 direkt um. Die Doku ist an dieser
   Stelle zu korrigieren, nicht der Code.
