# F019 — Cost-Ledger-Enforcement (Orchestrator-Bremse, Ebene 2)

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

F006 (Phase 2) hat bereits den LiteLLM-Client (`src/llm/client.py`) und die reinen
Cap-Vergleichsfunktionen (`src/llm/cost_guard.py`) gebaut, aber **noch nichts, das
tatsächlich `cost_ledger` liest oder beschreibt** — die zweite, orchestratorseitige
Bremse aus Invariante #7 existierte bis jetzt nur als ungenutzter Baustein. Dieses
Feature schließt die Lücke, **bevor** der Persona-Analyse-Agent (nächstes Feature,
erster echter LLM-Call in Produktion) gebaut wird: kein echter LLM-Call darf
passieren, ohne dass Budget vorher geprüft und danach gebucht wird.

**Scope:** `guarded_complete()` — prüft System- und (falls zutreffend)
Persona-Tagesbudget aus echten `cost_ledger`-Summen, ruft bei OK/WARN den echten
LiteLLM-Client auf, schreibt danach den `cost_ledger`-Eintrag; bei BLOCKED wird der
Call verweigert, **kein** LiteLLM-Aufruf findet statt. **Non-Scope:** kein
Telegram-Alert bei WARN (die aufrufende Stelle bekommt den Status zurück und kann
selbst entscheiden — dieses Feature erfindet noch keinen neuen Alert-Pfad); kein
Reporting-Agent, keine Persona-Analyse selbst (folgt als F020).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #7 Kosten-Caps doppelt durchgesetzt | ja (Kern des Features) | `guarded_complete` ist die zweite, orchestratorseitige Bremse — unabhängig von LiteLLMs eigenem Budget (das bleibt Proxy-seitige Config, siehe F006). System-Cap UND Persona-Cap werden **beide** vor jedem Call geprüft; bei `BLOCKED` wird `client.complete()` **nicht aufgerufen** — kein LLM-Spend nach Cap-Überschreitung. |
| 100%-Cap: bereits platzierte Orders/Stops bleiben unberührt | ja | `guarded_complete` hat keinerlei Broker-/Order-Bezug — kann strukturell nichts stornieren, blockiert ausschließlich neue LLM-Aufrufe. |
| Fairness | ja | Ein Persona-Cap-Check-Pfad für alle Personas identisch; `scope=SYSTEM`/`persona_id=None` für geteilte Rollen (`market_research`/`news_research`/`review`, `shared: true` in `config/llm.yaml`), `scope=PERSONA` + echte `persona_id` für `persona_analysis`/`trading` (`shared: false`) — Zuordnung kommt aus der Rollen-Config, nicht aus Persona-spezifischem Sondercode. |
| Keine stillen Kosten-Annahmen | ja | "Heute" = UTC-Kalendertag (`datetime.now(UTC)`), "dieser Monat" = UTC-Kalendermonat — einheitlich für System-, Persona- und Monats-Cap, unabhängig davon, ob der jeweilige Cycle America/New_York oder UTC (CRYPTOR) fährt. Diese Vereinfachung ist hier dokumentiert statt still angenommen. |

**Design-Entscheidungen:**
- **Scope-Zuordnung aus `RoleConfig.shared`:** `shared: true` → `CostLedgerScope.SYSTEM`,
  `persona_id=None` (geteilte Recherche-Kosten werden nicht einzelnen Personas
  angelastet); `shared: false` → `CostLedgerScope.PERSONA` + die übergebene
  `persona_id` (Pflichtparameter in diesem Fall — `guarded_complete` wirft, wenn eine
  `shared: false`-Rolle ohne `persona_id` aufgerufen wird).
- **System-Cap zählt über alle Scopes** (jede `cost_ledger`-Zeile des Tages,
  unabhängig von `scope`), **Persona-Cap zählt nur Zeilen mit passender
  `persona_id`** — ein geteilter Recherche-Call zählt gegen das System-Budget, aber
  gegen keine einzelne Persona.
- **`BudgetExceededError`** (eigene Exception, trägt den fehlgeschlagenen
  `BudgetCheck`) statt eines stillen `None`-Rückgabewerts — ein geblockter Call soll
  im Aufrufer nicht versehentlich wie ein leeres, aber "erfolgreiches" Ergebnis
  behandelt werden.
- **`GuardedCompletionResult`** trägt `response` + alle drei `BudgetCheck`s (System,
  Persona, Monat) zurück — die aufrufende Stelle (künftig auch der Telegram-Digest)
  kann bei `WARN` reagieren, ohne dass dieses Feature selbst einen Alert-Kanal
  festlegt.
- **Cost-Ledger-Schreiben passiert nach dem LLM-Call, mit denselben Werten, die der
  Client aus der echten Response gelesen hat** (`tokens_in`/`tokens_out`/`cost_usd`)
  — keine erneute Schätzung, ein einziger Wahrheitsquelle-Pfad von LiteLLM bis zur DB.

**Kosten:** dieses Feature selbst verursacht keine LLM-Kosten (reine
Wrapper-/Persistenzlogik, in Tests komplett gemockt). **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

`tests/llm/test_ledger.py` (real gegen lokale Test-Postgres, `session`-Fixture mit
Rollback):
1. `record_llm_call` persistiert eine `cost_ledger`-Zeile mit den übergebenen Werten.
2. `sum_system_spend_today` summiert alle Zeilen von heute (beide Scopes), ignoriert
   Zeilen von gestern.
3. `sum_persona_spend_today` summiert nur Zeilen mit passender `persona_id` von
   heute, ignoriert andere Personas und `scope=SYSTEM`-Zeilen ohne `persona_id`.
4. `sum_month_spend` summiert den ganzen Kalendermonat, ignoriert den Vormonat.

`tests/llm/test_guarded_complete.py` (LiteLLM-Client gemockt, echte Session):
5. OK-Fall: `guarded_complete` ruft `client.complete()` auf, schreibt genau eine
   `cost_ledger`-Zeile mit korrektem `scope`/`persona_id`.
6. Persona-Cap `BLOCKED` (Vorab-Summe bereits über dem Cap) → `BudgetExceededError`,
   `client.complete()` wird **nicht** aufgerufen, keine neue `cost_ledger`-Zeile.
7. System-Cap `BLOCKED` → dieselbe Erwartung.
8. `shared: false`-Rolle ohne `persona_id` → `ValueError` vor jedem Call.
9. `shared: true`-Rolle → `scope=SYSTEM`, `persona_id=None` in der geschriebenen
   Zeile, unabhängig von einem übergebenen `persona_id`-Argument.
10. WARN-Fall (Summe zwischen 80–100 %) → Call findet trotzdem statt,
    `GuardedCompletionResult.system_check.status == WARN`.

## 4. Implementierung

`src/llm/ledger.py`: `record_llm_call`, `sum_system_spend_today`,
`sum_persona_spend_today`, `sum_month_spend`, `BudgetExceededError`,
`GuardedCompletionResult`, `guarded_complete`.

## 5. Testdurchlauf

`uv run pytest tests/llm -q` → 25 passed (10 neue Tests aus diesem Feature + 15
bestehende aus F006, unverändert grün — die drei reinen F006-Testdateien bekamen
bewusst keine DB-Abhängigkeit aufgezwungen, siehe Design-Entscheidungen). `uv run
pytest -q -m 'not integration'` (Gesamtsuite) → 297 passed, 3 deselected. `uv run
ruff check`/`ruff format --check` → sauber. `uv run mypy src/llm` → sauber.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert, kein Schema (nutzt die
bestehende `cost_ledger`-Tabelle aus F003). Rollback = Commit zurücknehmen — noch
nichts ruft `guarded_complete` in Produktion auf (das kommt erst mit F020).
