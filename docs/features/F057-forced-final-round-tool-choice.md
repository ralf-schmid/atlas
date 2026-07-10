# F057 — Forcierte Abschlussrunde: `tool_choice=none` statt `tools` weglassen

Status: umgesetzt, Live-Bestätigung ausstehend (probabilistisch)
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Ralfs Auftrag: "Einige Agents melden immer noch Fehler in den Daten, prüfe
dies und schau, wie wir das beheben können." DB-Analyse: 17
`buy`/`reject_idea`-Decisions der letzten 3 Tage haben
`rejection_reason=llm_output_parse_error` ("LLM-Antwort konnte nicht als
valides JSON geparst werden") — überproportional häufig bei HYPE (11 von 17).
Der zugehörige `agent_run.error` (die für genau diesen Fall persistierte
Rohantwort, siehe F0xx-Kommentar in `persona_analysis.py`) ist in **jedem**
dieser Fälle die leere Zeichenkette, nicht kaputtes/unvollständiges JSON.
Das LLM (bzw. der LiteLLM-Proxy) liefert also gar keinen Text zurück, statt
einen Parse-Fehler zu produzieren.

**Root Cause (Hypothese, siehe §5 für den Vorbehalt):** `_run_llm_with_tools`
(F045) lässt eine Persona bis zu `_MAX_TOOL_ROUNDS=2` mal
`search_research_pool` aufrufen; die erzwungene Abschlussrunde (Runde 3)
übergab bisher **`tools=None`** — ließ das `tools`-Feld also komplett weg —,
obwohl die Konversationshistorie zu diesem Zeitpunkt bereits
Assistant-`tool_calls`- und `tool`-Antwort-Nachrichten aus den vorherigen
Runden enthält. Dieser Bruch (Historie erwartet Tool-Kontext, aktuelle
Anfrage deklariert kein einziges Tool mehr) ist ein bekanntes
Fehlerbild bei OpenAI-kompatiblen Tool-Calling-APIs und passt zum Befund:
HYPE nutzt laut Charter am ehesten beide Tool-Runden (viel
Empfehlungs-/Symbol-Suche), erreicht die Abschlussrunde also am häufigsten
mit bereits gefüllter Tool-Historie — konsistent mit der beobachteten
Häufigkeitsverteilung (HYPE 11, CONTRA 3, alle anderen ≤ 1).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate ist deterministischer Code | nein | Betrifft nur die LLM-Anfrage-Form, keine Risk-Gate-Logik. |
| Fairness | nein | Gleiche Änderung für alle 6 Personas (gemeinsamer `_run_llm_with_tools`-Pfad), keine persona-spezifische Sonderbehandlung. |
| Kosten | keine Änderung | Gleiche Anzahl LLM-Calls (max. 3 Runden), `tools`-Deklaration im Request-Body ist kostenneutral (kein separater Tool-Aufruf). |

**Design-Entscheidung:** `tools` bleibt auf **allen** drei Runden identisch
deklariert; `tool_choice="none"` (neuer, optionaler Parameter durch
`LiteLLMClient.complete()` → `guarded_complete()` durchgereicht) erzwingt nur
auf der letzten Runde eine reine Text-Antwort, ohne die Tool-Deklaration
selbst zu entfernen — behält die Konversationshistorie konsistent mit jeder
Anfrage.

## 3. Testdefinition

`tests/llm/test_client.py`: `tool_choice` wird ins Request-Body übernommen,
wenn gesetzt; bleibt weg, wenn nicht gesetzt (gleiches Muster wie der
bestehende `tools`-Test). `tests/orchestrator/test_persona_analysis.py`:
bestehender Test `test_tool_use_loop_is_capped_then_forces_a_final_answer`
umgebaut — prüft jetzt, dass alle drei Runden `tools` deklarieren und nur
die letzte zusätzlich `tool_choice="none"` setzt.

## 4. Implementierung

- `src/llm/client.py`: `LiteLLMClient.complete()` bekommt einen optionalen
  `tool_choice: str | None`-Parameter, ins Request-Body übernommen, wenn
  gesetzt.
- `src/llm/ledger.py`: `guarded_complete()` reicht `tool_choice` unverändert
  an `client.complete()` durch.
- `src/orchestrator/persona_analysis.py`: `_run_llm_with_tools` deklariert
  `tools=[SEARCH_RESEARCH_POOL_TOOL]` jetzt auf allen drei Runden; die
  erzwungene letzte Runde (`round_index == _MAX_TOOL_ROUNDS`) setzt
  zusätzlich `tool_choice="none"` statt `tools` wegzulassen.

## 5. Testdurchlauf

`uv run pytest tests/llm tests/orchestrator/test_persona_analysis.py -q` →
62 passed. `uv run pytest -q -m 'not integration'` → 491 passed, 10
deselected. `uv run pytest -q -m integration` → 8 passed, 2 skipped
(unverändert). `uv run ruff check`/`ruff format --check` → sauber. `uv run
mypy src/llm src/orchestrator` → sauber.

**Wichtiger Vorbehalt:** die Root-Cause-Analyse stützt sich ausschließlich
auf gespeicherte Daten (leerer `agent_run.error`, Häufigkeitsverteilung nach
Persona) — die rohe LiteLLM-/Anthropic-Antwort für einen tatsächlichen
Fehlerfall wurde nicht direkt mitgeschnitten (nicht reproduzierbar ohne
gezielten, kostenpflichtigen Live-Testlauf gegen exakt diese
Tool-Historien-Konstellation). Der Fix behebt den plausibelsten und am
wenigsten riskanten Kandidaten (Standard-Empfehlung für dieses Fehlerbild,
keine Verhaltensänderung bei Erfolg). **Endgültige Bestätigung braucht
weitere Beobachtung:** `rejection_reason='llm_output_parse_error'`-Rate über
die nächsten Tage/Zyklen sollte spürbar sinken, insbesondere für HYPE.

## 6. Rollback-Pfad

Additiv (neuer optionaler Parameter, ein geänderter Aufruf) — Commit
zurücknehmen genügt, kein Schema-Change, keine Verhaltensänderung für andere
Aufrufer von `complete()`/`guarded_complete()` (Default `tool_choice=None`).
