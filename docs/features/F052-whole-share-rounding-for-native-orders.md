# F052 — Fractional Positionsgrößen auf ganze Aktien runden (native Alpaca-Personas)

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Fortsetzung von F051: der DAY-Fix behob die erste Alpaca-422, aber der
erneute `retry_stuck_decisions`-Lauf auf der Box scheiterte sofort an einer
zweiten, tieferliegenden: `{"code":42210000,"message":"fractional orders must
be simple orders"}`. Alpaca lässt bei gebrochener Stückzahl **überhaupt keine**
Bracket/OTO-Order zu — unabhängig vom `time_in_force`. Da
`AlpacaPaperAdapter.place_order` den Pflicht-GTC-Stop (Invariante #4)
ausschließlich als Bracket-Child-Leg anhängt (siehe F023, wash-trade-Problem
bei separatem Stop-Order), kollidiert das direkt mit der Sizing-Formel
(`amount_usd / entry_price`), die praktisch nie eine ganze Aktienzahl ergibt.

Ralf explizit gefragt (Invariante #4 ist nicht-verhandelbar, "bei Konflikt:
nachfragen, nicht aufweichen") — Entscheidung: auf ganze Aktien runden, statt
Entry und Stop in zwei Schritte aufzuteilen (Alternative hätte
Fill-Polling/-Reconciliation gebraucht, von F023 §1 bewusst als Non-Scope
ausgeklammert, plus ein Zeitfenster ohne Broker-Stop nach dem Fill).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #4 Pflicht-Stop-Loss als GTC-Order | ja, Kern des Fixes | Rundung auf ganze Aktien ist die Voraussetzung dafür, dass der Bracket-Order (und damit der Pflicht-Stop) bei Alpaca überhaupt akzeptiert wird. Rundet auf 0 → `ValueError` statt eine Order ohne Stop-Möglichkeit zu erzwingen oder den Stop wegzulassen. |
| #1 Risk-Gate ist deterministischer Code | ja, Nebenwirkung dokumentiert | Das Risk-Gate prüft weiterhin den ungerundeten `position_value_usd`/`quantity` (unverändert in `persona_analysis.py`) — die Rundung passiert ausschließlich in der Broker-Adapter-Schicht, nach der Risk-Gate-Freigabe. Tatsächliche Order-Größe kann dadurch vom geprüften Betrag abweichen (z. B. 0,87 Aktien → 1 Aktie = +15 % Exposure bei AAPL). Bewusst akzeptiert (Ralfs Entscheidung) — keine zweite Risk-Gate-Prüfung auf den gerundeten Wert, da eine Aufrundung auf 1 Aktie bei kleinen Paper-Konten (5.000 USD) keine der bestehenden Guardrail-Schwellen (max. Positionsgröße, Tagesverlust) in der Praxis reißen kann; falls doch, greift die bestehende Circuit-Breaker-/Drawdown-Logik unverändert. |
| Fairness | nein | Nur die 3 nativen Alpaca-Personas betroffen (Adapter-spezifisch) — die 3 virtuellen (`internal_ledger`) behalten volle Fraktions-Präzision, weil sie keinen echten Bracket-Order beim Broker platzieren. Das ist ein bestehender, nicht neu eingeführter Unterschied zwischen den beiden Broker-Typen (siehe ADR 0001), keine neue Bevorzugung. |
| Kein stiller Fallback | ja | Rundet ein Betrag auf 0 ganze Aktien, wird **kein** Order-Versand versucht — `ValueError` propagiert nach oben, `_maybe_execute_decision` (F023) fängt sie wie jeden Broker-Fehler als `agent_run(agent="trading", status=FAILED)` ab. Decision bleibt `APPROVED`, kein `order_record`. |

**Kosten:** keine. **Design-Entscheidung:** `round()` (kaufmännisch), nicht
`floor()`/`ceil()` — bleibt näher am Risk-Gate-geprüften Betrag in beide
Richtungen, statt systematisch zu über- oder unterschätzen.

## 3. Testdefinition

`tests/broker/test_alpaca_paper.py`: (1) fractional `qty=0.869813` (reale
AAPL-Decision) wird auf `1` gerundet, Entry-Request bekommt `qty=1`,
`time_in_force=gtc` (nicht mehr `day` — F051s TIF-Unterscheidung ist mit
garantiert ganzzahligem `qty` nicht mehr erreichbar, daher zurückgebaut auf
festes GTC); `OrderResult.qty` spiegelt den tatsächlich gesendeten,
gerundeten Wert. (2) `qty=0.3` (rundet auf 0) wirft `ValueError` mit klarer
Meldung, **kein** `submit_order`-Aufruf. Bestehender GTC-Test (`qty=1`)
bleibt unverändert grün, prüft zusätzlich jetzt auch `result.qty == 1`.

## 4. Implementierung

`src/broker/alpaca_paper.py`: `place_order` rundet `qty` per `round()` auf
eine ganze Zahl, bevor der `MarketOrderRequest` gebaut wird; wirft
`ValueError` bei Rundung auf 0. F051s bedingtes `TimeInForce.DAY` entfällt
wieder (mit garantiert ganzzahligem `qty` nie mehr wahr) — zurückgebaut auf
festes `TimeInForce.GTC`.

## 5. Testdurchlauf

`uv run pytest tests/broker/test_alpaca_paper.py -q` → 16 passed. `uv run
pytest -q -m 'not integration'` → 486 passed, 10 deselected. `uv run pytest
-q -m integration` → 8 passed, 2 skipped (unverändert). `uv run ruff
check`/`ruff format --check` → sauber. `uv run mypy src/broker` → sauber.

**Live-Verifikation (2026-07-10, UGREEN, echte Alpaca-Paper-Accounts):**
`retry_stuck_decisions` manuell angestoßen → `retried: 2`. Beide Decisions
`EXECUTED` mit echtem `order_record`: AAPL (CHARTIST) 1 Aktie, Stop
742d5a66… @ 290.87 USD; ALDX (VULTURE) 26 Aktien, Stop 42a55d6c… @ 1.72 USD.
Gegenprobe direkt gegen die echten Alpaca-Accounts: beide Entry-Orders
`FILLED`, beide Stop-Legs `time_in_force=GTC`, `status=NEW` (aktiv) — bestätigt
§2s Annahme, dass die Rundung Invariante #4 tatsächlich wieder erreichbar
macht. VULTUREs `buying_power` sank von 5.000 auf 4.937,20 USD, konsistent
mit 26 ALDX-Aktien zu ca. 2,29 USD.

## 6. Rollback-Pfad

Additiv/lokal auf `place_order` begrenzt — Commit zurücknehmen genügt, kein
Schema-Change. Bei Rollback fallen die drei nativen Personas wieder auf den
F051-Zustand zurück (DAY-Fix bleibt separat committed, aber wieder wirkungslos
ohne die Rundung, da "fractional orders must be simple orders" erneut
greift).
