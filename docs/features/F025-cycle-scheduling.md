# F025 — Zyklen-Scheduling

Status: umgesetzt (Code), **nicht als laufender Prozess gestartet**
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Letztes geplante P4-Feature (`docs/dod/phase-4.md` Punkt 11): `config/cycles.yaml`
(Zyklus-Zeiten aus ARCHITECTURE.md §5.2) + ein APScheduler-Wrapper, der zur
richtigen Zeit (America/New_York für Aktien, UTC für CRYPTOR, Wochenend-Sonderfall)
automatisch einen Zyklus anstößt — inklusive HITL-Interrupt-Auswertung und
Telegram-Benachrichtigung (bisher nur manuell in `scripts/run_cycle.py`).

**Scope:** Config-Laden, Cron-Trigger-Berechnung, ein wiederverwendbarer
`run_one_cycle()`-Baustein (aus `scripts/run_cycle.py` herausgezogen, jetzt
parametrisiert nach `seq`/`market_session` statt hart codiert), ein
`build_scheduler()`, der alle konfigurierten Trigger registriert.

**Bewusst NICHT Teil dieser Umsetzung: den Scheduler tatsächlich als
dauerhaft laufenden Prozess zu starten.** Das würde ab sofort automatisiert,
unbeaufsichtigt echte Zyklen auslösen — inklusive echter LLM-Kosten (F019/F021) und
potenziell echter Order-Platzierung (F023), sobald HITL aus ist oder jemand
freigibt. Das ist ein bewusster Betriebs-Startpunkt, den Ralf explizit auslösen
sollte, nicht ein Nebeneffekt des Feature-Baus. Rollback-Pfad (§6) und
Aktivierungsschritt sind entsprechend getrennt dokumentiert.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Scheduling in Exchange-Zeit, nicht lokal (ARCHITECTURE.md §5.2) | ja | `zoneinfo`/APScheduler-`CronTrigger(timezone=...)` — direkt `America/New_York`/`UTC`, kein manuelles DST-Offset-Rechnen. |
| Einzelne Zyklen abschaltbar (Betriebs-Fallback) | ja | Jeder Aktien-Zyklus-Eintrag hat `active: true/false` — ein inaktiver Eintrag registriert keinen Trigger, kein Deploy nötig (Config-Datei). |
| CRYPTOR Wochenend-Sonderfall | ja | Getrennte `weekday_times`/`weekend_times`-Listen; APScheduler-`CronTrigger` mit `day_of_week` statt eigener Wochentagslogik im Anwendungscode. |
| Kosten-Caps (Invariante 7) | ja (indirekt) | Ändert nichts an F019 — jeder automatisch ausgelöste Zyklus läuft durch dieselbe `guarded_complete`-Bremse wie ein manueller. Der Scheduler selbst fügt keine neue Umgehung hinzu. |
| Keine stillen Annahmen bei Geld-Themen | ja (Kern dieser Entscheidung) | Der Scheduler wird gebaut, getestet, aber **nicht gestartet** — das Starten ist eine bewusste, mit Ralf abzustimmende Aktion (siehe Aktivierung, §6), keine stille Inbetriebnahme am Ende eines Feature-Commits. |

**Design-Entscheidungen:**
- **`run_one_cycle()` aus `scripts/run_cycle.py` extrahiert** nach
  `src/orchestrator/scheduler.py` — vorher hart auf `seq=1`/`us_equity` verdrahtet;
  jetzt nimmt es `seq`/`market_session` als Parameter, `scripts/run_cycle.py` wird zu
  einem dünnen Wrapper, der einen einzelnen Zyklus manuell für heute anstößt (bleibt
  das manuelle Live-Verifikations-Werkzeug aus F016/F021/F022/F023).
- **APScheduler `BackgroundScheduler`** (nicht `BlockingScheduler`) — läuft in einem
  Hintergrund-Thread, damit ein umgebender Prozess (künftig z. B. ein
  `orchestrator`-Service/Docker-Container) weiterlaufen und z. B. auf Signale
  reagieren kann.
- **Ein Job pro konfiguriertem Zeitpunkt**, nicht ein Cron-Ausdruck mit mehreren
  Uhrzeiten — einfacher zu testen (`scheduler.get_jobs()` zeigt jeden Zyklus einzeln),
  einfacher pro Zyklus ab-/anzuschalten.
- **Trigger-Fehler crashen den Scheduler-Thread nicht:** `run_one_cycle` fängt
  Exceptions pro Zyklus-Lauf ab und loggt (druckt) sie — ein einzelner fehlgeschlagener
  Zyklus (z. B. Netzwerkfehler beim Broker) darf nicht den ganzen Scheduler-Prozess
  beenden und damit alle künftigen Zyklen verhindern.

**Kosten:** keine zusätzlichen LLM-Calls durch dieses Feature selbst — sobald der
Scheduler läuft, entstehen die bereits an anderer Stelle gedeckelten Kosten (F019)
automatisch häufiger (bis zu 4×/Tag Aktien + 4×/Tag Crypto). **Fairness:** ein
Scheduler-Mechanismus für alle Zyklen/Personas gleichermaßen.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_cycles_config.py`:
1. `load_cycles_config` liest alle 4 Aktien-Zyklen mit korrekten Zeiten/`active`
   aus `config/cycles.yaml`.
2. Liest `crypto.weekday_times`/`weekend_times` korrekt.
3. Ein Zyklus mit `active: false` (Test-Fixture-Datei) wird beim Scheduler-Aufbau
   nicht registriert (siehe Test 4 unten).

`tests/orchestrator/test_scheduler.py` (Scheduler wird aufgebaut, **nie
`.start()`et** — reine Job-Registrierungs-Prüfung, kein echter Zeit-Trigger):
4. `build_scheduler` registriert genau 4 Aktien-Jobs (bei allen `active: true`) +
   die Crypto-Jobs (4 Werktags- + 2 Wochenend-Zeiten als getrennte
   `day_of_week`-Trigger).
5. Ein deaktivierter Aktien-Zyklus (Test-Config mit einem `active: false`-Eintrag)
   → ein Job weniger.
6. Jeder Aktien-Job-Trigger nutzt die Zeitzone `America/New_York`, jeder
   Crypto-Job `UTC` (Trigger-Introspektion, kein echtes Warten/Feuern).

## 4. Implementierung

`config/cycles.yaml`, `src/orchestrator/cycles_config.py` (`load_cycles_config`),
`src/orchestrator/scheduler.py` (`run_one_cycle`, `build_scheduler`),
`scripts/run_cycle.py` (refaktoriert zu einem dünnen Wrapper um `run_one_cycle`),
`pyproject.toml` (`apscheduler`-Dependency).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_cycles_config.py
tests/orchestrator/test_scheduler.py -q` → 5 passed (Job-Registrierung geprüft,
Scheduler nie `.start()`et). `uv run pytest tests/orchestrator -q -m
'not integration'` → 65 passed. `uv run pytest tests/orchestrator/test_graph.py -q
-m integration` → 2 passed (unverändert, `scripts/run_cycle.py`-Refactoring hat
keine Laufzeitlogik geändert, nur `run_one_cycle` nach `scheduler.py` extrahiert).
`uv run pytest -q -m 'not integration'` (Gesamtsuite) → 342 passed, 4 deselected.
`uv run ruff check`/`ruff format --check` → sauber. `uv run mypy src/orchestrator
src/llm src/personas src/risk src/broker src/db src/telegram` → sauber (inkl.
`apscheduler`-mypy-Override für fehlende Type-Stubs, `pyproject.toml`).

**Kein Live-Test des laufenden Schedulers** — das wäre exakt die in §1 beschriebene
bewusste Grenze (automatisierter, wiederkehrender Betrieb). `scripts/run_cycle.py`
(jetzt ein dünner Wrapper um `run_one_cycle`) bleibt der bereits mehrfach live
verifizierte manuelle Pfad (F016/F021/F022/F023/F024) — die Umstellung ist ein reiner
Code-Move ohne Logikänderung.

## 6. Rollback-Pfad / Aktivierung

**Rollback:** Commit zurücknehmen — `scripts/run_cycle.py` fällt auf seine vorherige,
in sich geschlossene Fassung zurück (kein Verlust der manuellen Live-Test-Fähigkeit).

**Aktivierung (bewusst getrennt, nicht Teil dieses Commits):** ein
`scripts/run_scheduler.py`-Einstiegspunkt existiert (`build_scheduler(...).start()`
+ Prozess am Leben halten), wird aber **erst auf Ralfs ausdrücklichen Wunsch**
tatsächlich als Dauerprozess (z. B. eigener Docker-Service) deployt — analog zur
Live-Order-Bestätigung in F023.
