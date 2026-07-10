# F055 — Persona-Kosten-Cap auch nach dem LLM-Call erneut prüfen

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Fund im Vollständigkeits-Audit (Subagent-Recherche nach F049-F054):
`guarded_complete` (`src/llm/ledger.py`) prüft **vor** dem LLM-Call sowohl das
System- als auch das Persona-Budget, aber **nach** dem Call (dem Moment, in
dem der tatsächliche, ggf. teurere Ist-Preis bekannt ist) nur noch das
System-Budget (`post_call_system_check`). Ein Persona-Post-Call-Check fehlte.
Invariante #7 verlangt "80 % Warnung, 100 % Stopp weiterer LLM-Calls" — ohne
den Recheck kann ein einzelner Call, der eine Persona allein über ihr enges
Tages-Cap (`persona_daily_usd: 1.0`, `config/llm.yaml`) hebt, unbemerkt
bleiben: das System-Cap (5.0 USD, geteilt über alle 6 Personas) reißt dabei
in aller Regel nicht mit — die Persona hätte bis zu ihrem nächsten Call
(wann auch immer der kommt) unkontrolliert weiter Kosten verursachen können.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #7 Kosten-Caps doppelt durchgesetzt | ja, Kern des Fixes | Ergänzt exakt die fehlende Hälfte der bereits vorhandenen Pre-Call-Symmetrie (System + Persona) um die Post-Call-Seite (bisher nur System). Gleiches Muster, gleicher Advisory-Lock, gleiche "Kosten wird trotzdem festgehalten, nur das Signalisieren ändert sich"-Logik wie beim bestehenden System-Recheck. |
| Fehlerbehandlung kein stiller Fallback | ja | Die bereits entstandene Kostenzeile wird weiterhin unverändert geschrieben (Ist-Kosten dürfen nie verloren gehen) — nur das Auslösen von `BudgetExceededError` kommt für die Persona-Ebene neu hinzu. |

**Kosten:** keine (reine Kontrolllogik, kein zusätzlicher LLM-Call).
**Fairness:** identische Prüfung für alle 6 Personas.

## 3. Testdefinition

`tests/llm/test_guarded_complete.py`: neuer Test — ein einzelner Call mit
1,30 USD (über dem 1,0-USD-Persona-Cap, während das 5,0-USD-System-Cap dabei
unberührt bleibt) löst `BudgetExceededError` aus; die Kostenzeile bleibt
trotzdem in `cost_ledger` erhalten (nicht verloren). Bestehende Tests
(pre-call Persona-/System-Block, WARN-Status, Sibling-Race für den
System-Recheck) bleiben unverändert grün.

## 4. Implementierung

`src/llm/ledger.py`: `guarded_complete` berechnet innerhalb desselben,
bereits gehaltenen Advisory-Locks zusätzlich `post_call_persona_check`
(analog zu `post_call_system_check`) und wirft danach `BudgetExceededError`,
falls dieser `BLOCKED` ist.

## 5. Testdurchlauf

`uv run pytest tests/llm -q` → 35 passed (34 bestehende + 1 neuer). `uv run
pytest -q -m 'not integration'` → 488 passed, 10 deselected. `uv run pytest
-q -m integration` → 8 passed, 2 skipped (unverändert). `uv run ruff
check`/`ruff format --check` → sauber. `uv run mypy src/llm` → sauber.

## 6. Rollback-Pfad

Additiv, ein zusätzlicher Recheck in einer bereits bestehenden Lock-Sektion —
Commit zurücknehmen genügt, kein Schema-Change.
