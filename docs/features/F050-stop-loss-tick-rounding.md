# F050 — Stop-Loss-Preise auf Alpacas Tick-Größe runden

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Live-Fund direkt nach dem F049-Deploy (Sonderlauf, Ralfs Anweisung): der
Telegram-Button-Callback funktioniert jetzt, zwei `buy`-Decisions wurden über
Telegram freigegeben (CHARTIST/AAPL, VULTURE/ALDX) — aber `execute_decision`
scheiterte für **beide** an Alpaca mit `422 {"code":42210000,"message":"invalid
stop_loss.stop_price ... sub-penny increment does not fulfill minimum pricing
criteria"}`. `agent_run` (`agent="trading"`, `status=FAILED`) hat das korrekt
festgehalten — kein stiller Fehler, aber die Order kam nie an. Root Cause:
`compute_stop_loss_price` (`src/orchestrator/decision_sizing.py`) gibt den
rohen ATR-/Fixed-Prozentsatz-Float zurück (z. B. `290.8672`), ohne ihn auf
Alpacas Preisraster zu runden. Alpaca verlangt bei Preisen ≥ 1 USD
Cent-Schritte, unter 1 USD sind 0,0001-USD-Schritte erlaubt.

**Vermutlich der eigentliche Grund, warum noch nie eine Kauforder durchkam:**
Jede `buy`-Decision, die Risk-Gate + (falls aktiv) HITL passiert, endet in
`_maybe_execute_decision` → `execute_decision` → `place_order()` mit genau
diesem unrundierten Stop — der Fehler war unabhängig vom F049-Bug bereits
vorher da, nur nie sichtbar, weil vorher gar keine Freigabe den Ausführungscode
erreichte (F049 fehlte der Listener, davor lief HITL laut F022 nur einmalig
manuell).

**Zweiter, unabhängiger Fund beim Nachprüfen (gleiche Session):** die beiden
gescheiterten Decisions (AAPL `a1f3ab40…`, ALDX `0da0230f…`) blieben nach dem
Broker-Fehler dauerhaft auf `status=APPROVED` stehen — F023s eigene
Doku-Aussage ("sie wird beim nächsten Lauf erneut versucht") stimmt nicht:
`_find_hitl_decision`s Idempotenz-Replay in `persona_analysis.py` ist auf
`cycle_id` skopiert, ein neuer Zyklus hat eine neue `cycle_id` und findet die
Alt-Decision nie wieder. Ohne einen zweiten Fix wären diese zwei echten,
von Ralf per Telegram freigegebenen Kauf-Decisions für immer verwaist
geblieben. Scope daher um zwei Punkte erweitert: (a) `execute_decision`
rundet den Stop defensiv nochmal direkt vor dem Broker-Aufruf (deckt auch
bereits-persistierte Alt-Decisions mit dem unrundierten Wert ab), (b) ein
neuer periodischer Sweep (`retry_stuck_decisions`, analog zu F030s
HITL-Timeout-Sweep) versucht jede `APPROVED`-Decision ohne `order_record`
erneut — unabhängig davon, aus welchem Zyklus sie stammt.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #4 Pflicht-Stop-Loss als GTC-Order | nein (verstärkt sie) | Ohne diesen Fix wird gar keine Order (und damit auch kein Stop) platziert — der Fix macht den Pflicht-Stop überhaupt erst erreichbar, ändert nichts an der Pflicht selbst. |
| #1 Risk-Gate ist deterministischer Code | nein | Rundung passiert nach der Risk-Gate-Prüfung, rein für die Broker-Preisdarstellung — die Risk-Gate-Entscheidung selbst (Prozentsätze, Guardrails) bleibt unverändert auf dem ungerundeten Wert, nur der an Alpaca übergebene Preis wird gerundet. |
| Fehlerbehandlung kein stiller Fallback | nein | Unverändert: `_maybe_execute_decision`s try/except (F023) bleibt bestehen — bei jedem anderen Broker-Fehler bleibt die Decision weiterhin `APPROVED` mit `agent_run(status=FAILED)`, kein Verhaltensunterschied. |
| #2 Privilege Separation | nein | `retry_stuck_decisions` ruft exakt denselben `execute_decision` mit exakt derselben `status==APPROVED`-Prüfung auf, kein neuer/loserer Ausführungspfad — nur ein zusätzlicher *Aufrufer* an derselben Stelle. |
| #3 Keine Order ohne persistierte Decision | nein | Der Sweep liest ausschließlich bereits persistierte, bereits `APPROVED`e Decisions aus der DB — nichts Neues wird erzeugt. |
| Doppel-Ausführung derselben Decision | ja | `place_order`s `client_order_id=decision_id` (F027) macht wiederholte `execute_decision`-Aufrufe für dieselbe Decision broker-seitig idempotent — der Sweep kann dieselbe verwaiste Decision über mehrere Läufe hinweg unbedenklich erneut versuchen, bis sie entweder ausgeführt wird oder dauerhaft fehlschlägt (z. B. delistetes Symbol; kein Backoff/Limit — läuft alle 15 Min neu an, non-fatal wie der HITL-Sweep). |

**Kosten:** keine. **Fairness:** betrifft alle 6 Personas gleich (gemeinsame
Sizing-Funktion, kein Persona-spezifischer Pfad, Sweep iteriert über alle
Portfolios gleich).

## 3. Testdefinition

`tests/orchestrator/test_decision_sizing.py`: neuer Test rundet einen
ATR-Stop mit Entry ≥ 1 USD auf 2 Dezimalstellen (reproduziert den echten
AAPL-Fall, 296.78/ATR14 2.9565 → vorher 290.8672); zweiter Test stellt sicher,
dass Sub-Penny-Präzision unter 1 USD (Penny-Stocks wie ALDX) auf 4
Dezimalstellen erhalten bleibt statt auf Cent gerundet zu werden (würde die
beabsichtigte Stop-Distanz verzerren).

`tests/orchestrator/test_stuck_decision_sweep.py` (neu, `integration`, Muster
wie `test_hitl_sweep.py`): (1) eine verwaiste `APPROVED`-Decision mit einem
stale unrundierten Stop wird ausgeführt, der Broker bekommt den gerundeten
Wert; (2) eine Decision mit bereits existierendem `order_record` wird
übersprungen (kein zweiter Broker-Aufruf); (3) bei anhaltendem Broker-Fehler
bleibt die Decision `APPROVED`, kein `order_record`, kein Crash.

## 4. Implementierung

- `src/orchestrator/decision_sizing.py`: `_round_to_tick()` → public
  `round_to_tick()`, angewendet auf beide Rückgabepfade von
  `compute_stop_loss_price` (FIXED- und ATR-Policy).
- `src/orchestrator/trading.py`: `execute_decision` rundet den aus
  `expected_outcome` gelesenen Stop defensiv nochmal über `round_to_tick()`
  direkt vor `place_order()` — deckt Alt-Decisions ab, die vor diesem Fix
  bereits mit einem unrundierten Wert persistiert wurden.
- `src/orchestrator/scheduler.py`: neue `retry_stuck_decisions()` +
  `_retry_stuck_decisions_job` (non-fatal, gleiches Muster wie
  `sweep_expired_hitl_decisions`/`_sweep_expired_hitl_job`), als
  `stuck-decision-retry-sweep`-Job alle 15 Minuten in `build_scheduler`
  registriert.

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_decision_sizing.py
tests/orchestrator/test_stuck_decision_sweep.py -q -m 'not integration or
integration'` → 10 passed (7 Sizing + 3 neue Sweep-Tests). Gesamtsuite:
`uv run pytest -q -m 'not integration'` → 484 passed, 10 deselected; `uv run
pytest -q -m integration` → 8 passed, 2 skipped (unverändert, keine
Regression). `uv run ruff check`/`ruff format --check` → sauber (nach
Auto-Fix des Import-Blocks in `scheduler.py`). `uv run mypy src/orchestrator
src/telegram src/broker` → sauber.

**Live-Verifikation (2026-07-10, direkt nach Deploy):** Rundungsfix deployt,
manueller `run_cycle.py`-Lauf produzierte diesmal keine neue `buy`-Decision
(LLM-Nichtdeterminismus/Marktlage) — der Rundungsfix selbst ist über die
Unit-Tests exakt gegen den echten AAPL-Fall verifiziert. Die beiden echten
verwaisten Decisions (AAPL, ALDX) wurden im Anschluss über den neuen Sweep
(`retry_stuck_decisions`, einmalig manuell angestoßen statt auf den 15-Min-
Timer zu warten) nachgeholt — Ergebnis siehe `docs/deployment.md`.

## 6. Rollback-Pfad

Additiv. Rundung: Commit zurücknehmen genügt, kein Schema-Change. Sweep:
`stuck-decision-retry-sweep`-Job entfernen (oder `scheduler.remove_job(...)`
zur Laufzeit) hält nur das erneute Antriggern an — bereits `APPROVED`e
Alt-Decisions bleiben liegen (kein Datenverlust, gleicher Zustand wie vor
diesem Feature).
