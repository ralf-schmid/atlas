# F002 — InternalLedgerAdapter (virtuelle Personas)

Status: in Umsetzung
Datum: 2026-07-04
Phase: 2

## 1. Zieldefinition

`InternalLedgerAdapter` (`src/broker/internal_ledger.py`) implementiert das
`BrokerAdapter`-Protocol für die 3 virtuellen Personas (HYPE, CONTRA, CRYPTOR), die laut
[ADR-0001](../adr/0001-alpaca-paper-account-limit.md) keinen eigenen nativen
Alpaca-Paper-Account bekommen (3-Account-Limit). Statt eines Brokers führt der Adapter
selbst Buch (Cash, Positionen, offene Stop-Orders) und simuliert Fills auf Basis echter
Alpaca-Marktdaten — mit dem Ziel, dass die virtuellen Personas gegenüber den nativen weder
einen Vorteil noch einen Nachteil bei der Order-Ausführung haben (Invariante 10).

Ergänzt: `MarketDataProvider` (`src/broker/market_data.py`, Aktien- und Krypto-Variante) und
`LedgerStore` (`src/broker/ledger_store.py`, JSON-Persistenz je Persona).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate deterministisch | indirekt | Adapter trifft keine Risk-Entscheidungen, reine Order-Ausführung/Buchführung. |
| #3 Keine Order ohne persistierte Decision | ja | `place_order()` verlangt wie bei `AlpacaPaperAdapter` `decision_id` als Pflichtparameter. |
| #4 GTC-Stop-Loss beim Broker | **eingeschränkt, siehe unten** | Es gibt keinen Broker, der den Stop durchsetzt. Die Order wird als "pending stop" im Ledger-State gespeichert; `check_stop_orders()` prüft sie gegen den aktuellen Marktpreis und löst aus, wenn der Preis den Stop kreuzt hat. **Das ist nur eine Kontrolle pro Aufruf, keine kontinuierliche Überwachung** — zwischen zwei Aufrufen (praktisch: zwischen zwei Orchestrator-Zyklen) kann der Preis durchschießen, ohne dass ausgelöst wird. Das ist ein bekannter, in ADR-0001 bereits akzeptierter Trade-off des virtuellen Fallbacks (dort so beschrieben: "Stop-Loss-Positionen selbst **pro Zyklus** prüfen"), kein neuer Kompromiss. Der Orchestrator **muss** `check_stop_orders()` jeden Zyklus für jede virtuelle Persona aufrufen, sobald er existiert — das ist hier explizit als Folgearbeit vermerkt, nicht stillschweigend vorausgesetzt. |
| #6 Secrets nie im Repo | ja | Marktdaten-Keys aus Environment (`ALPACA_MARKET_DATA_KEY_ID/SECRET_KEY`), keine Hardcodierung. |
| #10 Fairness | ja | Fill-Logik mirrort das dokumentierte Alpaca-Paper-Verhalten ("Fill sobald marketable, ohne Liquiditätsprüfung", ARCHITECTURE.md Zeile 245): sofortiger Fill zum letzten Marktpreis (`Trade.price`), keine zusätzliche Spread-Simulation, die native Fills schlechter/besser aussehen ließe als virtuelle. Beide Adapter-Typen nutzen dieselbe öffentliche Alpaca-Marktdatenquelle. Der eigentliche Slippage-Malus (Über-/Unterschätzung von Paper-Fills gegenüber Realität) ist laut ARCHITECTURE.md §4.7/Phase 5 explizit eine **Review-Agent-Funktion post-hoc für alle Paper-Accounts gleichermaßen** (nicht Teil dieses Adapters) — hier nicht implementiert, da spätere Phase. |
| Startkapital-Parität | ja | Default-Startkapital 5.000 USD, identisch zu den nativen Accounts (ADR-0003), kein Fairness-Unterschied durch Kapital. |
| Kein Margin/Leverage/Short | ja | `buying_power == cash` immer (kein Hebel), analog zur Margin-Multiplier-1-Einstellung der nativen Accounts. Short wird nicht unterstützt (Positionen können nicht negativ werden) — Order, die eine Position ins Negative drehen würde, wird abgelehnt (`ValueError`), analog zu "Shorting Enabled = aus" bei den nativen Accounts. |

**Kosten:** keine LLM-Calls. Marktdaten-Abfragen sind bei Alpaca kostenlos (IEX-Feed).
**Fairness:** Marktdaten-Key ist bewusst persona-unabhängig (Wiederverwendung des
VULTURE-Schlüssels für reine Leseabfragen) — Marktdaten sind ohnehin für alle Personas
identisch (Shared Research Pool, Invariante 10), der verwendete Key ändert daran nichts.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/broker/`), Alpaca-Datenclient gemockt, keine Netzwerkzugriffe,
`LedgerStore` über `tmp_path`:

1. `place_order` ohne `decision_id`/`stop_loss_price` → `TypeError` (wie F001).
2. `place_order` (BUY) füllt sofort zum aktuellen Marktpreis, bucht Cash/Position korrekt,
   registriert einen "pending stop" mit Gegenseite (SELL) und GTC-Charakter.
3. `place_order`, das die Position ins Negative drehen würde (SELL ohne ausreichenden
   Bestand) → `ValueError` (kein Shorting).
4. `place_order` mit Ordergröße größer als verfügbares Cash → `ValueError` (kein Margin).
5. `check_stop_orders()` löst eine Sell-Order aus, wenn der aktuelle Marktpreis den
   Stop-Preis unterschritten hat; Position/Cash werden entsprechend gebucht, der Stop wird
   aus den pending stops entfernt.
6. `check_stop_orders()` löst **nicht** aus, wenn der Preis den Stop nicht erreicht hat.
7. `cancel_order(stop_order_id)` entfernt den pending stop, ohne die Position zu verändern.
8. `get_positions()` liefert Positionen mit `market_value`/`unrealized_pl`, berechnet aus
   aktuellem Marktpreis.
9. `get_account_balance()`: `buying_power == cash` immer (kein Hebel); `equity = cash +
   Summe(market_value)`.
10. Persistenz: zwei Adapter-Instanzen mit demselben `LedgerStore`+Persona sehen denselben
    Zustand (State übersteht "Neustart").
11. `MarketDataProvider`: Stock- und Crypto-Variante rufen den jeweils richtigen
    Alpaca-Data-Client-Endpoint auf und geben `Trade.price` als `float` zurück.
12. Registry: `get_adapter("HYPE")`/`"CONTRA"` (Stock) und `get_adapter("CRYPTOR")` (Crypto)
    liefern `InternalLedgerAdapter`-Instanzen mit dem passenden `MarketDataProvider`-Typ.

Kein Integrationstest gegen echte Alpaca-Marktdaten in diesem Schritt (analog F001 —
Folgearbeit für CI).

## 4. Implementierung

Siehe `src/broker/market_data.py`, `src/broker/ledger_store.py`,
`src/broker/internal_ledger.py`, Registry-/Config-Anpassung in `src/broker/registry.py`
und `config/broker.yaml`.

## 5. Testdurchlauf

`uv run pytest tests/broker/ -v --cov=src/broker` → 33/33 grün, **100 % Line-Coverage**
für das gesamte `src/broker`-Paket (inkl. F001). `uv run ruff check src/broker` und
`uv run mypy src/broker` (strict) → beide sauber.

Nicht ausgeführt: Integrationstest gegen echte Alpaca-Marktdaten (analog F001, Folgearbeit
für CI).

## 6. Rollback-Pfad

Additives Feature: neue Dateien in `src/broker/`, Erweiterung von `registry.py`/
`broker.yaml` (bisher `NotImplementedError` für virtuelle Personas → jetzt funktionsfähig).
Kein bestehender Code (F001/native Adapter) wird verändert. Rollback = Commit zurücknehmen;
`config/broker.yaml` könnte Personas notfalls einzeln zurück auf einen Platzhalter setzen,
ist aber nicht nötig, da nichts anderes dieses Modul bisher aufruft (kein Agent existiert).
