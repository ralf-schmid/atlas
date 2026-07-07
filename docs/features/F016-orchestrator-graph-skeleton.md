# F016 — Orchestrator-Graph-Grundgerüst

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Erster Baustein von P4s "Agenten-Core" (ARCHITECTURE.md §8 P4, §5.1): ein echter
LangGraph-`StateGraph` mit Postgres-Checkpointer, der einen Zyklus anlegt, einen
gemeinsamen Recherche-Schritt durchläuft und per `Send` parallel über alle aktiven
Portfolios fanoutet — die strukturelle Grundlage, auf der die folgenden Features
(Shared-Research-Synthese, Persona-Analyse, Risk-Gate-Anbindung, HITL, Handels-Agent)
aufbauen.

**Scope:** Graph-Konstruktion (Knoten, Kanten, `Send`-Fanout), Postgres-Checkpointer-
Wiring, echte `cycle`-Zeile pro Lauf, ein Platzhalter-Research-Item pro Zyklus (damit
später referenzierte `input_research_ids` real und valide sind), ein Platzhalter-
`agent_run` je Portfolio (belegt, dass der Fanout tatsächlich alle 6 Portfolios
erreicht).

**Non-Scope (bewusst, kommt als eigene Features):** keine echte Recherche-Synthese aus
den Ingestion-Tabellen (F008–F014), keine LLM-Calls, **keine `decision`-Zeilen** — ein
Platzhalter-`reject_idea` bräuchte ein `instrument`-Feld (NOT NULL im Schema), für das
es ohne echte Recherche/Kandidatenliste keinen ehrlichen Wert gibt; das freizuerfinden
wäre eine Fake-Decision in einer Tabelle, die für Lineage/Journal Nachweischarakter hat
— explizit vermieden. Kein Risk-Gate-Aufruf (der bräuchte eine echte Trade-Decision mit
Preis/Größe, siehe oben). Kein HITL, kein Order-Pfad, kein Scheduler (kommt mit
Zyklen-Scheduling, letztes P4-Feature laut `docs/dod/phase-4.md`).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #2 Privilege Separation | ja | Dieser Graph hat keinerlei Order-Tools/Broker-Zugriff — nur DB-Lesen/-Schreiben auf `cycle`, `research_item`, `agent_run`. Der Handels-Agent kommt als eigenes, später abgegrenztes Feature. |
| #3 Keine Order ohne persistierte Decision / `input_research_ids` validiert | ja (indirekt) | Dieses Feature erzeugt noch keine Decisions — die Invariante wird erst ab dem Persona-Analyse-Feature relevant. Das Platzhalter-Research-Item existiert aber bereits *jetzt* real und referenzierbar, damit die erste echte Decision (nächstes Feature) sofort eine valide `input_research_ids`-Referenz hat. |
| #10 Fairness | ja | `_fanout_to_personas` iteriert über *alle* aktiven Portfolios identisch (gleicher Knotencode, gleiche Recherche-Referenz) — keine Persona bekommt einen strukturellen Vorteil. |
| Nebenläufigkeit/Thread-Safety | ja | LangGraphs `Send`-Fanout kann Knoten parallel ausführen (Pregel-Executor) — eine SQLAlchemy-`Session` ist nicht thread-sicher für gleichzeitigen Zugriff. Jeder Knoten öffnet daher seine *eigene* Session über eine `session_factory`-Closure, committet und schließt sie wieder; kein Session-Sharing über Knotengrenzen hinweg. |
| Crash-Recovery (P4-DoD, aber nicht dieses Features Scope) | teilweise | Jeder Knoten committet sein Ergebnis sofort (nicht erst am Zyklusende) — das ist die Grundlage für spätere Resume-Fähigkeit über den Postgres-Checkpointer, aber der eigentliche Crash-Recovery-Test (Container-Kill mitten im Zyklus) ist ein späterer P4-DoD-Punkt, kein Testfall dieses Features. |

**Design-Entscheidungen:**
- **Zwei-Ebenen-Struktur wie F008–F015:** reine, unit-testbare Helper-Funktionen
  (`create_cycle`, `create_bootstrap_research_item`,
  `create_persona_agent_run_placeholder`, `list_active_portfolios` — nehmen eine
  Session direkt entgegen, nur `.flush()`, kein `.commit()`) plus dünne
  LangGraph-Knoten-Closures, die diese Helper mit einer *eigenen*, aus einer
  `session_factory` frisch geöffneten Session aufrufen und committen. Das entkoppelt
  die testbare Logik komplett von LangGraph/Concurrency-Fragen — exakt das Muster,
  das sich bei den Ingestion-Features bewährt hat.
- **`session_factory: Callable[[], Session]`** statt eine einzelne geteilte Session —
  Voraussetzung für sicheren Parallel-Fanout (siehe Tabelle oben).
- **Ein einziges Platzhalter-`research_item` pro Zyklus, nicht pro Persona:** entspricht
  dem Shared-Research-Pool-Prinzip (Invariante 10) — auch als Platzhalter bereits
  strukturell korrekt (eine Quelle für alle).
- **Kein Join-/Finalize-Knoten:** die `persona_placeholder`-Knoten laufen direkt in
  `END`; da sie nichts in den geteilten Graph-State zurückschreiben (nur
  Seiteneffekte in der DB), gibt es keinen Merge-Konflikt, den ein expliziter
  Join-Knoten auflösen müsste.
- **`PostgresSaver`-Checkpointer nur im Live-Skript (`scripts/run_cycle.py`)
  verifiziert**, nicht Teil der Unit-Test-Suite (analog zu den `_live`-Funktionen aus
  F008–F015) — `PostgresSaver.setup()` legt eigene Tabellen an, deren Test-Zyklus
  (aufsetzen/aufräumen) den bestehenden Alembic-Migrationszyklus nicht verkomplizieren
  soll.

**Kosten:** keine LLM-Calls. **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_graph_nodes.py` (Helper-Funktionen, real gegen die lokale
Test-Postgres, `session`-Fixture mit Rollback):
1. `create_cycle` persistiert eine `Cycle`-Zeile mit den übergebenen Feldern.
2. `create_bootstrap_research_item` persistiert ein `ResearchItem` mit
   `agent="orchestrator_bootstrap"`, nicht-leerem `summary`, korrektem `cycle_id`.
3. `create_persona_agent_run_placeholder` persistiert einen `AgentRun` mit korrektem
   `cycle_id`/`portfolio_id`, `agent="persona_analysis_placeholder"`,
   `status=SUCCEEDED`.
4. `list_active_portfolios` liefert nach dem F015-Seed alle 6 Portfolios.
5. `list_active_portfolios` schließt ein Portfolio aus, dessen Persona
   `active=False` gesetzt ist.

`tests/orchestrator/test_graph.py` (compiled graph, `pytest.mark.integration` — siehe
Design-Entscheidungen):
6. `build_and_compile_graph(...).invoke(...)` mit `max_concurrency=1` und einer
   `session_factory`, die auf dieselbe (Test-)DB zeigt, erzeugt: genau 1 `Cycle`,
   genau 1 `ResearchItem`, genau 6 `AgentRun`-Zeilen (eine je zuvor geseedetem
   Portfolio) — belegt, dass der `Send`-Fanout tatsächlich alle Portfolios erreicht.

## 4. Implementierung

`src/orchestrator/graph.py`: `CycleState`, `PersonaTaskState` (TypedDicts),
Helper-Funktionen (s.o.), `build_and_compile_graph(session_factory, checkpointer=None)`.
`scripts/run_cycle.py`: CLI-Wrapper — lädt `.env`, baut den Graph mit
`get_session_factory()` und einem echten `PostgresSaver` (eigene Tabellen via
`.setup()`), ruft `graph.invoke(...)` für den heutigen Handelstag auf.

Neue Dependencies: `langgraph>=1.2.8`, `langgraph-checkpoint-postgres>=3.1.0`
(`pyproject.toml`).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_graph_nodes.py -q` → 5 passed.
`uv run pytest tests/orchestrator/test_graph.py -q -m integration` → 1 passed (echter
`Send`-Fanout über alle 6 nach F015 geseedeten Portfolios, genau 1 `Cycle`, 1
`ResearchItem`, 6 `AgentRun`-Zeilen). `uv run pytest -q -m 'not integration'`
(Gesamtsuite) → 263 passed, 3 deselected. `uv run ruff check`/`ruff format --check` →
sauber. `uv run mypy src/orchestrator` → sauber.

**Live-Verifikation (2026-07-07):** `uv run python scripts/run_cycle.py` gegen die
lokale Postgres-Instanz mit echtem `PostgresSaver` ausgeführt (nach Fix: psycopg
versteht das SQLAlchemy-`+psycopg`-Dialekt-Präfix in `DATABASE_URL` nicht, daher
Konvertierung zu einer reinen `postgresql://`-Conninfo vor `from_conn_string`).
Ergebnis: 1 `cycle`, 1 `research_item` (`agent="orchestrator_bootstrap"`), 6
`agent_run`-Zeilen (`agent="persona_analysis_placeholder"`, je eine pro Persona) —
sowie 7 echte Zeilen in `PostgresSaver`s eigener `checkpoints`-Tabelle (ein Checkpoint
je Superstep), belegt per direkter SQL-Abfrage. Damit ist sowohl der Fanout über alle
6 echten Portfolios als auch der Postgres-Checkpointer end-to-end live nachgewiesen.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert, keine Schema-Änderung (nutzt
ausschließlich bestehende Tabellen aus F003). Rollback = Commit zurücknehmen +
`uv remove langgraph langgraph-checkpoint-postgres`. `PostgresSaver`s eigene Tabellen
(falls über `scripts/run_cycle.py` einmal angelegt) können bei Bedarf manuell
gelöscht werden — sie referenzieren keine ATLAS-Tabellen per Fremdschlüssel.
