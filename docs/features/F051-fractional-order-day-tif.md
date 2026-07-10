# F051 — Fractional Orders brauchen `DAY` statt `GTC` bei Alpaca

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Live-Fund beim ersten manuellen Anstoß von F050s neuem
`retry_stuck_decisions`-Sweep (Box, direkt nach dem F050-Deploy): beide
verwaisten Decisions (AAPL, ALDX) scheiterten diesmal an einer **anderen**
Alpaca-422: `{"code":42210000,"message":"fractional orders must be DAY
orders"}`. `AlpacaPaperAdapter.place_order` (`src/broker/alpaca_paper.py`)
setzt das Entry-Leg des OTO-Bracket-Orders fest auf `TimeInForce.GTC` — Alpaca
verlangt aber für Orders mit gebrochener Stückzahl zwingend `DAY`.

**Vermutlich ebenfalls seit Anfang an blockierend, unabhängig von F049/F050:**
`compute_position_value_usd` teilt einen USD-Betrag durch den Einstiegspreis
(`quantity = position_value_usd / entry_price`) — das Ergebnis ist so gut wie
nie eine ganze Aktienzahl. Praktisch jede reale `buy`-Decision der drei
nativen Alpaca-Personas (VULTURE, GUARDIAN, CHARTIST) hätte an dieser Regel
scheitern müssen, sobald sie den Broker überhaupt erreichte.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #4 Pflicht-Stop-Loss als GTC-Order beim Broker | ja, zentral geprüft | `time_in_force` wird nur auf dem **Entry**-Leg umgestellt (Markt-Order, füllt bei offenem Markt sofort — `DAY` vs. `GTC` ändert das Füllverhalten praktisch nicht). `StopLossRequest` hat in der Alpaca-SDK kein eigenes `time_in_force`-Feld; Alpaca hält Bracket-Exit-Legs unabhängig vom Entry-TIF grundsätzlich GTC. **Live an den beiden echten Orders verifiziert** (siehe §5) — der zurückgegebene Stop-Leg trägt weiterhin `time_in_force=gtc`. |
| Fairness | nein | Betrifft alle 3 nativen Personas gleich (gemeinsamer Adapter-Code), keine persona-spezifische Sonderbehandlung. |

**Kosten:** keine. **Design-Entscheidung:** `DAY` nur bei tatsächlich
gebrochener Stückzahl (`qty != int(qty)`), nicht pauschal für jede Order — hält
das Verhalten für ganzzahlige Stückzahlen (auch künftig denkbar, z. B. wenn
`compute_position_value_usd` irgendwann rundet) unverändert bei `GTC`.

## 3. Testdefinition

`tests/broker/test_alpaca_paper.py`: neuer Test reproduziert den echten Fall
(`qty=0.869813`, wie bei der echten AAPL-Decision) und prüft, dass das
Entry-Leg `time_in_force=day` gesetzt bekommt. Bestehender Test
(`test_place_order_submits_oto_bracket_with_gtc_stop_leg`, `qty=1`) bleibt
unverändert grün — ganzzahlige Order bleibt bei `GTC`.

## 4. Implementierung

`src/broker/alpaca_paper.py`: `entry_time_in_force = TimeInForce.DAY if qty
!= int(qty) else TimeInForce.GTC`, verwendet im `MarketOrderRequest` statt des
bisher festen `TimeInForce.GTC`.

## 5. Testdurchlauf

`uv run pytest tests/broker/test_alpaca_paper.py -q` → 15 passed (14
bestehende + 1 neuer). `uv run ruff check`/`ruff format --check` → sauber.
`uv run mypy src/broker` → sauber.

**Live-Nachprüfung (2026-07-10, UGREEN, echter Alpaca-Paper-Account) deckte
einen tieferliegenden, hiermit NICHT gelösten Blocker auf:** nach Deploy
`retry_stuck_decisions` erneut angestoßen — beide verwaisten Decisions
scheiterten diesmal an einer weiteren Alpaca-422:
`{"code":42210000,"message":"fractional orders must be simple orders"}`.
Alpaca lässt bei gebrochener Stückzahl offenbar **überhaupt keine
Bracket/OTO-Orders** zu (also auch mit `DAY` nicht) — nicht nur eine engere
TIF-Vorgabe, sondern ein struktureller Konflikt zwischen Invariante #4
(Pflicht-GTC-Stop beim Broker) und der Sizing-Formel
(`amount_usd / entry_price`, praktisch nie eine ganze Aktienzahl). Der
DAY-Fix in diesem Dokument bleibt notwendig (behebt den ersten der beiden
gefundenen Fehler), ist aber allein nicht ausreichend, um eine Order
durchzubringen. Siehe F052 für die Fortsetzung — dieser Punkt geht an Ralf,
da er Invariante #4 direkt berührt (Nicht-verhandelbar, "bei Konflikt:
nachfragen, nicht aufweichen").

## 6. Rollback-Pfad

Ein einziger geänderter Ausdruck (`time_in_force`) in einer reinen
Adapter-Methode — Commit zurücknehmen genügt, kein Schema-Change.
