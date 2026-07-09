# F045 — Persona-Tool-Use: gezielte Suche im Research-Pool

Status: umgesetzt
Datum: 2026-07-09
Phase: 5

## 1. Zieldefinition

Ralfs Anschlussfrage an F044: "warum wird aktienfinder immer noch nicht ins
research einbezogen? ... parallel sollten die Agenten explizit nach passenden
Anlagen suchen." Diagnose ergab zwei getrennte Ursachen:

1. **Operativ (kein Bug):** `aktienfinder_blog` (F041) erreicht den Pool
   bereits (90 `research_item`-Zeilen), aber nur einmalig je Sync-Zeitpunkt —
   danach fällt der Batch aus dem Zyklus-Fenster. `aktienfinder_snapshot`
   (F043, Kursziel/Stabilität) hatte 0 Zeilen: Zugangsdaten fehlten noch beim
   letzten planmäßigen Lauf. Nach Ralfs Zustimmung manuell nachgeholt — dabei
   zwei bislang unbemerkte Infra-Bugs gefunden und behoben (Playwright-
   Browser-Pfad für den Non-Root-User, Host-Verzeichnis-Rechte für die
   Screenshot-Ablage — siehe separater Commit `59005ae`).
2. **Architektonisch:** `research_synthesis.py` ist bewusst rein
   fensterbasiert (siehe F017/F044) — eine Persona sieht nur, was zufällig ins
   aktuelle Zyklus-Fenster fiel. Ralfs explizite Wahl aus drei vorgeschlagenen
   Varianten (Fenster verbreitern / dedizierter Such-Agent / **Tool-Use für
   Personas selbst**): die Persona bekommt während ihrer eigenen Analyse ein
   Werkzeug, um gezielt im gesamten historischen Research-Pool zu suchen.

**Scope:** ein einziges, generisches Read-only-Tool (`search_research_pool`)
über die bereits existierende `research_item`-Tabelle, uniform für alle 6
Personas. **Non-Scope:** Tools, die neue externe Quellen anzapfen (bleibt bei
"Agenten lesen ausschließlich aus der DB", CLAUDE.md) oder die schreiben
können (Invariante #2).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Agenten lesen nur aus der DB | nein, bestätigt | Das Tool führt ausschließlich eine parametrisierte SQLAlchemy-Query gegen `research_item` aus — keine neue Ingestion, kein Internet-Zugriff aus dem Tool heraus. |
| #2 Privilege Separation | nein | Read-only; keine Order-Fähigkeit, keine Schreib-Operation. persona_analysis bleibt der einzige Ort, der `execute_decision` aufruft — unverändert. |
| #3 Keine Order ohne persistierte Decision / `input_research_ids` validiert | ja, erweitert | Zitierbare IDs waren bisher nur die des aktuellen Zyklus-Fensters (`available_ids`). Tool-Treffer sind **bereits existierende** `research_item`-Zeilen (nicht neu erzeugt) aus früheren Zyklen — `available_ids` wird um ihre echten IDs erweitert, sobald das Tool sie liefert. Die API (`src/api/routes.py`) lädt zitierte Research-Items ohnehin schon per ID ohne Zyklus-Filter — keine Änderung dort nötig, Data-Lineage bleibt vollständig nachvollziehbar. |
| Kein Look-ahead | ja, geprüft | Query filtert `Cycle.started_at <= as_of` (der Zyklus, in dem die suchende Persona gerade arbeitet) — eine Persona kann nie Research aus einem chronologisch späteren Zyklus zitieren. Testfall vorhanden. |
| #10 Fairness | nein | Identisches Tool-Schema für alle 6 Personas, in der generischen Infra-Instruktion (`_TOOL_USAGE_HINT`), nicht im Charter-Text — kein `charter_version`-Bump nötig, kein Informationsvorsprung einer Persona. |
| #9 Untrusted Content | nein | Tool-Ergebnisse sind Daten-Blöcke in der `tool`-Rolle, keine System-Prompt-Injektion; dieselben bereits vorhandenen `research_item`-Inhalte, nur zu einem späteren Zeitpunkt sichtbar gemacht. |
| #7 Kosten-Caps | ja, Kostenrisiko | Tool-Use bedeutet Mehrfach-Turns: bis zu 3 LLM-Calls statt 1 pro Persona pro Zyklus (`_MAX_TOOL_ROUNDS = 2` Suchrunden + 1 erzwungene Abschlussrunde ohne Tools). Jede Runde läuft einzeln durch `guarded_complete` — der bestehende Budget-Check/`cost_ledger`-Eintrag (Invariante #7) greift pro Runde, nicht nur einmal; ein Budget-Überschreiten mitten in der Schleife bricht sie wie gehabt über `BudgetExceededError` ab. Zusätzlich: Tool-Ergebnisse sind auf 10 Treffer und je 400 Zeichen Textauszug gedeckelt (enger als F044s 600, weil ein Tool-Call mehrere Items auf einmal liefern kann). |

**Design-Entscheidungen:**
- **Ein generisches Tool statt mehrerer typ-spezifischer** (z. B. je ein Tool
  für aktienfinder/EDGAR/Zeitschriften) — weniger Schema-Fläche, die Persona
  filtert stattdessen über `source_types`. Erweiterbar, falls sich das als zu
  grob erweist.
- **`available_ids` wird in-place erweitert, keine neuen `research_item`-Zeilen
  angelegt.** Verworfene Alternative: das Tool materialisiert Treffer als neue
  Zeilen mit `cycle_id` des aktuellen Zyklus. Das hätte bei LangGraphs
  parallelem `Send`-Fanout (mehrere Personas schreiben potenziell gleichzeitig
  in denselben Zyklus) Race-Bedingungen und einen impliziten
  Informations-Austausch zwischen parallel laufenden Personas erzeugt, dessen
  Determinismus schwer zu testen gewesen wäre. Read-only auf bereits
  persistierten Zeilen ist einfacher und race-frei.
- **Forcierte letzte Runde ohne `tools`** statt Vertrauen darauf, dass das
  Modell von selbst aufhört — verhindert eine Endlosschleife rein durch
  Modellverhalten; der Rundenzähler ist Code, keine Prompt-Bitte.

**Kosten:** siehe Tabelle oben — bis zu 3× Cost-Ledger-Einträge je Zyklus/
Persona, weiterhin hart durch die bestehenden Caps begrenzt. Ein
`AgentRun`-Eintrag pro Persona/Zyklus bleibt bestehen (Tokens/Kosten über alle
Runden summiert), passend zum bestehenden Test
`test_every_call_writes_exactly_one_agent_run`.

## 3. Testdefinition (vor Implementierung geschrieben)

- `tests/llm/test_client.py`: `tools`-Parameter wird im Request-Body gesendet
  (bzw. weggelassen, wenn nicht angegeben); `tool_calls` werden aus der
  Response geparst; `content` fällt bei reiner Tool-Call-Antwort auf `""`
  zurück statt `None`.
- `tests/llm/test_guarded_complete.py`: `tools` wird von `guarded_complete`
  zum Client durchgereicht.
- `tests/orchestrator/test_research_search.py` (neues Modul): Filter nach
  Symbol-Overlap, Keyword (ILIKE), Source-Types; kein Look-ahead über
  `as_of` hinaus; aktuelle Zyklus-Items eingeschlossen; Ergebnis auf 10
  gedeckelt; `raw.text_excerpt` auf 400 Zeichen gedeckelt; Serialisierung
  liefert genau die erwarteten Felder.
- `tests/orchestrator/test_persona_analysis.py` (3 neue End-to-End-Tests über
  `analyze_persona_cycle`): ein nur per Tool auffindbares, außerhalb des
  Zyklus-Fensters liegendes `research_item` wird zitierbar und die Decision
  persistiert erfolgreich (statt `invalid_research_ids`); die Tool-Schleife
  ist gedeckelt (2 Tool-Runden + 1 erzwungene finale Runde ohne Tools, exakt 3
  HTTP-Calls, letzter ohne `tools`-Key); genau ein `AgentRun` mit über alle
  Runden summierten Tokens/Kosten.

## 4. Implementierung

- `src/llm/client.py`: neuer `ToolCall`-Dataclass; `LLMResponse.tool_calls`
  (Default `()`); `complete()` nimmt optionalen `tools`-Parameter, parst
  `message.tool_calls` aus der Antwort, `content` fällt auf `""` zurück statt
  `None` bei reiner Tool-Call-Antwort.
- `src/llm/ledger.py`: `guarded_complete` reicht `tools` durch (Signatur von
  `messages: list[dict[str, str]]` auf `list[dict[str, object]]` erweitert —
  Tool-Nachrichten brauchen verschachtelte Werte, nicht nur Strings).
- `src/orchestrator/research_search.py` (neu): `SEARCH_RESEARCH_POOL_TOOL`
  (OpenAI-Function-Calling-Schema, LiteLLM-kompatibel) + `search_research_pool()`
  — parametrisierte Query über `research_item` JOIN `cycle`, Filter
  Symbol-Overlap/Keyword/Source-Types, `Cycle.started_at <= as_of`-Schranke,
  Limit 10, `raw.text_excerpt` auf 400 Zeichen gedeckelt.
- `src/orchestrator/persona_analysis.py`: `_run_llm_with_tools()` ersetzt den
  bisherigen einzelnen `guarded_complete`-Aufruf durch eine auf
  `_MAX_TOOL_ROUNDS = 2` gedeckelte Schleife; `_assistant_tool_call_message`/
  `_execute_tool_call` bauen die Tool-Turn-Nachrichten; `available_ids` wird
  pro Tool-Treffer erweitert; `_TOOL_USAGE_HINT` (generischer Infra-Text, kein
  Charter-Inhalt) erklärt der Persona das Tool im User-Content.
- Kein Alembic-Migrations-Bedarf (keine neue Tabelle/Spalte).

## 5. Test & Rollout

- `uv run pytest` (voller Lauf, `DATABASE_URL` gegen lokalen Test-Postgres):
  472 passed. `ruff check`/`format --check`, `mypy src/` (ganzes Repo, nicht
  nur die geänderten Dateien): clean.
- Deployment: die vier geänderten/neuen Dateien
  (`src/llm/client.py`, `src/llm/ledger.py`,
  `src/orchestrator/persona_analysis.py`,
  `src/orchestrator/research_search.py`) auf `atlas-ugreen`,
  `docker compose build api scheduler` + `up -d`.
- **Rollback-Pfad:** reiner Code-Revert (kein Schema-Change). Ohne Code-Revert
  auch möglich, das Tool "abzuschalten": `_MAX_TOOL_ROUNDS = 0` in
  `persona_analysis.py` erzwingt sofort die tool-lose finale Runde — identisch
  zum Verhalten vor diesem Feature.
