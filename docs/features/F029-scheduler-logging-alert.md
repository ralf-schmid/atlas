# F029 — Strukturiertes Logging + Scheduler-Fehler-Alert

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Security-Audit 2026-07-07, Finding P4: CLAUDE.md fordert JSON-Logging mit
`cycle_id`/`portfolio_id`-Korrelation; Ist-Zustand war `print()` in
`_run_cycle_job` (`src/orchestrator/scheduler.py`) — ein fehlgeschlagener Zyklus
erzeugt keinen Telegram-Alert und ist nur auf stdout sichtbar.

**Scope:** JSON-Logging-Grundgerüst + `print()` ersetzen; Telegram-Alert bei
Zyklus-Fehlschlag, 2×-Fail-Eskalation analog zum Container-Health-Alert.

## 2. Kritische Betrachtung

**Warum Stdlib `logging` + eigener JSON-Formatter statt `structlog`:** CLAUDE.md
verlangt nur "strukturiert (JSON)", keine bestimmte Bibliothek. Kein neuer
Dependency-Eintrag nötig; ein `logging.Formatter`, der ein JSON-Objekt statt
Klartext ausgibt, genügt.

**Warum In-Memory-Zähler statt DB-Persistenz für den 2×-Fail-Streak:** Der
Scheduler-Prozess ist ein langlebiger Singleton (`scripts/run_scheduler.py`,
noch nicht dauerhaft gestartet — F025 §6). Ein Prozess-Neustart setzt den Zähler
zurück; das verzögert im schlimmsten Fall den nächsten Alert um einen zusätzlichen
Fehlschlag — akzeptabel gegenüber der Komplexität einer DB-Tabelle nur für diesen
Zähler.

**Warum der Zähler nach dem Alert zurückgesetzt wird:** Ohne Reset würde jeder
weitere Fehlschlag ab dem zweiten erneut alarmieren (Spam). Mit Reset alarmiert es
alle 2 aufeinanderfolgenden Fehlschläge erneut — analog zum
Container-Health-Alert-Muster (CLAUDE.md: "2× Fail → Telegram").

**Warum der Telegram-Versand in ein eigenes try/except gekapselt ist:** Ein
Telegram-Ausfall darf den Scheduler-Thread genauso wenig zum Absturz bringen wie
ein fehlgeschlagener Zyklus selbst (F025 §2-Prinzip).

**Test-Overhead entdeckt und dokumentiert (kein Bug in diesem Feature, aber
relevant für zukünftige Logging-Tests in diesem Repo):** Der session-scoped
`_migrated_schema`-Fixture (autouse in `tests/orchestrator/`) ruft
`alembic.command.upgrade` auf, was intern `logging.config.fileConfig` aus
`alembic.ini` lädt — mit dessen Default `disable_existing_loggers=True` werden
dadurch alle zu diesem Zeitpunkt bereits existierenden Logger (u. a.
`src.orchestrator.scheduler`) `.disabled = True` gesetzt. `caplog` allein reicht in
diesem Verzeichnis deshalb nicht zum Testen von Log-Aufrufen; die Tests hier spionieren
stattdessen direkt `logger.error` an (siehe §3).

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_scheduler.py`:
1. Ein fehlschlagender Zyklus ruft `logger.error("cycle failed", extra={seq,
   market_session, trading_day}, exc_info=True)` auf.
2. Ein einzelner Fehlschlag löst noch keinen Telegram-Alert aus.
3. Der zweite aufeinanderfolgende Fehlschlag (gleicher Job) löst genau einen Alert
   aus, mit "2x in Folge" im Text.
4. Ein erfolgreicher Lauf setzt den Fail-Streak-Zähler zurück.

`tests/test_logging_config.py`:
5. `JsonFormatter` produziert valides JSON mit `level`/`logger`/`message` +
   vorhandenen Korrelationsfeldern.
6. Fehlende Korrelationsfelder (z. B. kein `cycle_id`) tauchen nicht im Payload auf.

## 4. Implementierung

`src/logging_config.py` (`JsonFormatter`, `configure_logging`),
`src/orchestrator/scheduler.py` (`logger`, `_consecutive_failures`,
`_send_cycle_failure_alert`), `scripts/run_scheduler.py`
(`configure_logging()` beim Start).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator tests/test_logging_config.py -q` → 75 passed,
2 deselected (keine Regression ggü. vorher). `uv run mypy src/orchestrator/scheduler.py
src/logging_config.py scripts/run_scheduler.py` → sauber. `uv run ruff
check`/`ruff format --check` → sauber.

**Kein Live-Test des laufenden Schedulers** — aus denselben Gründen wie F025 §5
(der Scheduler wird nirgends automatisch gestartet).

## 6. Rollback-Pfad

Commit zurücknehmen. Additiv: kein Schema-Change. `configure_logging()` wird nur
im (noch nicht aktivierten) `run_scheduler.py`-Entrypoint aufgerufen — kein
Einfluss auf andere Skripte/Tests.
