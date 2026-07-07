# F030 — HITL-Timeout-Sweep

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Security-Audit 2026-07-07, Finding P5, dokumentierter Gap seit F022 §1
("Non-Scope: kein automatischer 30-Minuten-Timeout-Sweep"): Eine nie beantwortete
HITL-Anfrage bleibt unbegrenzt `HITL_PENDING` — die Timeout-Logik
(`src/telegram/hitl.py`) greift nur bei einem *tatsächlichen* Button-Klick nach
Ablauf, nicht proaktiv. Kein Sicherheitsrisiko (fail-closed: keine Order ohne
Freigabe), aber ein Verfügbarkeits-Gap — der pausierte Zyklus-Prozess für diese
Persona hängt unbegrenzt.

**Scope:** Periodischer Scheduler-Job, der abgelaufene `HITL_PENDING`-Decisions
per Timeout-Regel auflöst (`decided_by="timeout"` → Reject) und den passenden
LangGraph-Interrupt mit "rejected" resumed.

## 2. Kritische Betrachtung

**Wiederverwendung statt Neuimplementierung:** Die 30-Minuten-Konstante
(`src/telegram/hitl.py::TIMEOUT`), die Expiry-Prüfung (`HitlRequest.is_expired`)
und die DB-Anwendung (`src/telegram/hitl_store.py::apply_hitl_outcome`,
`decision_to_hitl_request`) existieren bereits aus F005/F022 und werden 1:1
wiederverwendet — keine zweite Quelle der Wahrheit für die Timeout-Dauer.

**Resume-Mechanismus identisch zum echten Telegram-Callback:** Derselbe
`Command(resume={interrupt_id: "rejected"})`-Aufruf wie in
`src/telegram/bot.py::_handle_hitl_callback`. Aus Sicht des Orchestrator-Graphen
ist ein Sweep-Timeout nicht von einem manuellen Reject-Klick zu unterscheiden.

**Warum ein eigener Scheduler-Job statt an bestehende Zyklen gekoppelt:** Aktien-
Zyklen laufen nur 4×/Tag — viel gröber als das 30-Minuten-Fenster. Ein separater
`interval`-Trigger (alle 5 Minuten) prüft unabhängig von der Zyklus-Kadenz.

**Warum jede Decision einzeln resumed wird, nicht batch-committed-dann-alle-resumed:**
Ein fehlschlagender `graph.invoke()` für eine Decision (z. B. Checkpointer
kurzzeitig nicht erreichbar) darf die anderen abgelaufenen Decisions nicht
blockieren — DB-Status wird für alle abgelaufenen Decisions in einer Transaktion
gesetzt, aber jeder Resume-Versuch danach läuft unabhängig mit eigenem
try/except (gleiches Muster wie `_run_cycle_job`).

**Fehlender `thread_id`/`interrupt_id` (defensiv, sollte nicht vorkommen):** Die
Decision wird trotzdem korrekt auf `HITL_REJECTED` gesetzt (Datenintegrität hat
Vorrang), nur der Graph-Resume wird übersprungen — besser als der Sweep-Lauf an
einer einzelnen kaputten Zeile scheitert.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_hitl_sweep.py` (marked `integration` — braucht einen
echten, selbst-committenden `session_factory`, siehe Docstring):
1. Eine abgelaufene `HITL_PENDING`-Decision wird auf `HITL_REJECTED` gesetzt und
   der Graph mit `Command(resume={interrupt_id: "rejected"})` resumed.
2. Eine nicht abgelaufene Decision bleibt unverändert, kein Resume-Aufruf.
3. Fehlende `thread_id`/`interrupt_id`: Decision wird trotzdem rejected, aber kein
   Resume-Aufruf (kein Crash).

## 4. Implementierung

`src/orchestrator/scheduler.py`: `sweep_expired_hitl_decisions()`,
`_sweep_expired_hitl_job()` (Fehler-Containment analog `_run_cycle_job`),
neuer `interval`-Job (`hitl-timeout-sweep`, alle 5 Minuten) in `build_scheduler()`.

## 5. Testdurchlauf

`uv run pytest tests/orchestrator -q -m integration` → 5 passed, 73 deselected
(2 bestehend + 3 neu). `uv run pytest tests/orchestrator tests/telegram
tests/test_logging_config.py -q` → 122 passed, 5 deselected (keine Regression).
`uv run mypy src/orchestrator src/telegram` → sauber. `uv run ruff
check`/`ruff format --check` → sauber.

**Kein Live-Test des laufenden Sweeps** — aus denselben Gründen wie F025/F029
(der Scheduler wird nirgends automatisch gestartet; der neue Job ist Teil von
`build_scheduler()` und läuft erst, sobald `scripts/run_scheduler.py` bewusst
gestartet wird).

## 6. Rollback-Pfad

Commit zurücknehmen. Additiv: ein neuer Scheduler-Job, kein Schema-Change, keine
Änderung an bestehenden HITL-Codepfaden (nur Wiederverwendung).
