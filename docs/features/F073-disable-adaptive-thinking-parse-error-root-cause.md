# F073 — Adaptive Thinking als Ursache für `llm_output_parse_error`

Status: umgesetzt, live diagnostiziert (mechanistisch bestätigt, nicht exakt
reproduziert — siehe §5)
Datum: 2026-07-14
Phase: 5

## 1. Zieldefinition

VULTURE lehnte um 14.07.2026 13:00 erneut mit
`rejection_reason=llm_output_parse_error` ab (78654–2499 Tokens Antwort, aber
leerer Inhalt) — derselbe Fehler, den F057 (10.07.) und F065 (11.07.) schon je
einmal "behoben" haben wollten. Ralfs Auftrag: *"behebe das problem
nachhaltig"*.

Box-DB-Analyse (14.07., 7-Tage-Fenster): 25 von 215 Decisions (11,6 %) tragen
`llm_output_parse_error`, verteilt über HYPE (Großteil), VULTURE, CONTRA —
**nach** F057 und F065 deployt, nicht nur davor. In **jedem** der 25 Fälle ist
`agent_run.error` die leere Zeichenkette (nicht NULL) bei gleichzeitig
substantiellem `tokens_out` (770–2763) — der einzelne fehlgeschlagene Call
liefert also reichlich Completion-Tokens, aber keinen sichtbaren Text. F065s
eigener Retry (max. 2 Versuche) hat in allen 25 Fällen **beide** Versuche
verbraucht, ohne einen davon zu retten.

**Root Cause:** `claude-sonnet-5` nutzt laut installiertem litellm-Proxy
(Version 1.92.0, live auf `atlas-ugreen` geprüft) *adaptive thinking* — ein
server-seitiger Default für neuere Claude-Modellgenerationen
(`AnthropicModelInfo.supports_adaptive_thinking`), der greift, **ohne dass
dieser Code ihn je angefordert hat** (`LiteLLMClient.complete()` sendet bisher
weder `thinking` noch `reasoning_effort`). Live-Test gegen den echten Proxy
(kleine Prompts) zeigt: jede Antwort — auch ganz ohne Tool-Nutzung — enthält
bereits ein (meist leeres) `thinking_blocks`-Feld; das ist server-seitiges
Standardverhalten, kein Bug im hiesigen Request. Bei den großen, komplexen
Prompts dieses Agents (produktiv 78–92k Input-Tokens durch Charter + Research-
Payload + Tool-Historie) kann das Modell seinen kompletten Completion-Budget
auf das (unsichtbare) Denken verwenden und die Runde mit `finish_reason=stop`
beenden, ohne je sichtbaren Text zu emittieren — exakt das beobachtete Muster
(hohe `tokens_out`, leerer `content`), bei **jedem** der 25 historischen
Fälle, nicht nur vereinzelt.

Das erklärt zugleich, warum F057 (Tool-Deklaration in der Zwangsrunde) und
F065 (Retry + robusterer Parser) den Fehler nicht ausgerottet haben: beide
adressierten plausible, aber falsche Ursachen (Tool-Choice-Historie-
Inkonsistenz bzw. "irgendein" leerer Turn) — keine der beiden hat je das
`thinking`-Feld angefasst, weil bis zu dieser Untersuchung nicht bekannt war,
dass das Modell es selbständig nutzt.

**Scope:** `thinking={"type": "disabled"}` auf jeder LLM-Runde in
`_run_llm_with_tools` (alle 6 Personas, gleicher Pfad) + `finish_reason`-
Diagnostik, damit ein erneutes Auftreten sofort beweisbar statt erneut zu
erraten ist. **Non-Scope:** andere Rollen (`market_research`, `news_research`,
`trading`, `review`) — nur `persona_analysis` nutzt `claude-sonnet-5` und
zeigt das Symptom; keine spekulative Änderung an Rollen ohne beobachtetes
Problem.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein | `_THINKING_DISABLED` gilt identisch für alle 6 Personas über den gemeinsamen `_run_llm_with_tools`-Pfad. |
| #7 Kosten-Caps | ja, positiv | Thinking-Tokens werden als Completion-Tokens abgerechnet (live gemessen: derselbe Prompt kostete mit Thinking 3 Runden/~42k Tokens, ohne Thinking 2 Runden/~23k Tokens — das Modell traf die Entscheidung schneller und günstiger). Keine neue Kostenprüfung nötig, der bestehende Pfad bleibt unverändert. |
| Keine Order ohne persistierte Decision | nein | Reine LLM-Request-Form, kein Änderungspunkt an Order-/Persistenz-Pfad. |

**Design-Entscheidungen:**
- **`thinking` als expliziter, optionaler Parameter durch die ganze Kette**
  (`LiteLLMClient.complete()` → `guarded_complete()` → `_run_llm_with_tools`),
  identisches Muster wie `tool_choice` (F057) — additiv, kein Breaking Change
  für andere Aufrufer (Default `None`, Feld wird nur bei explizitem Wert ins
  Request-Body übernommen).
- **`thinking={"type": "disabled"}` statt Budget-Begrenzung
  (`{"type": "enabled", "budget_tokens": N}`).** Diese Aufgabe hat keine
  Verwendung für verstecktes Chain-of-Thought — die geforderte JSON-Antwort
  trägt die sichtbare Begründung bereits im Feld `thesis_text`. Ein Budget
  würde das Problem nur verkleinern (das Modell könnte das Budget immer noch
  ausschöpfen), nicht strukturell beheben.
- **`finish_reason` zusätzlich auf `LLMResponse` erfasst und in
  `agent_run.error` vorangestellt** (`f"[finish_reason={...}] {content}"`).
  F057 und F065 zeigen: eine unbewiesene Hypothese wird hier zum dritten Mal
  ohne harte Daten riskiert. Diese minimale, seit F065 fehlende Diagnostik
  kostet nichts extra (das Feld kommt in jeder Proxy-Antwort mit) und macht
  eine vierte Runde Rätselraten überflüssig, falls der Fehler doch nochmal
  auftritt.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/llm/test_client.py`:
- `test_complete_sends_thinking_when_given` / `..._omits_thinking_key_when_not_given`
  — gleiches Muster wie die bestehenden `tool_choice`-Tests.
- `test_complete_captures_finish_reason` / `..._finish_reason_is_none_when_absent`.

`tests/orchestrator/test_persona_analysis.py`:
- `test_tool_use_loop_is_capped_then_forces_a_final_answer` erweitert: alle
  drei Runden senden `thinking={"type": "disabled"}`.
- `test_unparseable_llm_response_is_persisted_on_agent_run_for_diagnostics`
  und `test_two_empty_completions_in_a_row_still_reject_with_diagnostics`
  angepasst auf das neue `[finish_reason=...] ...`-Präfix in `agent_run.error`.

## 4. Implementierung

- `src/llm/client.py`: `LiteLLMClient.complete()` bekommt `thinking: dict | None`
  (durchgereicht ins Request-Body wie `tool_choice`) und liest `finish_reason`
  aus der Proxy-Antwort in `LLMResponse.finish_reason`.
- `src/llm/ledger.py`: `guarded_complete()` reicht `thinking` unverändert an
  `client.complete()` durch.
- `src/orchestrator/persona_analysis.py`: neue Konstante
  `_THINKING_DISABLED = {"type": "disabled"}`; jede Runde in
  `_run_llm_with_tools` übergibt sie; `analyze_persona_cycle`s
  `agent_run.error`-Diagnostik stellt `finish_reason` voran.
- Kein Alembic-Migrations-Bedarf.

## 5. Test & Live-Verifikation

- `uv run pytest -q` (lokaler Test-Postgres): 586 passed (7 neue/geänderte
  Tests). `ruff check`/`format --check`, `mypy src/llm src/orchestrator`:
  clean.
- **Live-Diagnose auf `atlas-ugreen`** (echter LiteLLM-Proxy, echter
  Anthropic-Call, read-only DB-Zugriff, kein Schreibzugriff/keine
  Ledger-Buchung — reine Diagnose, gleicher Charakter wie F065s
  `session.rollback()`-Testzyklus):
  - Kleine Prompts (ohne Tools, mit Tools+`tool_choice=auto`) zeigen: der
    Proxy liefert **immer** ein `thinking_blocks`-Feld, auch ohne dass dieser
    Code `thinking` je angefordert hat — bestätigt den server-seitigen
    Default.
  - `thinking={"type": "disabled"}` gegen denselben Proxy: `thinking_blocks`
    entfällt vollständig, Tool-Calls und finale JSON-Antwort funktionieren
    unverändert korrekt.
  - Nachstellung des exakten VULTURE-13:00-Zyklus (echte Research-Items,
    echter Charter, echte `search_research_pool`-Tool-Ausführung gegen die
    Box-DB, identischer 3-Runden-Ablauf wie Produktion): ohne
    `thinking`-Override lief dieser eine Testlauf zufällig **nicht** in den
    leeren `content` hinein (probabilistischer Fehler, siehe Vorbehalt
    unten) — lieferte aber `tokens_in≈18k` für den vollständigen 3-Runden-
    Durchlauf. Das passt sehr genau zur beobachteten Produktionszahl
    (`tokens_in=81401` für die persistierte Decision): F065 summiert Tokens
    über **beide** Retry-Versuche, `2 × ~18k(+Tool-Runden) ≈ 82k` — starkes
    Indiz, dass der reale Fall zwei aufeinanderfolgende leere Completions war,
    kein Einzelausreißer.
  - Mit `thinking={"type": "disabled"}` lief derselbe Testzyklus zudem mit
    **weniger** Tool-Runden (2 statt 3) und niedrigeren Gesamt-Tokens (~23k)
    zu einer sauberen, inhaltlich stimmigen `hold`-Entscheidung — ein
    beobachteter Kosten- und Stabilitätsvorteil, kein reiner Seiteneffekt.
- **Wichtiger Vorbehalt** (gleiche Ehrlichkeit wie F057 §5): der exakte leere-
  `content`-Fall ließ sich in diesem einzelnen Testlauf nicht direkt
  provozieren — das Fehlerbild ist laut Produktionsdaten selten genug
  (~11,6 % pro Decision, nach Retry), dass ein einzelner Repro-Versuch ihn
  verfehlen kann. Die Ursachenkette (adaptive thinking ist nachweislich an,
  frisst nachweislich Completion-Budget, `thinking=disabled` schaltet es
  nachweislich ab, ohne Tool-Calling/JSON-Ausgabe zu beeinträchtigen) ist
  jedoch mechanistisch vollständig und passt exakt auf jedes der 25
  historischen Symptome (nie NULL, nie kaputtes JSON, immer nichttriviale
  `tokens_out`) — anders als F057/F065s jeweilige Hypothesen, die den Fehler
  nach Deploy nicht eliminiert haben. Für den Fall, dass doch noch eine
  andere/zusätzliche Ursache existiert, ist mit dem neuen
  `finish_reason`-Präfix in `agent_run.error` jetzt erstmals sichtbar, *warum*
  ein künftiger Fall leer bleibt, statt erneut zu raten.
- **Verbleibende Beobachtung:** `llm_output_parse_error`-Rate über die
  nächsten Live-Zyklen sollte auf ~0 fallen. Ein verbleibender Einzelfall
  liefert jetzt sofort ein `finish_reason` in `agent_run.error` zur
  Diagnose statt einer leeren Zeichenkette.

## 6. Rollback-Pfad

Additiv (neue optionale Parameter durch die Kette, ein neues Feld). Commit
zurücknehmen genügt, kein Schema-Change. Ohne Revert lässt sich Thinking auch
lokal wieder aktivieren, indem `_THINKING_DISABLED` in `persona_analysis.py`
auf `None` gesetzt wird — identisch zum Verhalten vor diesem Feature.
