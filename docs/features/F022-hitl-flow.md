# F022 — HITL-Flow (Telegram-Approval via LangGraph-Interrupt)

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Schließt eine echte Sicherheitslücke in F021: risk-approved `buy`-Decisions wurden
direkt auf `status=APPROVED` gesetzt — ohne HITL, obwohl ARCHITECTURE.md §5.3 für die
aktuelle Phase ("Einschwingphase", vor Wettbewerbsstart) **HITL an** für Paper
vorschreibt. Dieses Feature verdrahtet den in F005 (Phase 2) bereits gebauten
Telegram-Approval-Mechanismus (`hitl.py`/`hitl_store.py`/`bot.py`) endlich mit dem
echten LangGraph-Orchestrator, über `interrupt()`/`Command(resume=...)` — exakt der
in ARCHITECTURE.md §5.3 spezifizierte Mechanismus ("Callback resumed den
LangGraph-Interrupt").

**Scope:** `config/hitl.yaml` (Schaltung je `mode`), risk-approved `buy` pausiert den
Zyklus-Lauf für genau diese Persona per `interrupt()` (andere Personas laufen
unbeeinflusst weiter — experimentell verifiziert, siehe §2), ein Telegram-Callback
resumed genau diesen einen Interrupt über die echte Interrupt-ID.

**Non-Scope (bewusst, dokumentierter Gap):** **kein automatischer 30-Minuten-Timeout-
Sweep.** Die Timeout-Logik (`HitlRequest.is_expired`, `TIMEOUT=30min`) existiert
bereits (F005) und wird bei einem *tatsächlichen* Button-Press nach Ablauf korrekt als
Reject behandelt — aber ohne einen laufenden Scheduler (kommt erst mit dem letzten
P4-Feature, "Zyklen-Scheduling") gibt es niemanden, der eine **nie beantwortete**
Anfrage proaktiv nach 30 Minuten reject. Der Zyklus-Prozess pausiert in diesem Fall
einfach unbegrenzt (durable im Postgres-Checkpointer, kein Datenverlust) bis entweder
ein Button-Press oder ein manueller Sweep-Aufruf kommt. Dokumentiert statt verschwiegen
— siehe Rollback-/Restrisiko unten.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #5 Paper/Live-Trennung, HITL gemäß Phasenlogik | ja (Kern) | `config/hitl.yaml` schaltet HITL je `mode` — aktuell `paper: true` (Einschwingphase, ARCHITECTURE.md §5.3 Zeile 1), `live: true` (Live existiert ohnehin noch nicht). Die Schaltung ist Config, kein Code-Pfad umgeht sie. |
| Timeout = Reject, keine Umgehung | teilweise | Die Prüf-Logik selbst bleibt unverändert und unumgehbar (F005). Der **fehlende proaktive Sweep** ist ein Verfügbarkeits-Gap, kein Sicherheits-Gap: ein unbeantworteter Vorschlag bleibt `HITL_PENDING` (keine Order, keine Freigabe) — "fail closed", nicht "fail open". Explizit im Non-Scope dokumentiert statt still gelassen. |
| Nebenläufigkeit (F016 §2) | ja | Experimentell verifiziert (siehe unten): ein `interrupt()` in einem `Send`-Branch pausiert **nur diesen Branch** — die anderen 5 Personas laufen unbeeinflusst weiter und ihre Decisions werden trotzdem committet. Kein Persona blockiert eine andere. |
| Kein doppelter LLM-Call beim Resume | ja | LangGraph re-executed bei einem Resume die **gesamte** Knoten-Funktion von vorne (offiziell dokumentiertes Verhalten). Ohne Gegenmaßnahme würde ein Redo den LLM-Call erneut auslösen (doppelte Kosten). Lösung: `analyze_persona_cycle` prüft **zuerst**, ob für `(cycle_id, portfolio_id)` bereits eine `HITL_PENDING`-Decision in der DB existiert (aus einem vorherigen, unterbrochenen Durchlauf) — falls ja, wird direkt zum `interrupt()`-Aufruf gesprungen, kein erneuter LLM-Call. |
| Durability über Prozessgrenzen | ja | Die `HITL_PENDING`-Decision wird **vor** dem `interrupt()`-Aufruf committet (nicht erst danach) — sonst würde ein `session.close()` beim Exception-Bubbling die Änderung verwerfen. Damit ist der Zustand sichtbar/wiederherstellbar, selbst wenn der Python-Prozess zwischen Pause und Resume neu startet (Postgres-Checkpointer, bereits aus F016). |
| #2 Privilege Separation | ja | `interrupt()`/Resume berühren ausschließlich `decision.status` — kein Order-Tool, keine Broker-Interaktion in diesem Feature. |

**Design-Entscheidungen (inkl. experimenteller Befunde zu LangGraph):**
- **Ein `interrupt()`-Aufruf in derselben Knoten-Funktion** (`_resolve_buy_decision`),
  nicht ein separater Graph-Knoten — ein zweiter Knoten hätte erfordert, dass
  branch-lokale Daten (z. B. `decision_id`) über einen geteilten Graph-State-Kanal
  von Knoten zu Knoten wandern; das kollidiert bei parallelem `Send` ohne
  `Annotated`-Reducer (experimentell reproduziert: `InvalidUpdateError`). Die
  Idempotenz-Prüfung über die DB (siehe oben) löst das Replay-Problem sauber, ohne
  Graph-State-Gymnastik.
- **Resume-Ziel-Adressierung über die echte Interrupt-ID:** `graph.invoke()` liefert
  bei einem Interrupt `result["__interrupt__"]` mit je einer eindeutigen `Interrupt.id`
  — experimentell verifiziert, dass `Command(resume={interrupt_id: wert})` **gezielt
  genau einen** von mehreren gleichzeitig offenen Interrupts (mehrere Personas wollen
  im selben Zyklus kaufen) auflöst, ohne die anderen zu berühren. `thread_id` +
  `interrupt_id` werden in `decision.hitl` gespeichert, damit der Telegram-Callback
  (der Stunden später, in einem komplett anderen Prozess laufen kann) weiß, welchen
  Graph-Lauf er resumen muss.
- **`scripts/run_cycle.py` sendet die Telegram-Nachricht**, nicht der Graph-Knoten
  selbst — der Knoten kennt nur die `interrupt()`-Payload; das eigentliche Senden
  passiert nach `graph.invoke()`, wenn `result["__interrupt__"]` ausgewertet wird
  (klare Trennung: Graph entscheidet/pausiert, Skript kommuniziert).

**Kosten:** kein zusätzlicher LLM-Call (siehe Idempotenz-Punkt oben). **Fairness:**
identischer Mechanismus für alle Personas.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_hitl_config.py`:
1. `is_hitl_required(PAPER)` liefert den konfigurierten Wert aus `config/hitl.yaml`.

`tests/orchestrator/test_persona_analysis.py` (Ergänzung):
2. `buy`, Risk-Gate approved, HITL aktiv → `analyze_persona_cycle` wirft
   `GraphInterrupt`; die Decision ist **vor** dem Interrupt bereits als
   `HITL_PENDING` committet (per separater Session sichtbar).
3. Zweiter Aufruf mit bereits existierender `HITL_PENDING`-Decision → **kein**
   erneuter LLM-Call (Mock-Client wirft bei zweitem Aufruf), Funktion springt direkt
   zum `interrupt()`.
4. `buy`, Risk-Gate approved, HITL **aus** (Config) → weiterhin direktes
   `status=APPROVED` wie in F021 (Regressionsschutz).

`tests/orchestrator/test_graph.py` (Ergänzung, `pytest.mark.integration`):
5. Voller Graph-Lauf mit zwei Personas, deren simulierte LLM-Antwort `buy` mit
   Risk-Gate-Freigabe ist: `graph.invoke()` liefert zwei Einträge in
   `__interrupt__`; die **anderen** 4 Personas haben trotzdem normal committete
   Decisions. `Command(resume={interrupt_id: "approved"})` für **eine** der beiden
   löst genau diese auf (`status=APPROVED`), die andere bleibt `HITL_PENDING`.

## 4. Implementierung

`config/hitl.yaml`, `src/orchestrator/hitl_config.py` (`is_hitl_required`),
`src/orchestrator/persona_analysis.py` (Idempotenz-Check + `interrupt()`-Aufruf in
`_resolve_buy_decision`), `scripts/run_cycle.py` (Interrupt-Auswertung +
Telegram-Nachricht + `decision.hitl`-Update mit `thread_id`/`interrupt_id`),
`src/telegram/bot.py` (`_handle_hitl_callback` ruft nach `apply_hitl_outcome`
zusätzlich `graph.invoke(Command(resume=...))` auf, um den echten Zyklus-Lauf
fortzusetzen).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_hitl_config.py -q` → 2 passed.
`uv run pytest tests/orchestrator/test_persona_analysis.py -q` → 10 passed (F021s
Tests + die 3 neuen HITL-Tests: Interrupt+Pending, Resume ohne zweiten LLM-Call,
Regression bei deaktiviertem HITL). `uv run pytest tests/orchestrator -q -m
'not integration'` → 49 passed. `uv run pytest tests/orchestrator -q -m integration`
→ 2 passed — inkl. des neuen Mehrfach-Interrupt-Tests: 6-Personas-Graph-Lauf, 2
gleichzeitige Interrupts (VULTURE+HYPE wollen kaufen), die anderen 4 Personas
committen normal (`RECORDED`); gezieltes Resume der ersten Interrupt-ID →
`APPROVED`, die zweite bleibt `HITL_PENDING`; Resume der zweiten mit "rejected" →
`HITL_REJECTED`. `uv run pytest tests/telegram -q` → 47 passed (unverändert).
`uv run pytest -q -m 'not integration'` (Gesamtsuite) → 327 passed, 4 deselected.
`uv run ruff check`/`ruff format --check` → sauber. `uv run mypy src/orchestrator
src/llm src/personas src/risk src/broker src/db src/telegram` → sauber.

Kein separater Live-Test mit echtem Telegram-Bot in dieser Session — die
Telegram-Sende-/Callback-Mechanik selbst war bereits in F005 live verifiziert
(Testnachricht + Button-Callback), dieses Feature fügt nur die Graph-Resume-Anbindung
hinzu, die über die Integrationstests (echte `interrupt()`/`Command(resume=...)`-
Mechanik) abgedeckt ist.

## 6. Rollback-Pfad

`config/hitl.yaml` auf `paper: false` setzen deaktiviert den Interrupt-Pfad sofort
(Config-Flag, kein Deploy nötig, exakt wie ARCHITECTURE.md §5.3 vorsieht:
`/hitl off`). Vollständiger Code-Rollback = Commit zurücknehmen, fällt zurück auf
F021s direktes `APPROVED` — kein Schema, keine Migration betroffen.
