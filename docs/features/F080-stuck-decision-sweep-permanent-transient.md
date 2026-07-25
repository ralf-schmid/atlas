# F080 — Stuck-Decision-Sweep unterscheidet permanent vs. transient

**Status:** Entwurf (Feature-Schnitt 25.07.2026, Phase 5 Block 0)
**Phase:** 5, Block 0 (P4-Abschluss + Aufräumer, vor dem P5-Start)
**Abhängigkeiten:** keine harten. Muss vor dem Wettbewerbsstart (2026-08-03)
erledigt sein. Verwandt mit [F079] (Sizing-Reject) — F079 verhindert das
Entstehen sub-1-Aktien-APPROVED-Leichen, F080 räumt bestehende dauerhaft
unausführbare APPROVED-Decisions auf, statt sie endlos zu wiederholen.

## 1. Zieldefinition

`retry_stuck_decisions` (`src/orchestrator/scheduler.py`) versucht jede
`APPROVED`-Decision ohne `order_record` in jedem Sweep erneut über
`execute_decision`. Bei einem Fehler wird die Decision nur geloggt und beim
nächsten Sweep wieder versucht — **ohne Ende**. Das ist richtig für transiente
Fehler (Netzwerk, Broker-5xx, Markt geschlossen), aber falsch für dauerhaft
unausführbare Decisions: eine Decision mit kaputten Daten (z. B. `quantity`
rundet im Adapter auf 0 ganze Aktien, fehlender `stop_loss_price`, `quantity`
None) scheitert bei **jedem** Versuch identisch und erzeugt bei jedem Sweep einen
`ERROR`-Logeintrag — Log-Rauschen, das echte Probleme verdeckt, und (vor F079)
der beobachtete Endlos-Retry-Fall aus `phase-4.md` (21.07.2026).

Ziel: `retry_stuck_decisions` unterscheidet **permanente** von **transienten**
Fehlern.
- **Permanent** (`ValueError`): Die Decision ist strukturell unausführbar und
  wird es bei jedem Retry bleiben. → Decision terminal auf neuen Status
  `EXECUTION_FAILED` setzen, `rejection_reason` mit der Fehlerursache füllen,
  **einen einzigen** Telegram-Alert senden, danach nie wieder anfassen.
- **Transient** (jeder andere Fehler, insb. Broker-`APIError`/Netzwerk): wie
  bisher — loggen, `APPROVED` lassen, im nächsten Sweep erneut versuchen.

**Entscheidung (Ralf, 25.07.2026):**
- **Terminal-Status = neuer `DecisionStatus.EXECUTION_FAILED`** (nicht `RECORDED`
  wiederverwenden). Sauber im Dashboard/Grafana filterbar und klar von
  `reject_idea`/`risk_rejected`/`hold` getrennt — eine am Broker gescheiterte
  Order ist etwas anderes als eine nie platzierte Idee.
- **Nur `ValueError` gilt als permanent.** Konservativ: gestoppt wird nur, wo das
  Scheitern sicher aussichtslos ist (kaputte Decision-Daten, die `execute_decision`
  selbst als `ValueError` wirft — siehe §2). Jeder Broker-/Netzwerkfehler bleibt
  transient und wird weiter versucht — ein valider Trade wird nie fälschlich
  verworfen, nur weil der Broker kurz nicht erreichbar war oder der Markt zu war.

## 2. Kontext / Ist-Zustand

`execute_decision` (`src/orchestrator/trading.py`) wirft `ValueError` genau in den
strukturell-kaputten Fällen:
- `decision.status != APPROVED` (Zeile 33) — im Sweep ausgeschlossen (Filter),
  aber defensiv permanent.
- kein `stop_loss_price` in `expected_outcome` (Zeile 42).
- `decision.quantity is None` (Zeile 44 / 93).

Der Adapter (`AlpacaPaperAdapter.place_order`) wirft zusätzlich `ValueError`, wenn
`round(qty) == 0` (F052) — der historische Endlos-Retry-Fall. Ab F079 entsteht
dieser für **neue** Decisions nicht mehr (Reject in der Sizing-Schicht), aber
Alt-Decisions, die vor F079 als APPROVED persistiert wurden, können ihn noch
auslösen — genau die räumt F080 auf.

Transiente Fehler dagegen kommen als `alpaca.common.exceptions.APIError` (5xx,
Rate-Limit, „market closed") oder als Netzwerk-Exception aus dem Adapter — **keine**
`ValueError`. Die Trennlinie „`ValueError` = permanent, alles andere = transient"
fällt damit exakt mit der bestehenden Fehlersemantik zusammen, ohne dass
`execute_decision` oder der Adapter neue Exception-Typen einführen müssen.

## 3. Scope

- Neuer Enum-Wert `DecisionStatus.EXECUTION_FAILED` (`src/db/models.py`) +
  Alembic-Migration (`ALTER TYPE decision_status ADD VALUE 'EXECUTION_FAILED'`,
  non-transaktional — `op.execute` mit `COMMIT`, siehe §4).
- `retry_stuck_decisions` (`scheduler.py`): `except ValueError` **vor** dem
  generischen `except Exception`:
  - `session.rollback()` (die halbfertige Transaktion verwerfen), dann die
    Decision frisch laden, `status = EXECUTION_FAILED`,
    `rejection_reason = f"execution_failed_permanent: {exc}"` setzen,
    `session.commit()`.
  - genau **einen** Telegram-Alert senden (best-effort, non-fatal wie die
    bestehenden Alerts im Sweep — ein Telegram-Ausfall darf den Sweep nicht
    abbrechen).
  - Sweep mit der nächsten Decision fortsetzen (`continue`).
- Der generische `except Exception`-Zweig bleibt unverändert (transient: loggen,
  `rollback`, `continue` — Decision bleibt `APPROVED`).
- Ein neuer Telegram-Formatter `format_execution_failed_message` in
  `src/telegram/alerts.py` (analog `format_trade_executed_message`).
- Unit-Tests (§5).

**Non-Scope:**
- Keine Retry-Zähler/Backoff für transiente Fehler — bleibt „bei jedem Sweep
  erneut", wie bisher. (Ein Zähler wäre ein eigenes Feature; die konservative
  ValueError-Grenze macht ihn nicht dringend.)
- Keine Reklassifizierung bestehender Broker-Fehler zu `ValueError` — die
  Trennlinie nutzt die vorhandene Semantik.
- Kein LLM-Anteil (Scheduler ist Code, CLAUDE.md-Verbot).
- Kein Eingriff in `reconcile_order_fills` (das behandelt bereits-platzierte
  Orders, nicht das Platzieren selbst).

## 4. Migration

`ALTER TYPE ... ADD VALUE` kann in Postgres **nicht** in einem
Transaktionsblock laufen. Die Migration nutzt daher `op.execute` mit vorherigem
`COMMIT` (Muster: autocommit-Block), und `downgrade` ist ein No-Op mit Kommentar
(Postgres kann einen Enum-Wert nicht ohne Typ-Neuaufbau entfernen; ein
ungenutzter Enum-Wert schadet nicht). Der neue Wert wird **ans Ende** der
Enum-Werteliste gehängt — Reihenfolge ist für `DecisionStatus` bedeutungslos
(kein Ordinal-Vergleich im Code).

## 5. Testdefinition

Fixtures analog `tests/orchestrator/test_scheduler*.py` (echte Postgres-Schema-Fixture),
`adapter_factory` injizierbar (bereits Parameter von `retry_stuck_decisions`).

1. **Permanenter Fehler (`ValueError`) → EXECUTION_FAILED + ein Alert:** Adapter,
   dessen `place_order` `ValueError` wirft (oder Decision mit `quantity=None`).
   Ein Sweep → Decision-Status `EXECUTION_FAILED`, `rejection_reason` beginnt mit
   `"execution_failed_permanent:"`, **kein** `order_record`, `send_alert` genau
   einmal aufgerufen.
2. **Kein zweiter Versuch:** nach Test 1 ein zweiter Sweep → Decision wird vom
   Filter (`status == APPROVED`) nicht mehr erfasst, `place_order` **nicht**
   erneut aufgerufen, **kein** zweiter Alert.
3. **Transienter Fehler (`APIError`/generisch) → bleibt APPROVED, kein Alert:**
   Adapter, dessen `place_order` `RuntimeError`/`APIError` wirft. Ein Sweep →
   Decision bleibt `APPROVED`, kein `EXECUTION_FAILED`, kein Alert; ein zweiter
   Sweep ruft `place_order` **erneut** auf (Retry lebt weiter).
4. **Transient dann Erfolg:** erster Sweep transient gescheitert (bleibt
   APPROVED), zweiter Sweep mit funktionierendem Adapter → `EXECUTED`,
   `order_record` existiert.
5. **Telegram-Ausfall beim permanenten Fehler ist non-fatal:** `send_alert` wirft
   → Decision ist trotzdem `EXECUTION_FAILED` (Alert-Fehler nur geloggt), Sweep
   bricht nicht ab.
6. **Isolation im Sweep:** zwei stuck Decisions, die erste permanent kaputt, die
   zweite ausführbar → erste `EXECUTION_FAILED`, zweite `EXECUTED` (ein kaputter
   Fall blockiert den Rest nicht — bestehender Kontrakt bleibt erhalten).

## 6. Kritische Betrachtung

- **Invariante 2 (Privilege Separation):** unberührt — `retry_stuck_decisions`
  ruft weiterhin nur `execute_decision`, kein neuer Order-Pfad.
- **Invariante 4 (Stop-Loss-Pflicht):** unberührt — eine `EXECUTION_FAILED`-Decision
  platziert keine Order.
- **Datenintegrität:** `EXECUTION_FAILED` ist terminal; eine so markierte Decision
  wird vom APPROVED-Filter nie wieder erfasst. Der `rejection_reason` bewahrt die
  konkrete Fehlerursache für die spätere Analyse (Dashboard/Grafana).
- **Fehlklassifikations-Risiko:** bewusst konservativ (nur `ValueError`). Der
  teurere Fehler wäre, einen bei geänderten Bedingungen ausführbaren Trade
  fälschlich zu verwerfen — die ValueError-Grenze schließt genau das aus, weil
  Broker-/Marktzustände nie als `ValueError` ankommen.
- **Alert-Volumen:** genau ein Alert pro permanent gescheiterter Decision (nicht
  pro Sweep) — kein Alert-Spam.
- **Kosten:** 0 — reiner Code, keine LLM-Calls.

## 7. Offene Punkte

- Keine — Terminal-Status (`EXECUTION_FAILED`) und Klassifikation (nur
  `ValueError` permanent) sind mit Ralf entschieden (25.07.2026).

[F079]: F079-sizing-no-sub-one-share-orders.md
