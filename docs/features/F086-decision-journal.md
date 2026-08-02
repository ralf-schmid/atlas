# F086 — Decision Journal (inkl. Rejected-Filter)

**Status:** umgesetzt und deployt (02.08.2026)
**Phase:** 5, Block 3 (UI-Ausbau)
**Abhängigkeiten:** `decision` (inkl. `rejection_reason`, `input_research_ids`),
`order_record`, `review` (F084), F033 (Alterssignal je Research-Item).

## 1. Zieldefinition

DoD-Satz (§8 P5): „UI komplett (… Decision Journal inkl. Rejected-Filter …)";
Feature-Schnitt aus `phase-5.md`: „chronologisch je Portfolio, Thesis, verlinkte
`input_research_ids`, Erwartung vs. Ist, Review-Verdict, **Rejected-Filter**".

**Scope:**
- API: `GET /api/personas/{name}/decisions` um `filter` erweitert und um die
  drei fehlenden Blöcke ergänzt — `expected` (was die Persona erwartet hat),
  `outcome` (was der Broker tatsächlich getan hat), `review` (F084-Verdikt).
- UI: neue Route `/journal` mit Persona-Auswahl und Filter-Umschalter,
  mobile-first, plus Eintrag in der Bottom-Nav.
- Die Persona-Detailseite nutzt dieselbe Karten-Komponente, statt eine zweite
  Darstellung derselben Daten zu pflegen.

**Non-Scope:** Impuls-Vergleich (F087) und Agent Trace (F088) — eigene Features.

## 2. Kritische Betrachtung

- **Filter serverseitig, nicht im Client.** Bei ~150 `hold`-Decisions gegen
  5 Trades würde ein Client-Filter über die neuesten 50 Zeilen drei Trades von
  fünfzig Holds zeigen und das Journal nennen. Der Filter gehört in die Query,
  damit `limit` weiter etwas Sinnvolles bedeutet. Nebeneffekt: die Seite bleibt
  eine reine Server-Component ohne JS-Bundle (wie das Leaderboard F085).
- **Was zählt als „verworfen"?** Eine Idee kann auf zwei Arten sterben: die
  Persona verwirft sie selbst (`reject_idea` mit `rejection_reason`) oder das
  Risk-Gate bzw. HITL lehnt sie ab (`risk_rejected`/`hitl_rejected`). Beides
  gehört in den Rejected-Filter — sonst fehlen genau die Fälle, die F101
  aufgedeckt hat (5 Gate-Rejects durch Rundung).
- **`expected_outcome` ist freies JSONB vom LLM-Pfad.** Schlüssel können fehlen,
  `null` oder (selten) ein String sein. Der Journal-Endpoint parst defensiv
  (`_as_float`) — in einem reinen Read-Pfad ist ein fehlender Wert besser als
  ein 500er.
- **Invarianten:** reiner Read-Pfad, kein LLM (0 USD), keine Order-Rechte.
  Zeitschriften-Volltexte bleiben draußen: das Journal zeigt weiterhin nur
  `summary` + Quelle (`ResearchRefOut` selektiert kein `raw`, CLAUDE.md).

## 3. Umsetzung

- `filter=all|traded|rejected|hold` (unbekannter Wert → 422). `traded` = Aktion
  `buy`/`close`, `rejected` wie oben, `hold` = Aktion `hold`.
- `DecisionOut` bekommt `expected` (Einstieg, Stop, Kursziel, Horizont),
  `outcome` (Order-Status, Stückzahl, Fill-Preis, Fill-Zeitpunkt) und `review`
  (Verdikt, Abweichung, Slippage-Malus, Lessons). Alle drei sind optional bzw.
  `null`, wenn es (noch) keine Order bzw. kein Review gibt.
- `web/src/components/DecisionCard.tsx` rendert einen Eintrag: Aktion +
  Instrument, Status, Zeitpunkt, Sicherheit, These, Ablehnungsgrund,
  Erwartung/Ist, Review-Verdikt mit Lessons, zitierte Research-Items (mit Link
  zur Quelle, wo vorhanden).
- `/journal?persona=…&filter=…` — beide Umschalter sind Links (Touch-Target
  44 px), kein Client-State.

## 4. Tests (`tests/api/test_routes.py`)

- Erwartung, Ausgang und Review werden vollständig geliefert (Fill-Preis 101,25,
  Verdikt, Slippage-Malus, Lessons-Text).
- Ohne Order und ohne Review sind `outcome`/`review` `null` und `expected`
  leer — statt eines 500ers bei fehlenden JSONB-Schlüsseln.
- Rejected-Filter erfasst **beide** Sterbearten (`reject_idea` **und**
  `risk_rejected`) und lässt `hold`/`buy` draußen.
- `traded` liefert `buy`+`close`, `hold` nur `hold`.
- Unbekannter Filter → 422.

Gesamtlauf 886 passed; ruff/mypy/eslint/tsc grün.

## 5. Live-Verifikation

(nach Deployment)

## 6. Rollback

Additiv: neuer Query-Parameter mit Default `all`, neue optionale
Response-Felder, neue Route. `git revert` + Rebuild von `api`/`web`. Kein
Schema-Change, keine Migration.
