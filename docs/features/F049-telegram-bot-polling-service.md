# F049 — Telegram-Bot als laufender Dienst (Polling-Aktivierung)

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Live-Vorfall 2026-07-10: vier risk-approved `buy`-Decisions gingen in HITL, die
Freigabe-Nachrichten kamen auf Telegram an — aber kein Klick auf ✅/❌ hatte
irgendeinen Effekt. Ursache: `docker-compose.yml` startet `postgres`, `litellm`,
`api`, `web`, `scheduler` — aber **nirgends** einen Prozess, der
`Application.run_polling()` aus `src/telegram/bot.py` aufruft. Der Scheduler
sendet Freigabe-Anfragen nur einseitig (`send_hitl_approval_request` →
`Bot.send_message`, `src/telegram/alerts.py`); der `CallbackQueryHandler`, der
Button-Klicks verarbeitet (`_handle_hitl_callback`), existierte nur als
getesteter, aber nie deployter Code (F005 §5: einmaliger manueller Live-Test
am 2026-07-05, danach nie in einen Dauerbetrieb-Service überführt).

**Kein Datenfehler, kein Sicherheitsvorfall:** die vier Decisions blieben
korrekt `HITL_PENDING` und wurden vom Timeout-Sweep (F030, läuft alle 5 Min im
`scheduler`-Prozess) nach 30 Minuten automatisch `rejected` — fail-closed wie
vorgesehen. Der Vorfall ist ein Verfügbarkeits-Gap (verpasste Kaufgelegenheiten),
kein Risk-Gate-Problem.

**Scope:** neues `scripts/run_telegram_bot.py` (baut denselben kompilierten
Graphen wie `run_scheduler.py`, gegen denselben Postgres-Checkpointer, dann
`app.run_polling()`), neuer `telegram-bot`-Service in `docker-compose.yml`.
**Nicht Scope:** Änderungen an `hitl.py`/`hitl_store.py`/`bot.py` selbst — die
Callback-/Timeout-/Persistenz-Logik ist seit F005/F022/F030 fertig und getestet,
hier fehlte ausschließlich die Deployment-Verdrahtung.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #5 HITL gemäß Phasenlogik | ja (schließt Lücke) | Der Interrupt-Pfad selbst war korrekt (fail-closed); jetzt kommt zusätzlich die Freigabe-Möglichkeit tatsächlich an. Keine Änderung der Schaltlogik (`config/hitl.yaml` bleibt unverändert). |
| Timeout = Reject, keine Umgehung | nein | Unverändert; der neue Service macht approve/reject nur wieder *erreichbar*, ändert nichts an der Timeout-Regel selbst. |
| #2 Privilege Separation | nein | Der neue Prozess führt keinen zusätzlichen Code-Pfad aus — er startet exakt dieselbe `build_application()`/`_handle_hitl_callback`-Logik, die schon unit-getestet ist. |
| Getrennte Prozess-Lebenszyklen (wie F032 für `scheduler`) | ja | Eigener Service statt Mitnutzung von `api`/`scheduler`: ein API-Deploy darf den Telegram-Callback-Listener nicht unterbrechen (sonst wieder unbeantwortbare Buttons während eines Deploys), und ein Bot-Neustart (z. B. Token-Rotation) darf laufende Zyklen nicht anfassen. |
| Zwei Prozesse resumen potenziell denselben Graph-Thread | ja | `telegram-bot` (Button-Resume) und `scheduler` (Timeout-Sweep-Resume, F030) rufen beide `Command(resume=...)` auf demselben `thread_id` auf — aber nur, wenn die jeweilige Decision noch `HITL_PENDING` ist (beide prüfen das vor dem Resume: `load_pending_decision` bzw. `is_expired`). Ein Button-Klick nach Ablauf der 30 Minuten trifft in `process_callback` ohnehin auf die Timeout-Prüfung und liefert `rejected`, egal wer zuerst war — kein Doppel-Resume möglich, weil `decision.status` nach dem ersten Resume nicht mehr `HITL_PENDING` ist. |
| Kosten | keine zusätzlichen LLM-Calls | Der Bot-Prozess selbst ruft kein LLM auf; ein Resume re-executed `analyze_persona_cycle`, aber die Idempotenz-Prüfung (F022 §2) verhindert einen erneuten LLM-Call. |

**Design-Entscheidung:** `run_telegram_bot.py` baut denselben Graphen wie
`run_scheduler.py` (nicht nur `bot.py` ohne Graph) — sonst könnte der Prozess
zwar Nachrichten empfangen/aktualisieren, aber keinen echten
`Command(resume=...)`-Aufruf gegen den pausierten Orchestrator-Lauf machen
(genau der in F022 §2 vorgesehene Fall: "der Telegram-Callback […] kann Stunden
später in einem komplett anderen Prozess laufen").

## 3. Testdefinition (vor Umsetzung)

Kein neuer Logik-Testbedarf — `build_application`, `_handle_hitl_callback`,
`hitl.py`, `hitl_store.py` sind seit F005/F022 vollständig unit-getestet; dieses
Feature ist reine Deployment-Verdrahtung (gleiche Einordnung wie F032 §3).
Verifikation:

1. `docker-compose.yml` bleibt strukturell gültig (`yaml.safe_load`).
2. `scripts/run_telegram_bot.py` importiert und baut ohne echte Credentials bis
   zum `PostgresSaver`-Kontext durch (gleiche Prüfung wie bei `run_scheduler.py`/
   `run_cycle.py` — kein dedizierter Test, da beide Referenzskripte ebenfalls
   ungetestet sind: dünne Wiring-Skripte, nicht die eigentliche Logik).
3. Live-Verifikation nach Deploy auf der UGREEN (durch Ralf): Testnachricht mit
   Button senden (z. B. nächste reale HITL-Anfrage oder manueller Testaufruf),
   Klick auf ✅ oder ❌ muss die Nachricht aktualisieren und `decision.status`
   in der DB ändern.

## 4. Implementierung

`scripts/run_telegram_bot.py` (neu), `docker-compose.yml` (neuer
`telegram-bot`-Service, Umgebungsvariablen identisch zu `scheduler` plus
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, die `api`/`scheduler` bereits nutzen).

## 5. Testdurchlauf

`uv run ruff check scripts/run_telegram_bot.py`/`ruff format --check` → sauber.
`uv run mypy src/telegram src/orchestrator` → sauber (keine Quelländerung in
`src/`, nur ein neues Skript nach demselben Muster wie `run_scheduler.py`).
`python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` → lädt
ohne Fehler. Vollständige Suite (`uv run pytest -q -m 'not integration'`)
unverändert, da keine bestehende Datei in `src/`/`tests/` angefasst wurde.

**Kein lokaler Container-Start** (gleiche Begründung wie F032 §5: ein lokaler
Start mit echten Credentials würde einen zweiten, parallel laufenden
Callback-Listener gegen die echte Telegram-Chat-ID starten). Verifikation
erfolgt auf der Box nach `git pull` + `docker compose up -d --build
telegram-bot`.

## 6. Rollback-Pfad

**Sofort:** `sudo docker compose stop telegram-bot` auf der Box — hält nur den
Polling-Prozess an, alle anderen Services (inkl. `scheduler`, der weiterhin
Freigabe-Nachrichten sendet und den 30-Min-Timeout-Sweep fährt) laufen
unverändert weiter; Verhalten fällt zurück auf den Vorfall-Zustand
(fail-closed, Buttons ohne Wirkung, Timeout greift). Für einen vollständigen
Rückbau: `sudo docker compose rm -f telegram-bot` + Commit zurücknehmen (kein
Schema-Change, keine Migration betroffen).
