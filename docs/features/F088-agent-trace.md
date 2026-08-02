# F088 — Agent Trace

**Status:** umgesetzt und deployt (02.08.2026)
**Phase:** 5, Block 3 (UI-Ausbau) — letzter offener UI-Baustein der Phase
**Abhängigkeiten:** `cycle`, `agent_run` (Tokens/Kosten/Fehler), `decision`
(Status + `hitl`-JSONB), `research_item`.

## 1. Zieldefinition

Feature-Schnitt aus `phase-5.md`: „pro Zyklus Läufe, Token/Kosten
(`cost_ledger`, `agent_run`), Fehler, HITL-Ereignisse."

**Scope:**
- `GET /api/cycles` — die letzten Zyklen mit Aggregaten: Läufe, davon
  fehlgeschlagen, Decisions, Research-Items, Token ein/aus, Kosten.
- `GET /api/cycles/{id}/trace` — Detail: jeder `agent_run` mit Agent, Persona,
  Status, Tokens, Kosten und **Fehlertext**; Decisions nach Status; alle
  HITL-Ereignisse des Zyklus.
- UI: `/trace` (Liste) und `/trace/{id}` (Detail), Eintrag in der Bottom-Nav.

## 2. Kritische Betrachtung

- **Kosten je Zyklus kommen aus `agent_run`, nicht aus `cost_ledger`.** Der
  Ledger ist die Budget-Sicht (Scope + Persona + Tag, F028) und trägt keine
  `cycle_id` — er lässt sich nicht nach Zyklus schneiden. `agent_run` trägt
  beides und ist damit die richtige Quelle für diese Ansicht. Der Feature-Text
  nennt beide Tabellen; das ist hier bewusst aufgelöst und dokumentiert.
- **Der stumme Zyklus ist der eigentliche Grund für dieses Feature.** Am
  30./31.07. liefen 13 Zyklen mit Research, aber ohne einen einzigen
  `agent_run` — sichtbar wurde das erst durch eine SQL-Abfrage, weil die
  Container-Logs beim nächsten Rebuild weg waren
  ([F101](F101-trade-activity-root-cause.md) §2 U1). Die Trace-Liste markiert
  genau dieses Muster (Research > 0, Läufe = 0) gelb und benennt es im Klartext;
  das Detail sagt „der Zyklus ist gestartet und die Analyse-Schicht kam nie zum
  Zug" statt eine leere Liste zu zeigen.
- **Fehlgeschlagene Läufe zeigen ihren Fehlertext ungekürzt.** Der Wert des
  Traces liegt genau darin — der `CreditsError` des Providers stand nur im
  `agent_run.error`, nicht im Alert.
- **HITL-Ereignisse lesen aus dem `hitl`-JSONB** (`required`, `requested_at`,
  `amount_usd`, `decided_by`, `at`) und werden defensiv geparst; für Paper ist
  HITL abgeschaltet, die Ansicht sagt das explizit statt „keine Daten".
- **Invarianten:** reiner Read-Pfad, kein LLM, keine Order-Rechte.

## 3. Tests (`tests/api/test_routes.py`)

- Aggregation über `agent_run`: Läufe, fehlgeschlagene Läufe, Token-Summen,
  Kosten, Research- und Decision-Zähler.
- Der stumme Zyklus (Research vorhanden, 0 Läufe, 0 Decisions) wird als solcher
  ausgewiesen.
- Detail: gemeinsamer Lauf ohne Persona (`market_research`) und
  persona-gebundener Lauf mit Fehlertext; Decisions nach Status gruppiert.
- HITL-Ereignis mit Betrag, Zeitpunkten und Entscheider; Decisions ohne HITL
  tauchen nicht auf.
- Unbekannte Cycle-ID → 404.

Gesamtlauf 896 passed; ruff/mypy/eslint/tsc grün.

## 4. Nebenänderung: Bottom-Nav-Labels

Mit fünf Einträgen bleiben auf 390 px rund 62 px Textbreite je Eintrag —
„Leaderboard" würde umbrechen oder die Leiste in horizontales Scrollen zwingen.
Die Nav nutzt deshalb Kurzlabels („Ranking", „Trace"); die Seitenüberschriften
behalten die vollen Namen.

## 5. Live-Verifikation (02.08.2026)

- `GET /api/cycles?limit=30` liefert die letzten 30 Zyklen mit Aggregaten; die
  laufenden Zyklen zeigen plausible Werte (7–8 Läufe, 6 Decisions, 130k–380k
  Token, 0,32–0,59 USD je Zyklus).
- **Der Ausfall vom 30./31.07. ist jetzt in der UI sichtbar:** genau **13** der
  30 gelisteten Zyklen erfüllen das Muster „Research > 0, Läufe = 0" und sind
  gelb markiert — dieselbe Zahl, die die F101-Analyse per SQL ermittelt hatte.
  Beispiel `2026-07-30 C1`: 1.500 Research-Items, 0 Läufe, 0 Decisions.
- `/trace` und `/trace/{id}` liefern 200.

## 6. Rollback

Additiv: zwei Endpoints, zwei Routen, ein Nav-Eintrag. `git revert` + Rebuild
von `api`/`web`. Kein Schema-Change, keine Migration.
