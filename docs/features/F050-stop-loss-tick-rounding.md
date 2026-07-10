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

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #4 Pflicht-Stop-Loss als GTC-Order | nein (verstärkt sie) | Ohne diesen Fix wird gar keine Order (und damit auch kein Stop) platziert — der Fix macht den Pflicht-Stop überhaupt erst erreichbar, ändert nichts an der Pflicht selbst. |
| #1 Risk-Gate ist deterministischer Code | nein | Rundung passiert nach der Risk-Gate-Prüfung, rein für die Broker-Preisdarstellung — die Risk-Gate-Entscheidung selbst (Prozentsätze, Guardrails) bleibt unverändert auf dem ungerundeten Wert, nur der an Alpaca übergebene Preis wird gerundet. |
| Fehlerbehandlung kein stiller Fallback | nein | Unverändert: `_maybe_execute_decision`s try/except (F023) bleibt bestehen — bei jedem anderen Broker-Fehler bleibt die Decision weiterhin `APPROVED` mit `agent_run(status=FAILED)`, kein Verhaltensunterschied. |

**Kosten:** keine. **Fairness:** betrifft alle 6 Personas gleich (gemeinsame
Sizing-Funktion, kein Persona-spezifischer Pfad).

## 3. Testdefinition

`tests/orchestrator/test_decision_sizing.py`: neuer Test rundet einen
ATR-Stop mit Entry ≥ 1 USD auf 2 Dezimalstellen (reproduziert den echten
AAPL-Fall, 296.78/ATR14 2.9565 → vorher 290.8672); zweiter Test stellt sicher,
dass Sub-Penny-Präzision unter 1 USD (Penny-Stocks wie ALDX) auf 4
Dezimalstellen erhalten bleibt statt auf Cent gerundet zu werden (würde die
beabsichtigte Stop-Distanz verzerren).

## 4. Implementierung

`src/orchestrator/decision_sizing.py`: neue private `_round_to_tick()`,
angewendet auf beide Rückgabepfade von `compute_stop_loss_price` (FIXED- und
ATR-Policy).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_decision_sizing.py -q` → 7 passed (5
bestehende + 2 neue). `uv run pytest tests/orchestrator tests/risk -q -m 'not
integration'` → 173 passed, 5 deselected (keine Regression). `uv run ruff
check`/`ruff format --check` → sauber. `uv run mypy
src/orchestrator/decision_sizing.py` → sauber.

**Live-Nachverifikation ausstehend:** nächster Sonderlauf nach Deploy sollte
eine `buy`-Decision bis `EXECUTED` mit echtem `order_record` bringen (siehe
`docs/deployment.md`).

## 6. Rollback-Pfad

Additiv, ein einziger neuer Rundungsschritt in einer reinen Funktion — Commit
zurücknehmen genügt, kein Schema-Change.
