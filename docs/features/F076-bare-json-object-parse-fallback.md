# F076 — Robusteres Parsing für unfenced JSON hinter Prosa

Status: umgesetzt, live verifiziert
Datum: 2026-07-15
Phase: 5

## 1. Zieldefinition

Ralfs Meldung: erneut `llm_output_parse_error` (VULTURE/CRYPTOR/HYPE, Zyklus
00:00), obwohl F073 (adaptive thinking abgeschaltet) und F065/F057 (Retry,
Codefence-Parser) bereits deployt waren. Live-Diagnose gegen die echte
Box-DB: F073s `finish_reason`-Diagnostik (genau dafür gebaut) zeigte
sofort, dass dies **kein** Wiederauftreten des alten Musters ist —
`finish_reason=stop` bei **substantiellem** `tokens_out` (2000-2400) *und*
vollständigem, kohärentem Inhalt (`error_len` 1450-1900 Zeichen), nicht die
leere Completion, die F073 behoben hat.

Volltext-Abruf eines Falls zeigte die tatsächliche Ursache: das Modell
antwortet trotz der Prompt-Anweisung ("Antworte ausschließlich mit einem
JSON-Objekt... keine Erklärung davor/danach") mit **Prosa-Begründung zuerst**
("Keine zusätzlichen Treffer im Pool. Die verfügbaren BTC-Dominanz-
Datenpunkte..."), gefolgt von einem **korrekt geformten, aber nicht in
Codefences eingeschlossenen** JSON-Objekt. `parse_llm_decision`
(`src/orchestrator/llm_decision_schema.py`) fand keinen Codefence-Match und
fiel auf `json.loads(raw_content.strip())` über den **kompletten** String
zurück — das schlägt sofort fehl, sobald der String nicht ab Zeichen 0 reines
JSON ist, selbst wenn ein valides Objekt weiter hinten im Text steht.

**Kein Widerspruch zu F073:** unterschiedliche Ursache, unterschiedliches
Symptom (leerer Inhalt vs. valider Inhalt an falscher Stelle im String) —
F073 bleibt die korrekte, weiterhin gültige Erklärung für die *alten* Fälle
(`tokens_out` klein, `error_len=0`); alle seit F073-Deploy beobachteten
Fälle (3 von 3, Stand 15.07.) zeigen ausschließlich dieses neue Muster.

**Scope:** dritter Fallback-Schritt im bestehenden Parser (Codefence →
Ganzer-String → **balancierter `{...}`-Block irgendwo im String**) +
Testabdeckung. **Non-Scope:** Prompt-Härtung/erneutes Anmahnen von "nur
JSON" (das Modell hat die Anweisung bereits, ignoriert sie gelegentlich —
ein robusterer Parser behebt das strukturell, ohne auf zukünftiges
Modellverhalten zu wetten), natives JSON-Mode/`response_format` am
LiteLLM-Client (größerer Eingriff, durch die live beobachteten Daten nicht
zwingend begründet — der robuste Extraktions-Fallback reicht für alle 3
beobachteten Fälle).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein | `parse_llm_decision` ist derselbe Pfad für alle 6 Personas, keine Sonderbehandlung. |
| Finanz-Kennzahlen vom LLM ausrechnen lassen | nein | Der Parser extrahiert nur das vom Modell selbst gelieferte JSON, berechnet nichts. |

**Design-Entscheidung:** Fallback-Regex `\{.*\}` (DOTALL, greedy) statt
eines echten Klammer-Zählers — greedy `.*` erreicht die *letzte* `}` im
String, nicht die erste verschachtelte; für dieses Schema unproblematisch,
da `thesis_text`/`input_research_ids` laut Pydantic-Modell keine
literalen `{`/`}`-Zeichen enthalten können (String bzw. Liste von
UUID-Strings). Nur aktiv, wenn **weder** ein Codefence-Match **noch** der
Ganzer-String-Parse erfolgreich war — ändert das Verhalten der beiden
bereits funktionierenden, getesteten Pfade nicht.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/orchestrator/test_llm_decision_schema.py`:
- `test_parses_bare_json_object_preceded_by_prose` — exakt das live
  beobachtete Muster (deutsche Prosa-Begründung, dann unfenced JSON).
- `test_parses_bare_json_object_with_leading_and_trailing_prose` — Prosa vor
  *und* nach dem Objekt.
- Alle 7 bestehenden Tests (Codefence, Ganzer-String, leerer String, kaputtes
  JSON) bleiben unverändert grün — Regressionsschutz für F057/F065.

## 4. Implementierung

`src/orchestrator/llm_decision_schema.py`: neue `_BARE_JSON_OBJECT_RE`
(`\{.*\}`, `DOTALL`); `parse_llm_decision` versucht jetzt in Reihenfolge
Codefence → ganzer String → (nur wenn kein Codefence gefunden wurde)
`{...}`-Ausschnitt; `_try_parse_json`-Helfer für den gemeinsamen
`try/except json.JSONDecodeError`-Block.

## 5. Test & Verifikation

- `uv run pytest -q`: **607 passed** (2 neue Tests). `ruff check`/`format
  --check`, `mypy src`: clean.
- **Live-Diagnose (nicht Reproduktion) gegen die echte Box-DB:** Volltext
  aller 3 seit F073-Deploy aufgetretenen `llm_output_parse_error`-Fälle
  abgerufen — alle 3 exakt das "Prosa dann unfenced JSON"-Muster, alle 3
  hätten mit dem neuen Fallback erfolgreich geparst (manuell gegen den
  gespeicherten Volltext eines Falls mit `parse_llm_decision` bestätigt).
- **Verbleibende Beobachtung:** wie bei F073 — die tatsächliche
  `llm_output_parse_error`-Rate über die nächsten Live-Zyklen sollte auf 0
  fallen; ein verbleibender Fall wäre jetzt entweder eine dritte, neue
  Variante (per `finish_reason`-Diagnostik direkt sichtbar) oder ein
  tatsächlich kaputtes/unvollständiges JSON.

## 6. Rollback-Pfad

Rein additiv: ein neuer Fallback-Schritt, aktiv nur wenn beide bestehenden
Pfade bereits fehlgeschlagen sind. Commit zurücknehmen genügt, kein
Schema-Change.
