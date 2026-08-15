# F110 — Verlorene Reviews durch ein überzähliges Komma

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 5 (Bugfix im Review-Zweig)
Auslöser: Nebenbefund beim formalen Review-Nachweis (Phase-5-DoD)

## 1. Befund

Beim Nachweis „jede geschlossene Position hat binnen 7 Tagen ein Review" fiel auf,
dass zwei geschlossene Positionen (VULTURE/LUNG, CHARTIST/ADSK) seit Tagen ohne
Review dastanden, obwohl der Median-Vorlauf sonst bei **0,39 Tagen** liegt. Ein
manueller Sweep-Lauf reproduzierte es:

```
SweepResult(reviewed=1, skipped_existing=0, deferred_budget=0, failed=1)
src.review.agent.ReviewParseError: no JSON object in review response
```

Die Fehlermeldung nennt die Ursache nicht — sie verwarf die Rohantwort. Erst ein
Live-Mitschnitt zeigte, woran es liegt. Die Antwort war **fast** valides JSON:

```
{"verdict":"inconclusive","lessons_text":"… keine belastbare Aussage treffen.",}
                                                                              ^^
```

Ein **überzähliges Komma vor der schließenden Klammer**, bei
`finish_reason: stop` — also kein abgeschnittener Output, sondern eine Marotte des
Modells. `json.loads` lehnt das ab (Python ist hier strenger als JavaScript), und
der Fallback im Parser schnitt zwar Prosa und Markdown-Zäune weg, änderte aber am
Komma nichts. Ergebnis: Review verworfen, LLM-Call bezahlt, Kennzahl fehlt.

**Wie oft:** in drei Versuchen gegen dieselbe Decision zweimal. Es ist also kein
Einzelfall, sondern eine stille Fehlerquote auf jedem Review und jedem
Meta-Review — beide Module trugen byte-identische Kopien desselben Parsers.

**Was es nicht war:** kein Budget-Stopp, kein LLM-Ausfall (der `cost_ledger` weist
für den 14.08. 139 Calls und 2,90 USD aus), kein Token-Limit.

**Entwarnung beim Schadensbild:** `find_due_decisions` ist stateless — eine
gescheiterte Decision ist am nächsten Tag wieder fällig. Der Fehler kostet also
Verzug und Geld, nicht das Review selbst. Bei einer Frist von 7 Tagen und einem
Tageslauf ist das verkraftbar; genau deshalb ist es auch nie jemandem aufgefallen.

## 2. Umsetzung

| Datei | Änderung |
|---|---|
| `src/llm/json_output.py` | **neu** — `parse_json_object()` (drei Pässe: strikt, `{…}`-Span, Span ohne Trailing Commas) und `excerpt()` |
| `src/review/agent.py` | nutzt den gemeinsamen Parser; `ReviewParseError` trägt jetzt einen Auszug der Rohantwort |
| `src/review/meta_agent.py` | dito für `MetaReviewParseError` |

Die beiden lokalen Kopien von `_parse_json_object` sind entfallen. Das ist die
einzige Zusammenlegung in diesem Fix — sie war nötig, weil der Defekt sonst an
zwei Stellen zu reparieren gewesen wäre und beim nächsten Mal wieder auseinander
läuft.

**Bewusst kein allgemeiner „JSON-Reparierer".** Toleriert wird genau die eine
Fehlform, die produktiv auftrat. Ein Parser, der bei kaputtem Output rät, würde
ein verstümmeltes Verdict in eine protokollierte Bewertung verwandeln — und das
Decision Journal ist die Grundlage der Wettbewerbswertung. Die Strenge beim
Verdict selbst (unbekannter Wert ⇒ Fehler, nie Default) bleibt unangetastet.

## 3. Testdefinition

`tests/llm/test_json_output.py`, 10 Tests:

1. `test_parses_plain_json_object` — der Normalfall bleibt unberührt.
2. `test_parses_trailing_comma_before_closing_brace` — der Live-Fall.
3. `test_parses_trailing_comma_in_nested_array` — dieselbe Marotte in Listen.
4. `test_parses_json_wrapped_in_prose_and_a_fence` — das bisherige Verhalten
   bleibt erhalten (Regressionsschutz für den alten Fallback).
5. `test_comma_inside_a_string_value_is_untouched` — die Regex darf nur
   strukturelle Kommas treffen; ein `,}` im Fließtext einer Lehre muss bleiben.
6.–8. `None` bei fehlendem Objekt, leerem Input und einem JSON-Array.
9. `test_excerpt_keeps_head_and_tail` — der Auszug muss das **Ende** zeigen, dort
   sitzen die Defekte; ein reiner Prefix hätte das Komma nie sichtbar gemacht.
10. `test_excerpt_collapses_whitespace_and_passes_short_text_through`.

Gesamtlauf: **1006 passed, 26 deselected**; `ruff`, `mypy src` clean.

## 4. Rollout

- Deployt am 15.08.2026 (`api`, `scheduler`). Kein Schema-Change, keine Migration,
  keine Config.
- **Verifikation:** der zuvor reproduzierbar scheiternde ADSK-Review lief nach dem
  Deploy durch (siehe `docs/dod/phase-5.md`).
- **Rollback:** Revert des Commits. Ein Config-Flag wäre hier sinnlos — der alte
  Zustand ist schlicht der Fehler.

## 5. Folgearbeit

- **Ein Retry im Sweep** wäre die nächste Härtung: heute wird ein Parse-Fehler nur
  gezählt und die Decision wandert in den Folgetag. Bei einer Fehlerquote von grob
  einem Drittel würde ein einziger Wiederholungsversuch den Verzug praktisch
  beseitigen. Nicht in diesem Fix, weil er dann zwei Dinge auf einmal täte —
  braucht Ralfs Go.
