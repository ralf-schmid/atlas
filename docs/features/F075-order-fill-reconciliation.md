# F075 — Order Fill Reconciliation

Status: umgesetzt, deployt und live verifiziert auf `atlas-ugreen`
Datum: 2026-07-14
Phase: 5

## 1. Zieldefinition

Beim Live-Check von F074 (Kurs-Charts) fehlten die Kauf-Marker auf den
Charts der echten Personas. Root Cause (bestätigt gegen die echte Box-DB):
**jeder** `order_record` in Produktion (alle 12, alle 6 Personas) stand auf
`status=NEW` — keiner wurde je auf `FILLED` gesetzt.
`src/orchestrator/trading.py::execute_decision` legt jede Order mit
`status=OrderRecordStatus.NEW` an; danach schrieb **nirgends** im Code
etwas anderes zurück. Das ist keine Regression, sondern eine in F023 bewusst
ausgeklammerte Lücke ("Fill-Polling/-Reconciliation... von F023 §1 bewusst
als Non-Scope ausgeklammert", Kommentar in `src/broker/alpaca_paper.py`,
bestätigt in F052 §1).

Betroffen waren drei Konsumenten von `filled_at`/`fill_price`/`status`:
1. F074s Chart-Marker (erfordert `filled_at IS NOT NULL`).
2. `/holdings`' "Letzter Kauf" (`func.max(OrderRecord.filled_at)`, F034) —
   zeigte in Produktion immer "–".
3. Der tägliche Telegram-Digest (F070): "Durchgeführte Trades" ist explizit
   als `OrderRecordStatus.FILLED` definiert — zeigte vermutlich seit Deploy
   immer 0 Trades, auch an Tagen mit echten Käufen.

Positionswerte/P&L selbst waren **nicht** betroffen — die kommen aus
`PositionSnapshot` via direktem `broker_adapter.get_positions()`-Polling,
nicht aus `order_record`. Ralfs Entscheidung nach Rückfrage: dafür ein
eigenes Feature bauen, kein reines Doku-Issue.

**Kein Widerspruch zu F023/F052:** jene Entscheidung betraf das *Aufteilen
von Entry+Stop in zwei Order-Submits* (Wash-Trade-Risiko, Zeitfenster ohne
Broker-Stop) — dieses Feature ändert an der Order-**Platzierung**
(Bracket/OTO, Invariante #4) nichts. Es ist ein reiner Read-Only-Status-Poll
*nach* der Platzierung, betrifft nur die eigene DB-Bilanz.

**Scope:** zwei adapterspezifische Pfade (kein einheitliches
`BrokerAdapter`-Protocol-Feld) + ein einmaliges Backfill-Skript für
bestehende virtuelle Alt-Orders. **Non-Scope:** `filled_qty`/Partial-Fill-
Mengen-Tracking (Schema-Change, nicht durch Daten begründet), rückwirkender
`fill_price`-Backfill für virtuelle Alt-Orders (Daten nicht rekonstruierbar
— nie persistiert), jede Änderung an Order-Platzierung selbst.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #4 Pflicht-Stop-Loss als GTC-Order | nein | Reiner Status-Read nach Platzierung, ändert nichts an der Bracket-Order-Logik. |
| #1 Risk-Gate ist deterministischer Code | nein | Reine Reporting-Aktualisierung, kein Einfluss auf Risk-Gate/Sizing. |
| Fairness #10 | nein | Gleicher Code-Pfad je Adaptertyp für alle Personas dieses Typs, kein Informationsvorsprung. |
| Kosten-Caps #7 | nein | Keine LLM-Calls, reine Broker-/DB-Reads (Alpaca IEX-Trading-API, kostenneutral wie die Marktdaten-Calls in F074). |

**Design-Entscheidung: zwei Pfade statt ein einheitliches Protocol-Feld.**

**A) Virtuelle Personas (HYPE/CONTRA/CRYPTOR, `InternalLedgerAdapter`) —
synchron, ohne Polling.** `place_order()` füllt bereits synchron
(`_apply_fill` im selben Call, `market_data.get_last_price` als Preis) — der
Fill ist zum Zeitpunkt der Order-Erstellung bereits bekannt, `OrderResult`
gab ihn bisher nur nicht weiter. `OrderResult` bekommt zwei neue optionale
Felder (`filled_at`, `fill_price`, beide Default `None` — additiv, kein
Breaking Change); `InternalLedgerAdapter.place_order()` befüllt sie;
`AlpacaPaperAdapter.place_order()` lässt sie `None` (beim Submit ist der
Fill bei Alpaca noch nicht bekannt, unverändertes Verhalten);
`execute_decision()` legt die Order bei gesetztem `filled_at` direkt mit
`status=FILLED` an statt `NEW`.

**B) Native Personas (VULTURE/GUARDIAN/CHARTIST, `AlpacaPaperAdapter`) —
asynchroner Reconciliation-Job**, weil Alpaca den Fill erst nach dem Submit
asynchron bestätigt (bereits real beobachtet: F052 §5 zeigt Entry-Orders,
die erst bei manueller Nachprüfung als `FILLED` bestätigt wurden). Neue
Methode `AlpacaPaperAdapter.get_order_status(order_id)` — **nicht** Teil des
gemeinsamen `BrokerAdapter`-Protocols (ergibt für die virtuelle
Adapter-Seite keinen Sinn, die nie einen offenen/pending Zustand hat;
gleiches Präzedenzmuster wie `persona_analysis._sweep_stop_orders`, das
ebenfalls konkret auf `InternalLedgerAdapter` statt uniform übers Protocol
geht). Mapped Alpacas `OrderStatus` (`filled`/`partially_filled`/
`canceled`/`rejected`/`expired`/alles andere=weiterhin offen) auf einen
kleinen, broker-eigenen `AlpacaOrderState`. Neue Funktion
`reconcile_order_fills(session_factory, adapter_factory=get_adapter)` in
`src/orchestrator/scheduler.py`, 1:1 nach dem Muster von
`retry_stuck_decisions` (gleiche Datei): holt alle `OrderRecord` mit
`status=NEW`, überspringt Personas mit `get_adapter_type(name) !=
"alpaca_paper"` (virtuelle Personas sind über Pfad A bereits erledigt),
pollt pro verbleibender Order, aktualisiert bei definitivem Ergebnis — pro
Zeile eigener Commit, ein Fehler bricht nicht die restliche Sweep
(identischer Non-Fatal-Vertrag wie `retry_stuck_decisions`). Läuft alle 15
Minuten (`_ORDER_RECONCILE_INTERVAL_MINUTES`, gleiche Größenordnung wie
`_STUCK_DECISION_SWEEP_INTERVAL_MINUTES` — unkritisch, reine
Reporting-Aktualisierung, kein Zeitdruck). Löst rückwirkend auch die
bereits bestehenden `NEW`-Orders der nativen Personas (Alpaca kennt deren
echten Fill-Status unabhängig davon, seit wann wir fragen).

**C) Einmaliger Backfill für bestehende virtuelle Orders**
(`scripts/backfill_ledger_order_fills.py`): `filled_at = submitted_at` ist
exakt korrekt (synchroner Fill = derselbe Zeitpunkt wie Submit, keine
Schätzung), `fill_price` bleibt für diese Alt-Zeilen `NULL` (ehrlich
unbekannt — nie persistiert). Digest-Zähler und `last_buy_at` werden dadurch
für diese Personas korrekt; Chart-Marker bleiben für genau diese
Alt-Positionen leer (Chart-Query verlangt `fill_price IS NOT NULL`) —
akzeptierte, dokumentierte Lücke nur für Alt-Daten.

**Ledger-JSON-Schema:** `ExecutedOrder` (`src/broker/ledger_store.py`)
bekommt zwei neue optionale Felder `fill_price`/`filled_at` (Letzteres als
ISO-String, nicht `datetime` — hält `json.dumps(asdict(...))` ohne
Custom-Encoder funktionsfähig). Rückwärtskompatibel: `JSONLedgerStore.load()`
nutzt `.get(...)` mit Fallback `None` für Dateien, die dieses Feld noch
nicht kennen — betrifft bereits bestehende, echte Ledger-Dateien auf der
Box (HYPE/CONTRA/CRYPTOR), keine Migration nötig, kein Datenverlust.

## 3. Testdefinition (vor Implementierung geschrieben)

- `tests/broker/test_internal_ledger.py`: `place_order()` liefert
  `filled_at`/`fill_price` korrekt befüllt; ein Crash-Replay
  (F027-Idempotenz) rekonstruiert **dieselben** Werte, nicht `None` — das
  war der erste gefundene Regressions-Fall (bestehender Test
  `test_place_order_replayed_with_same_decision_id_does_not_refill` prüft
  volle `OrderResult`-Gleichheit).
- `tests/broker/test_ledger_store.py`: Save/Load-Roundtrip für
  `ExecutedOrder.fill_price`/`filled_at`; ein Laden einer Alt-Datei ohne
  diese Felder liefert `None`, kein Crash.
- `tests/orchestrator/test_trading.py`: neuer Fake-Adapter-Fall mit
  gesetztem `filled_at` → `OrderRecord.status == FILLED` mit korrekten
  Werten; bestehender Fall (kein `filled_at`) bleibt `NEW` (Regression
  Guard).
- `tests/broker/test_alpaca_paper.py`: `get_order_status()` — Mapping für
  `filled`/`partially_filled`/`canceled`/`rejected`/`expired`/offen
  (`new`/`accepted`), inkl. `filled_at`/`filled_avg_price`-Extraktion
  (tz-aware Alpaca-Zeitstempel → naive DB-Konvention).
- Neue `tests/orchestrator/test_order_fill_reconciliation.py`
  (`pytest.mark.integration`, Muster: `test_stuck_decision_sweep.py` —
  eigene `session_factory`, kein Rollback-Fixture): aktualisiert eine native
  `NEW`-Order zu `FILLED`; lässt eine weiterhin offene Order unverändert;
  überspringt virtuelle Personas (`adapter_factory` wird für sie nie
  aufgerufen); ein fehlschlagender Poll bricht nicht die restliche Sweep.

## 4. Implementierung

- `src/broker/protocol.py` — `OrderResult` + 2 optionale Felder.
- `src/broker/ledger_store.py` — `ExecutedOrder` + `fill_price`/`filled_at`
  (rückwärtskompatibles Laden).
- `src/broker/internal_ledger.py` — `place_order()` befüllt sie synchron
  (fresh path und Crash-Replay-Pfad).
- `src/orchestrator/trading.py` — `execute_decision()` nutzt sie für
  `status=FILLED` bei synchronem Fill.
- `src/broker/alpaca_paper.py` — neue `AlpacaOrderState`, `AlpacaFillStatus`,
  `get_order_status()`.
- `src/orchestrator/scheduler.py` — `reconcile_order_fills` +
  `_reconcile_order_fills_job` + Registrierung (15-Minuten-Intervall).
- `scripts/backfill_ledger_order_fills.py` — einmaliges Backfill-Skript für
  bestehende virtuelle `NEW`-Orders.
- Kein Alembic-Migrations-Bedarf (keine Schema-Änderung an Postgres-Tabellen
  — nur das JSON-Ledger-Dateiformat gewinnt zwei optionale Felder).

## 5. Test & Verifikation

- `uv run pytest -q` (lokaler Test-Postgres): **605 passed** (16 neue/
  geänderte Tests), `-m integration`: **18 passed, 2 skipped**.
- `uv run ruff check`/`format --check`, `uv run mypy src`: clean.
- **Coverage-Gate (`tests/risk/ tests/broker/ --cov-fail-under=100`,
  identisch zum CI-Job):** `src/broker/*` und `src/risk/*` weiterhin
  **100 % Line + Branch** — durch dieses Feature nicht verschlechtert.
- **Deployt und live verifiziert (14./15.07.2026, `atlas-ugreen`):** rsync +
  `docker compose build api scheduler` + `up -d api scheduler` — beide
  Container healthy, `_reconcile_order_fills_job` im Scheduler-Log
  registriert. `scripts/backfill_ledger_order_fills.py` gegen die echte
  Box-DB ausgeführt: 2 virtuelle Alt-Orders (CONTRA, CRYPTOR) → `FILLED`.
  `reconcile_order_fills` danach manuell angestoßen (nicht auf die
  15-Minuten-Sweep gewartet): **10 native Orders reconciled** — `SELECT
  status, count(*) FROM order_record GROUP BY status` zeigt jetzt **12
  FILLED, 0 NEW** (vorher: 12 NEW, 0 FILLED). `GET
  /api/personas/VULTURE/chart?instrument=ALDX` liefert jetzt einen echten
  Kauf-Marker (`fills: [{"ts": "2026-07-10T19:00:30...", "price": 2.16,
  "action": "buy"}]`) und einen echten Live-Preis
  (`live_price.price: 1.935`); `/api/personas/VULTURE/holdings` zeigt ein
  echtes `last_buy_at` für ALDX und KEEL statt `null`. Der ursprüngliche
  F074-Befund (fehlende grüne Dreiecke) ist damit vollständig behoben.

## 6. Rollback-Pfad

Additiv: neue optionale Felder (`OrderResult`, `ExecutedOrder`), neue
Funktionen/Methoden, eine neue Zeile in `execute_decision`. Kein
Schema-Change an Postgres. Bei Rollback: Commit zurücknehmen genügt — alte
Ledger-JSON-Dateien mit den neuen Feldern bleiben von einer älteren
Code-Version lesbar (unbekannte JSON-Keys werden von der alten
`ExecutedOrder`-Konstruktion ignoriert, da `JSONLedgerStore.load()` die
Felder explizit auflistet statt generisch zu entpacken). Der
Scheduler-Job lässt sich ohne Revert auch durch Entfernen der
`add_job(...)`-Registrierung abschalten — bestehende `order_record`-Zeilen
bleiben dann einfach `NEW`, identisch zum Verhalten vor diesem Feature.
