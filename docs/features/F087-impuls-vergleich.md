# F087 — Impuls-Vergleich (1 Research-Item, 6 Sichten)

**Status:** umgesetzt und deployt (02.08.2026)
**Phase:** 5, Block 3 (UI-Ausbau)
**Abhängigkeiten:** `research_item`, `decision.input_research_ids` (Pflichtfeld,
DB-validiert), F086 (gemeinsame Label-/Farblogik).

## 1. Zieldefinition

Feature-Schnitt aus `phase-5.md`: „Einstieg über ein `research_item`: was hat
jede Persona daraus gemacht (gekauft/verworfen/ignoriert) und warum." Damit wird
ARCHITECTURE.md §1.1 Punkt 3 („Gleiche Impulse, unterschiedliche
Interpretation") überhaupt erst sichtbar.

**Scope:**
- `GET /api/research/impulses` — Auswahlliste: Items, die mindestens eine
  Persona zitiert hat, mit Zähler „x/6 zitiert".
- `GET /api/research/{id}/comparison` — der Impuls plus **eine Reaktion je
  aktiver Persona**.
- UI: `/impulse` (Liste) und `/impulse/{id}` (Vergleich), Eintrag in der
  Bottom-Nav.

**Non-Scope:** Agent Trace (F088), Volltext der Quelle (CLAUDE.md verbietet
Zeitschriften-Volltexte in der UI — gezeigt werden `summary` und, wo vorhanden,
ein Link auf die Originalquelle).

## 2. Kritische Betrachtung

- **„Ignoriert" braucht eine belastbare Definition, sonst ist es eine
  Unterstellung.** Umsetzung: die Persona hat in dem Zyklus, zu dem das Item
  gehört, eine Entscheidung getroffen, aber ein anderes Item zitiert. Hatte sie
  in diesem Zyklus **gar keine** Entscheidung (Ausfall, pausiert), meldet der
  Vergleich `no_run` statt „ignoriert" — sonst würde eine Persona für eine
  Infrastrukturlücke verantwortlich gemacht. Genau dieser Fall ist real:
  13 Zyklen ohne jede Decision am 30./31.07. ([F101](F101-trade-activity-root-cause.md) §2 U1).
- **Ein abgelehnter Kauf ist kein Handel.** `buy` mit Status `risk_rejected`
  bzw. `hitl_rejected` zählt als `rejected`, nicht als `traded` — sonst
  behauptet der Vergleich, die Persona habe auf den Impuls gehandelt.
- **Zitate aus späteren Zyklen zählen mit.** Seit dem F045-Suchtool und den
  F101-Companion-Items kann eine Persona ein Item zitieren, das aus einem
  früheren Zyklus stammt. Die Reaktions-Abfrage filtert deshalb nicht auf den
  Zyklus des Items, sondern sucht alle Decisions, die es zitieren.
- **Fairness/Invarianten:** reiner Read-Pfad, kein LLM, identische Darstellung
  für alle 6 Personas.

## 3. Tests (`tests/api/test_routes.py`)

- Die Auswahlliste enthält nur zitierte Items und zählt die zitierenden
  Personas korrekt (2 von 2, nicht die Zahl der Decisions).
- Der Vergleich liefert je Persona genau eine Reaktion und unterscheidet alle
  fünf Fälle: `traded`, `rejected` (mit Begründung), `hold`, `ignored`
  (entschied im Zyklus, zitierte anderes), `no_run` (keine Entscheidung).
- Ein vom Risk-Gate abgelehnter Kauf zählt als `rejected`.
- Unbekannte Item-ID → 404.

Gesamtlauf 890 passed; ruff/mypy/eslint/tsc grün.

## 4. Live-Verifikation

(nach Deployment)

## 5. Rollback

Additiv: zwei neue Endpoints, zwei neue Routen, ein Nav-Eintrag. `git revert` +
Rebuild von `api`/`web`. Kein Schema-Change, keine Migration.
