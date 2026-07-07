# F020 — Portfolio-Risk-Gate-Eingaben

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Letzter Baustein vor dem Persona-Analyse-Agenten (`docs/dod/phase-4.md` Punkt 6):
`src.risk.gate.evaluate_decision` (F004, Phase 2) ist deterministischer Code, der
`portfolio_equity_usd`, `portfolio_cash_usd`, `portfolio_peak_equity_usd`,
`open_positions_count` und `trades_today_count` als Eingaben braucht — bisher liest
nirgends im Repo den echten Broker-Kontostand für diese Werte. Dieses Feature liefert
`read_portfolio_risk_state`, das den echten `BrokerAdapter` (F001/F002) + echte
`order_record`/`decision`-Historie kombiniert.

**Scope:** Portfolio-Zustand lesen (Equity, Cash, offene Positionen, Peak-Equity,
Trades heute). **Non-Scope:** kein neuer `portfolio_snapshot`-Schreib-Job (das ist
Teil des späteren Reporting-Agenten, der auch PnL-Realized/Benchmark-Tracking
braucht) — Peak-Equity nutzt die bereits vorhandene Snapshot-Historie rein lesend,
mit einem sicheren Fallback, wenn noch keine existiert.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate ist deterministischer Code | ja | Dieses Feature liefert nur *Eingaben* für das bestehende, unveränderte `evaluate_decision` — keine Änderung an der Risk-Gate-Logik selbst. |
| Broker-Zugriff ausschließlich über `BrokerAdapter` | ja | `read_portfolio_risk_state` nimmt einen bereits konstruierten `BrokerAdapter` entgegen (via `src.broker.registry.get_adapter`), ruft ausschließlich `get_account_balance()`/`get_positions()` auf — kein direkter Alpaca-Zugriff. |
| Keine stillen Annahmen bei Geld-Themen | ja | **Peak-Equity-Fallback ohne Historie = aktuelle Equity** (Drawdown 0) ist eine bewusste, hier dokumentierte Annahme für den Kaltstart-Fall (noch kein `portfolio_snapshot` vorhanden) — kein stiller Fantasiewert, konservativ (kann den Circuit-Breaker an Tag 1 nicht fälschlich auslösen, aber auch nicht künstlich schützen: sobald echte Snapshots existieren, übernimmt deren Maximum). |
| Fairness | ja | Eine Funktion, ein Adapter-Aufrufpfad für alle 6 Personas — nativ (Alpaca) und virtuell (internal_ledger) liefern über dasselbe `BrokerAdapter`-Protocol identische Feldtypen. |

**Design-Entscheidungen:**
- **`trades_today_count` zählt `order_record`, nicht `decision`:** ein `hold` oder
  `reject_idea` ist kein Trade; erst ein tatsächlich platzierter `order_record`
  (verknüpft über `decision.portfolio_id`) zählt gegen `max_trades_per_day`.
- **Peak-Equity = `MAX(aktuelle Equity, historische portfolio_snapshot.total_value)`**
  für dieses Portfolio — kein neuer Schreibpfad, reine Lesefunktion; sobald der
  spätere Reporting-Agent regelmäßig Snapshots schreibt, wächst die Historie von
  selbst.
- **Ein Dataclass `PortfolioRiskState`** statt fünf einzelner Rückgabewerte — direkt
  als Kwargs-kompatible Eingabe für `risk.gate.evaluate_decision` gedacht (nächstes
  Feature verbindet beides).

**Kosten:** keine LLM-Calls. **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_risk_inputs.py` (Fake-`BrokerAdapter`, echte DB via
`session`-Fixture):
1. `read_portfolio_risk_state` liefert `equity_usd`/`cash_usd` aus
   `adapter.get_account_balance()`.
2. `open_positions_count == len(adapter.get_positions())`.
3. Ohne vorhandene `portfolio_snapshot`-Historie → `peak_equity_usd == equity_usd`
   (Kaltstart-Fallback).
4. Mit einer historischen `portfolio_snapshot`-Zeile, deren `total_value` **über**
   der aktuellen Equity liegt → `peak_equity_usd` = der historische (höhere) Wert.
5. `trades_today_count` zählt nur `order_record`-Zeilen von heute für dieses
   Portfolio, ignoriert andere Portfolios und andere Tage.
6. Ein `hold`/`reject_idea`-`decision` ohne zugehörigen `order_record` zählt nicht
   als Trade.

## 4. Implementierung

`src/orchestrator/risk_inputs.py`: `PortfolioRiskState`, `read_portfolio_risk_state`.

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_risk_inputs.py -q` → 6 passed. `uv run pytest
-q -m 'not integration'` (Gesamtsuite) → 303 passed, 3 deselected. `uv run ruff
check`/`ruff format --check` → sauber. `uv run mypy src/orchestrator` → sauber.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert, kein Schema. Rollback =
Commit zurücknehmen — noch nichts ruft `read_portfolio_risk_state` in Produktion auf
(das kommt erst mit dem Persona-Analyse-Agenten).
