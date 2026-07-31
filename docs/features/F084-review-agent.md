# F084 — Review-Agent

**Status:** Implemented (31.07.2026) — Kern umgesetzt, pgvector-Lessons-Pfad
bewusst ausgeklammert (§7)
**Phase:** 5, Block 2 (Kern der Phase)
**Abhängigkeiten:** F083 (Slippage-Malus, wird hier geschrieben), F082
(Kennzahlen-Modul: nicht zwingend, aber Review nutzt ggf. Roh-Rendite-Helper).
`review`-Tabelle existiert (0 Zeilen), `ReviewVerdict`-Enum existiert
(`thesis_confirmed` / `thesis_failed` / `inconclusive`).

## 1. Zieldefinition

DoD-Satz (§8 P5): „Review-Agent verarbeitet fällige Decisions automatisch;
jede geschlossene Position hat binnen 7 Tagen ein Review mit Verdict."

Rollenmodell §5.1: 1 Instanz, Sonnet. **Code rechnet** (expected vs. actual,
Deviation, Slippage-Malus via F083); **LLM liefert nur** `verdict` +
`lessons_text` (+ Meta-Review der Recherche-Qualität als Teil der Lessons).

**Scope:**
- Neuer Agent `src/agents/review.py` + Scheduler-Job (Sonntag-Wochenlauf
  gemäß §5.2, zusätzlich täglicher Due-Sweep — siehe Fälligkeit unten)
- Fälligkeits-Query: welche Decisions brauchen ein Review
- Deterministische Vorrechnung: expected (`decision.expected_outcome` JSONB)
  vs. actual (Fill-Preise, Position geschlossen? realisierter P&L),
  `deviation`, `slippage_malus` (F083)
- LLM-Call (Sonnet, eigener LiteLLM-Key `review` × Persona für
  Kostenzuordnung): Input = Thesis + expected + vorgerechnetes actual +
  verlinkte Research-Zusammenfassungen; Output = strukturiert
  `{verdict, lessons_text}`; Eval-Fixture Pflicht
- Lessons → pgvector-Embedding, damit `research_search.py`-Retrieval sie in
  künftige Persona-Analysen einspeisen kann (Anbindung prüfen — Retrieval
  existiert, Einspeisepfad ist zu verifizieren)
- Schreibt genau eine `review`-Zeile je Decision (idempotent: existiert schon
  ein Review → skip)

**Non-Scope:**
- Kein Review für `RISK_REJECTED`/`HITL_REJECTED` (kein Marktergebnis)
- Keine Charter-Änderungen aus Lessons (das wäre `charter_version`-Thema, P7)
- Kein UI (F086 zeigt Reviews an)

### Fälligkeits-Definition (Vorschlag zur Entscheidung, Ralf)

§8 sagt nur „geschlossene Position binnen 7 Tagen". Präzisierung nötig für:

| Fall | Vorschlag |
|---|---|
| Position geschlossen (Sell/Close-Fill, F077-Pfad) | Review fällig ab Schließung, spätestens +7 Tage (harte DoD-Grenze) |
| `EXECUTED`-Buy, Position noch offen | Zwischen-Review nach 14 Tagen Haltedauer („Thesis on track?" — `inconclusive` erlaubt), danach alle 14 Tage |
| `RECORDED` `hold` | kein eigenes Review (Ketten-Rauschen, 394 Stück); Holds fließen als Kontext ins Review der zugehörigen Position ein |
| `RECORDED` `reject_idea` | kein LLM-Review (188 Stück, Kostenfresser ohne Marktergebnis); §5.2-Meta-Review stichprobenartig im Wochenlauf (max. 5/Woche) |
| Offene Positionen am Wettbewerbsende | Abschluss-Review mit Mark-to-Market als „actual" (kein Zwangsverkauf) |

## 2. Kritische Betrachtung

- **Invariante 2 (Privilege Separation):** Review-Agent bekommt **keine
  Order-Tools** und keine Schreibrechte auf `decision`/`order_record` — nur
  INSERT auf `review` + Embedding-Write. Prompt-seitig: Lessons sind Fremdtext
  für künftige Analysen → werden wie Research als getaggte Datenblöcke
  eingespeist, nie in System-Prompts (Invariante 9).
- **Invariante 9 (Untrusted Content):** Research-Zusammenfassungen im
  Review-Input sind potenziell injiziert → getaggte Datenblöcke, Output strikt
  auf `{verdict ∈ Enum, lessons_text}` validiert (Parser wie
  `persona_analysis`, inkl. F076-Fallback).
- **Invariante 10 (Fairness):** Lessons einer Persona dürfen nur in die
  Analyse **derselben** Persona zurückfließen (sonst Informationstransfer
  zwischen Personas). Retrieval-Filter auf `persona_id` ist Pflicht-Testfall.
- **Kosten (kritischster Punkt):** Sonnet-5-Ist: ø 0,0281 USD/Call, max 0,0716
  (7-Tage-Ledger). Review-Call ist eher groß (Thesis + Research-Kontext) →
  Annahme 0,05–0,08 USD/Review. Bestand: 24 EXECUTED-Decisions → Erstlauf
  ~1,20–1,90 USD einmalig (unter Tages-Headroom von ~2 USD, aber am Sonntag
  laufen ohnehin nur Krypto-Zyklen ≈ 1 USD → passt). Laufend: ~5–15
  Reviews/Woche → ~0,25–1,20 USD/Woche ≈ 0,04–0,17 USD/Tag. **Verdikt: kein
  Cap-Risiko vor dem 31.08.** Nach Intro-Preis-Ende (+50 % auf Sonnet) neu
  rechnen — gehört zur offenen Entscheidung „Cap nach Intro-Ende"
  (phase-5.md). Erstlauf über den Bestand nur nach explizitem Go von Ralf,
  gedrosselt (max. N Reviews/Lauf, Config).
- **Doppelte Cap-Durchsetzung:** Review-Key bekommt eigenes LiteLLM-Budget;
  `cost_ledger`-Scope wie gehabt. Review zählt gegen das 1-USD-Persona-Cap →
  bei Cap-Stopp werden Reviews aufgeschoben (nächster Lauf), nie verworfen.
- **Idempotenz/Crash:** Job kann jederzeit sterben → Fälligkeits-Query ist
  zustandsfrei („Decision ohne Review und fällig"), Re-Run erzeugt keine
  Duplikate (Unique-Semantik auf `decision_id` prüfen — ggf. Migration:
  Unique-Constraint auf `review.decision_id`).
- **Betrieb:** eigener Scheduler-Job im bestehenden APScheduler (kein neuer
  Container); Fehlerpfad wie `_run_cycle_job` (Alert nach 2 Fails).

## 3. Testdefinition (vor Umsetzung)

1. Fälligkeits-Query: Fixtures für alle 5 Fälle der Tabelle oben → genau die
   erwarteten Decisions gelten als fällig
2. Vorrechnung: bekannte Fills/Preise → deterministisch korrekte
   `expected`/`actual`/`deviation`-JSONs (kein LLM im Test)
3. Idempotenz: zweifacher Lauf → genau 1 Review je Decision
4. LLM-Parser: Eval-Fixture (fixer Input → Output-Struktur validiert;
   ungültiges Verdict → Fehler, kein Silent-Default)
5. Fairness: Retrieval-Test — Lessons von Persona A erscheinen nie im
   Kontext von Persona B
6. Cap-Verhalten: Cap erschöpft → Review verschoben, kein Verlust, Log
7. Paper-Smoke-Test: 1 echte geschlossene Position (existiert seit F077)
   end-to-end reviewen, Review-Zeile + Kosten im Ledger nachweisen

## 4.–6. Implementierung / Test & Verifikation / Rollback

Bei Umsetzung. Rollback-Pfad (geplant): Scheduler-Job per Config-Flag
(`review.enabled: false`) deaktivierbar; bereits geschriebene Reviews bleiben
(reine Daten, kein Schaden).

---

# Umsetzung (31.07.2026)

## 4. Implementierung

`src/review/agent.py` (nicht `src/agents/review.py` wie oben geplant — `src/review/`
existiert bereits mit `slippage.py`, ein zweites Verzeichnis für eine Datei wäre
Selbstzweck gewesen).

* `find_due_decisions` — zustandsfrei („EXECUTED, gefüllt, kein Review"), gedrosselt
* `compute_review_inputs` — **Code rechnet**: expected/actual/deviation/slippage_malus
  aus `expected_outcome`, `order_record`, `position_snapshot` + F083
* `build_review_messages` / `parse_review_output` — **LLM urteilt nur**
* `review_decision` — idempotent, eine `review`-Zeile
* `run_review_sweep` — der Job; wirft nie
* Scheduler-Job `review-sweep`, täglich 17:30 ET
* Migration `a1b2c3d4e5f6`: Unique-Index `uq_review_decision_id`
* Config `review:` in `config/llm.yaml` (`enabled`, `max_reviews_per_run`,
  `intermediate_after_days`)

### Abweichungen von der Planung oben — mit Begründung

1. **Kein wiederkehrendes 14-Tage-Zwischen-Review.** §1 forderte „danach alle 14
   Tage", §1 forderte gleichzeitig „genau eine `review`-Zeile je Decision
   (idempotent)". Beides zusammen ist mit einem Unique-Constraint unmöglich. Gewählt:
   **ein Review je Decision**. Die Lernschleife bleibt vollständig, weil die
   schließende Sell/Close-Decision ihr *eigenes* Review bekommt — die offene
   Buy-Position bekommt ihres nach 14 Tagen Haltedauer.
2. **Täglicher Sweep statt Sonntag-Wochenlauf.** Die DoD lautet „binnen 7 Tagen";
   ein Wochenlauf träfe das nur mit einem exakt 7-Tage-engen Fenster, der
   Tageslauf mit Reserve.
3. **Kein Bestandslauf.** §2 verlangt dafür Ralfs ausdrückliches Go — es lief genau
   **ein** Review als Smoke-Test. 16 weitere sind fällig.

## 5. Test & Verifikation

24 Tests in `tests/review/test_review_agent.py` entlang §3; Gesamtsuite **776
passed** (vorher 751), `ruff` und `mypy` sauber.

### Paper-Smoke-Test (§3.7), live auf `atlas-ugreen`

§3.7 setzte „1 echte geschlossene Position (existiert seit F077)" voraus — die gibt
es aktuell **nicht**: der Bestand sind 28 gefüllte BUYs, keine gefüllte
Sell/Close-Decision. Getestet wurde daher am Zwischen-Review einer offenen Position.

```
persona        | VULTURE
instrument     | ALDX  (BUY)
verdict        | THESIS_FAILED
deviation      | -0.2000
slippage_malus | 0.0141
expected       | {"conviction": 0.4, "entry_price": 2.29, "stop_loss_price": 1.7175}
actual         | {"fill_price": 2.16, "last_price": 1.8319, "position_open": true,
                  "pnl_unrealized": -8.53, "fees": 0.0}
lessons        | "Der Kurs fiel von 2.16 auf 1.83 (-15%) ... Die Recherche-Basis
                  bestand nur aus reinen Indikatorwerten ohne fundamentalen
                  Kontext oder Katalysator ..."
```

`deviation` gegengerechnet: (1.8319 − 2.29) / 2.29 = −0.2000 ✓ — gemessen gegen die
**erwartete** Entry-Price der These, nicht gegen den Fill. Kosten: **0,0056 USD**,
also rund ein Zehntel der §2-Schätzung (0,05–0,08). Der Bestandslauf über die
restlichen 16 kostet damit ~0,09 USD statt 1,20–1,90.

### Beim Smoke-Test gefunden und behoben

`find_due_decisions` prüfte die Mengengrenze **nach** dem Anhängen — `limit=0`
lieferte deshalb genau eine Decision statt keiner und hat ein echtes Review
gekostet. Grenzprüfung an den Schleifenanfang gezogen, Regressionstest ergänzt,
live gegengeprüft (`limit=0` → `reviewed=0`).

## 6. Rollback

`review.enabled: false` in `config/llm.yaml` + Rebuild (Config ist ins Image
gebacken). Geschriebene Reviews bleiben — reine Daten. Die Migration ist
rückwärts-lauffähig (`downgrade` löscht nur den Index).

## 7. Ausgeklammert — mit Begründung

**Der pgvector-Lessons-Pfad.** §1 fordert „Lessons → pgvector-Embedding, damit
`research_search.py`-Retrieval sie in künftige Persona-Analysen einspeisen kann
(Anbindung prüfen)". Geprüft: **es existiert keinerlei Embedding-Infrastruktur** —
keine `vector`-Spalte in der DB, kein bge-m3, kein Embedding-Code, und
`research_search.py` kennt weder Embeddings noch einen `persona_id`-Filter.

Das ist ein eigenes Feature (lokales Embedding-Modell, Vektor-Spalte, Migration,
Retrieval, plus der in §2 geforderte Fairness-Filter auf `persona_id` als
Pflicht-Testfall) und nicht der Review-Agent. **Folge:** Lessons werden heute
persistiert, fließen aber noch in keine Persona-Analyse zurück — die Lernschleife
ist geschrieben, aber noch nicht geschlossen.

**Meta-Review für `reject_idea`** (§5.2, max. 5/Woche stichprobenartig) — bewusst
nicht mitgebaut, eigener Zuschnitt.

