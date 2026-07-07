# F028 — Budget-Check-Race bei parallelem Send-Fanout

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Security-Audit 2026-07-07, Finding P3: `guarded_complete` (`src/llm/ledger.py`)
prüft Summe → LLM-Call → Insert nicht atomar. Da ein Zyklus bis zu 6 Personas
parallel (`Send`-Fanout) fanoutet, können alle 6 den System-Tages-Cap
(`system_daily_usd`, geteilt über alle Personas) mit einem jeweils veralteten
Zwischenstand passieren, bevor irgendjemand seine Kosten committet hat.

**Scope:** Das Zeitfenster zwischen "Kosten sind bekannt" und "Kosten sind
geprüft+gebucht" atomar machen, ohne den teuren LLM-Call selbst zu serialisieren
(das würde die Parallelität des Fanouts zunichtemachen, für die er existiert).

## 2. Kritische Betrachtung

**Warum kein Lock über den ganzen Ablauf:** Ein Lock, der auch den LLM-Call
(Sekunden Latenz) umschließt, würde alle 6 Personas-Calls faktisch sequentialisieren
— das widerspricht dem Zweck des `Send`-Fanouts und würde die Zykluslaufzeit
vervielfachen.

**Warum kein `SELECT ... FOR UPDATE`:** `check_system_budget` prüft eine
`SUM(cost_usd)`-Aggregation über viele Zeilen, keinen einzelnen Datensatz — es gibt
keinen natürlichen Zeilen-Lock-Kandidaten. Ein Postgres-Advisory-Lock
(`pg_advisory_lock`/`_unlock`) passt strukturell besser.

**Warum das Ergebnis trotzdem geloggt wird, auch wenn der Recheck "blocked" meldet:**
Das Geld für den LLM-Call ist zu diesem Zeitpunkt bereits ausgegeben (der Provider
hat abgerechnet) — würde der Ledger-Eintrag bei einem Recheck-Fehlschlag
verschluckt, würde `cost_ledger` vom tatsächlichen Verbrauch abweichen (Invariante 7
verlangt eine **doppelt** durchgesetzte, also verlässliche Kostenbuchhaltung). Der
Recheck entscheidet nicht "wird gebucht oder nicht", sondern nur, ob
`BudgetExceededError` signalisiert wird — die eigentliche Bremse für *zukünftige*
Calls ist der unveränderte Pre-Call-Check am Anfang der Funktion, der jetzt einen
akkuraten Stand sieht, sobald der Recheck+Insert einer anderen Persona
durchgelaufen ist.

**Bewusst nicht vollständig verhindert:** Die 6 initialen Pre-Call-Checks können
weiterhin gleichzeitig einen veralteten (zu niedrigen) Stand lesen und alle "OK"
zurückgeben, bevor irgendjemand seinen LLM-Call beendet hat — das Audit akzeptiert
diesen Rest-Spielraum ausdrücklich ("Überschuss ≤ 6 × Einzelcall-Kosten"), zusätzlich
gedeckelt durch die zweite Ebene (LiteLLM-Key-Budgets pro Rolle×Persona). Der Fix
schließt das Fenster *danach*: sobald auch nur eine Persona ihren Call+Recheck+Insert
abgeschlossen hat, sehen alle folgenden Calls (auch die restlichen der 6 parallelen,
falls ihr eigener Call länger braucht) den echten Stand.

**Design-Entscheidungen:**
- `pg_advisory_lock`/`pg_advisory_unlock` (Session-scoped, explizit released) statt
  `pg_advisory_xact_lock` (transaktions-scoped) — die SQLAlchemy-Session lebt bis zum
  Commit im Graph-Knoten weit über das Ende von `guarded_complete` hinaus; ein
  xact-scoped Lock bliebe bis dahin gehalten und würde effektiv den gesamten Rest der
  Persona-Verarbeitung serialisieren.
- Fixer Lock-Key (`_SYSTEM_BUDGET_LOCK_KEY`, beliebige int64-Konstante) statt
  `hashtext(...)` — einfacher, keine Hash-Kollisions-/Funktionsverfügbarkeits-Fragen.
- Recheck erst *nach* dem Insert der eigenen Kosten (nicht davor) — nur so erkennt
  der Recheck, ob **dieser** Call (zusammen mit dem, was während seines Laufs an
  Geschwister-Kosten committet wurde) den Cap gerade gerissen hat.

## 3. Testdefinition (vor Umsetzung)

`tests/llm/test_guarded_complete.py`:
1. Ein während des LLM-Calls (im Mock-Handler) committeter "Geschwister"-Kosten-Eintrag
   plus die eigenen Kosten überschreiten den Cap zusammen → `BudgetExceededError`
   wird geworfen, **aber beide** `cost_ledger`-Zeilen bleiben erhalten (nicht verloren).
2. Bestehende Tests (kein Recheck-Fall) bleiben unverändert grün.

## 4. Implementierung

`src/llm/ledger.py`: `_system_budget_lock()`-Context-Manager,
`guarded_complete()` rechnet nach dem Insert erneut `check_system_budget` innerhalb
des Locks nach und wirft danach (außerhalb des Locks) bei Bedarf.

## 5. Testdurchlauf

`uv run pytest tests/llm -q` → 26 passed (25 bestehend + 1 neu). `uv run mypy
src/llm` → sauber. `uv run ruff check`/`ruff format --check` → sauber.

## 6. Rollback-Pfad

Commit zurücknehmen — rein additiv (ein Context-Manager-Aufruf um den
bestehenden Insert), kein Schema-Change, kein Feature-Flag nötig.
