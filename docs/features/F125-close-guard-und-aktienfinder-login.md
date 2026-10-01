# F125 — CLOSE nur gegen gehaltene Position + aktienfinder-Login-Reparatur

Status: implementiert, Deploy 01.10.2026
Datum: 2026-10-01
Phase: Betriebshärtung (ergänzt F077/F080)
Auslöser: Ralf — gehäufte Fehlermeldungen aus ATLAS Ende September; Log-Auswertung
der Box (7 Tage, `atlas-scheduler-1`)

## 1. Befund

Log-Auswertung 24.09.–01.10.2026, nach Häufigkeit:

| Meldung | Anzahl | Ursache |
|---|---|---|
| `failed to retry stuck decision` | 3360 | **Code** — §2 |
| `review failed` / `cycle failed` / `market_research` / `news_research` | je 34–56 | **Kein Code-Fehler:** OpenCode-Zen-Guthaben leer seit 22.09. (`Insufficient account funds`); der Anthropic-Direkt-Slot (`*-anthropic`) hat ebenfalls kein Guthaben. Ralf muss aufladen. |
| `aktienfinder-Snapshot failed` / `-Screener-Discovery failed` | je 7 (täglich seit 25.09.) | **Code** — §3 |
| `EDGAR-RSS-Sync failed` | 6 | transient (SEC-ReadTimeout am 28.09.), kein Handlungsbedarf |

## 2. CLOSE ohne gehaltene Position

Ein CLOSE ist ein Market-Sell über `decision.quantity` — ohne Prüfung, ob die
Position beim Broker noch existiert. Wenn eine Persona dieselbe Position in zwei
Zyklen hintereinander schließen will, läuft die zweite Decision ins Leere:

- **Nicht shortbares Asset** (BTCT, RZLV ×3, PDSB — alle VULTURE): Alpaca antwortet
  `422 cannot be sold short`. Der Sweep (F080) behandelte das als transient, die
  fünf Decisions blieben `APPROVED` und wurden seit August alle paar Minuten neu
  versucht.
- **Shortbares Asset** (GPRO, VULTURE): die zweite CLOSE-Decision vom 02.09. hing im
  Sweep und ging am **14.09. durch** — 146 Stück leerverkauft, **ohne Stop-Loss**
  (Invariante #4). Die Short-Position stand am 01.10. noch bei Alpaca.

**Fix:** `_execute_close` prüft vor dem Verkauf `broker_adapter.get_positions()`.
Liegt keine Long-Position in mindestens der CLOSE-Menge vor → `ValueError`. Das ist
der bestehende Permanent-Pfad aus F080: `EXECUTION_FAILED` + genau ein Telegram-Alert.
Broker statt `order_record` als Wahrheit, weil ein Stop-Fill die Position schließt,
ohne einen `order_record` zu hinterlassen. Toleranz 1e-6 für Krypto-Bruchstücke
(`numeric(18,6)` gegen Ledger-float). Symbolvergleich ohne `/` (`BTC/USD` = `BTCUSD`).

**Bekannte Grenze:** Absturz *zwischen* Broker-Submit und DB-Commit eines CLOSE → der
Retry findet die Position nicht mehr und markiert `EXECUTION_FAILED`, obwohl der
Verkauf stattfand. Sichtbar (Alert), nicht still; die Alternative (blind
wiederholen) hat GPRO produziert.

**Nicht Teil dieses Features — Ralfs Entscheidung:** die GPRO-Short-Position
(−146) glattstellen (Buy-to-Cover im Alpaca-Paper-Dashboard von VULTURE).

## 3. aktienfinder-Login

Seit ~25.09. führt der Klick auf „Anmelden" (von `/profil`) nach `/anmelden`
**und** öffnet zusätzlich ein Login-Modal. Zwei Formulare mit denselben IDs
`#username`/`#password`; `fill` traf das Seitenformular, der Klick auf „Weiter"
löste auf den noch deaktivierten Button im Modal auf → Timeout nach 30 s.

**Fix:** direkt `/anmelden` aufrufen — dort gibt es genau ein Formular, kein Modal.
Live verifiziert 01.10.2026 im `scheduler`-Container (Nav-Leiste zeigt „Abmelden").

## 4. Tests

- `tests/orchestrator/test_trading.py`: CLOSE verweigert bei leerer Position, zu
  kleiner Position, Short-Position, anderem Symbol — kein Broker-Call, kein
  `order_record`, Decision bleibt `APPROVED`; Krypto-Symbol ohne Slash + Rundung.
- `tests/orchestrator/test_stuck_decision_sweep.py`: hängende CLOSE ohne Position →
  `EXECUTION_FAILED`, ein Alert, Broker nicht erreicht.
- `tests/ingestion/test_aktienfinder_grabbing.py`: Login ruft `/anmelden` auf.

## 5. Livesetzung

Mit demselben Deploy wird F124 (`stock.calendar_gate: true`) scharf geschaltet —
fällig seit 19.09., war nie auf der Box.

Erwartung nach dem Deploy: der erste Sweep markiert die fünf hängenden VULTURE-
Decisions `EXECUTION_FAILED` (fünf Telegram-Alerts, einmalig), danach keine
`failed to retry stuck decision` mehr. aktienfinder-Job am nächsten Morgen
(11:00 UTC) ohne Fehler.

## 6. Rollback

Code-Revert dieses Commits + Rebuild `api web scheduler telegram-bot`. Kein
Config-Flag: der Guard verhindert ausschließlich Verkäufe, die eine Short-Position
eröffnen würden.
