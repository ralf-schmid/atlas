# F047 — Research-Pool: Fenster-Resilienz + faire Quellen-Auswahl im Prompt

Status: umgesetzt
Datum: 2026-07-09
Phase: 5

## 1. Zieldefinition

Ralf, nach mehreren Live-Zyklen: *"alle 6 Agenten bekommen keine geeigneten
Kaufsignale. Das muss geändert werden."* Live-Diagnose (Box-DB) fand zwei
konkrete, unabhängige Pipeline-Bugs — keine zu strengen Kriterien, keine
Charter-Frage:

1. Der Anthropic-Kreditausfall (siehe F046-Deployment-Log) ließ mehrere Zyklen
   `research_synthesis` fertig durchlaufen (Research-Items wurden erzeugt),
   aber `persona_analysis` scheiterte komplett — 0 Decisions. Cycle
   `6155260e` (echter C1, 13:00 UTC) hatte 1306 Research-Items inkl. 185
   frischer VULTURE-Screener-Kandidaten, aber keine einzige Decision. Der
   nächste Zyklus fensterte trotzdem direkt danach weiter — dieser ganze
   Batch wurde nie wieder gezeigt, für niemanden.
2. Der F046-Prompt-Deckel (30 Items, reine Rekenz-Sortierung) ließ EDGAR
   (Filings alle paar Minuten) alle 30 Plätze belegen. Live gemessen: VULTUREs
   letzter echter Zyklus bekam 30/30 EDGAR-Filings, 0 Screener-Kandidaten,
   obwohl 185 im Pool lagen.

**Scope:** zwei gezielte Pipeline-Fixes (Fenster-Grenze + Prompt-Auswahl).
**Non-Scope:** Charter-Änderungen, Risk-Gate-Anpassungen, Lockerung von
Schwellenwerten — ausdrücklich nicht angefasst (Invarianten 1/10, "Was Claude
Code nicht tun darf").

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness (kein Informationsvorsprung) | ja, direkt gestärkt | Beide Fixes wirken auf den gemeinsamen `research_item`-Pool bzw. die generische Prompt-Bau-Logik — identisch für alle 6 Personas, keine Persona-spezifische Sonderbehandlung. |
| Persona-Charter unverändert | ja, geprüft | Kein `charter_version`-Bump, keine Signal-/Universums-Änderung in `src/personas/charters.py` oder `config/personas/*.yaml`. |
| #7 Kosten-Caps | nein, neutral | `_MAX_PROMPT_RESEARCH_ITEMS` bleibt bei 30 — die faire Auswahl ändert *welche* 30 Items gesendet werden, nicht wie viele. Die Fenster-Fix kann in Ausfall-Szenarien mehr Rohdaten *synthetisieren* (mehr `research_item`-Zeilen in der DB), aber der Prompt-Deckel begrenzt weiterhin, was tatsächlich an die LLM geht. |

**Design-Entscheidungen:**
- **Fenster-Grenze = "letzter Zyklus mit mindestens einer Decision"**, nicht
  "letzter Zyklus chronologisch". Ein `REJECT_IDEA` zählt als "gesehen" (die
  Daten wurden bewertet, nicht verloren) — nur ein Zyklus mit exakt null
  Decisions (z. B. Totalausfall aller 6 LLM-Calls) gilt als "nie passiert".
  Bewusst auf Zyklus-Ebene, nicht pro Persona: passt zum bestehenden
  "gemeinsamer Pool pro Zyklus"-Modell (kein neuer Tracking-Mechanismus pro
  Persona nötig).
- **Faire Auswahl = Round-Robin über `source_type`**, neueste zuerst
  innerhalb jedes Typs. Einfach, deterministisch (Dict-Einfügereihenfolge
  folgt der festen Quellen-Reihenfolge in `synthesize_research_items`),
  kein zusätzlicher LLM-Call. Alternative verworfen: fester Kontingent pro
  Typ (z. B. "max 10 EDGAR") — Round-Robin passt sich automatisch an, wenn
  ein Typ in einem Zyklus leer ist (andere Typen füllen die Lücke).
- **Nicht angefasst:** ob ein Zyklus überhaupt genug *neue* Rohdaten hat, um
  ein Kaufsignal zu rechtfertigen, bleibt Marktrealität — Tag 1 des
  Experiments mit dünner EDGAR-/Zeitschriften-Historie kann durchaus
  ehrlich wenig hergeben. Dieses Feature stellt nur sicher, dass Personas
  sehen, was tatsächlich (fair, vollständig) verfügbar ist — es erzeugt
  keine künstlichen Signale.

**Kosten:** keine zusätzlichen laufenden Kosten (siehe Tabelle oben).
**Fairness:** siehe oben — beide Fixes sind Fairness-*Verbesserungen*.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/orchestrator/test_research_synthesis.py`:
- `test_window_skips_past_a_cycle_with_no_decisions` — ein Zyklus ohne
  Decision wird nicht zur Fenster-Grenze; Daten aus davor bleiben sichtbar.
- `test_window_stops_at_a_cycle_that_did_produce_a_decision` — Regressionstest
  für den unveränderten Normalfall.
- Vier bestehende Boundary-Tests angepasst (`_make_decided_cycle_at`
  Helfer): sie testeten ursprünglich reine Fenstergrenzen und brauchen jetzt
  eine "echte" (Decision-tragende) Vorgänger-Zyklus-Fixture, um weiterhin
  genau das zu testen statt versehentlich die neue Resilienz-Logik.

`tests/orchestrator/test_persona_analysis.py`:
- `test_prompt_selection_is_fair_across_source_types` — 90 EDGAR-Items +
  1 Screener-Item, Cap 30 → das Screener-Item muss im Prompt landen.

## 4. Implementierung

- `src/orchestrator/research_synthesis.py`: `_resolve_window_start` joint
  jetzt gegen `Decision` (`Cycle` ⋈ `Decision` auf `cycle_id`), sonst
  unverändert (gleicher Bootstrap-Fallback, gleiche Session-Filterung).
- `src/orchestrator/persona_analysis.py`: neue `_select_prompt_items`
  (Round-Robin über `source_type`-Buckets, Rekenz-sortiert innerhalb jedes
  Buckets) ersetzt die reine `sorted(...)[:N]`-Kürzung in `_build_messages`.

## 5. Test & Rollout

- `uv run pytest`: 478 passed. `ruff check`/`format --check`, `mypy`: clean.
- Deployment: scp der beiden geänderten Dateien + `docker compose build api
  scheduler` + `up -d` auf `atlas-ugreen`.
- Verifikation: außerplanmäßiger Zyklus nach Deploy, `research_item`- und
  `decision`-Tabellen geprüft (Quellen-Mix im Prompt, Fenster reicht über
  den vorherigen Ausfall-Zyklus zurück).
- **Rollback-Pfad:** reiner Code-Revert beider Funktionen (kein
  Schema-/Config-Change).
