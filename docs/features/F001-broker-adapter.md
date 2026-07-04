# F001 — BrokerAdapter Protocol + AlpacaPaperAdapter (native Personas)

Status: abgeschlossen
Datum: 2026-07-04, aktualisiert 2026-07-05
Phase: 2

## 1. Zieldefinition

Ein `BrokerAdapter`-Protocol (`src/broker/protocol.py`) plus eine erste konkrete
Implementierung `AlpacaPaperAdapter` (`src/broker/alpaca_paper.py`) für die 3 nativen
Alpaca-Paper-Accounts (VULTURE, GUARDIAN, CHARTIST; siehe
[ADR-0001](../adr/0001-alpaca-paper-account-limit.md)). Ziel: Order platzieren (inkl.
verpflichtendem GTC-Stop-Loss), Positionen abfragen, Kontostand abfragen, Order stornieren —
gekapselt hinter einem Protocol, damit später kein Agent-/UI-Code Alpaca direkt anspricht
(ARCHITECTURE.md §3.1/§9). Eine `registry.py` löst `persona -> BrokerAdapter`-Instanz über
Config + Environment-Variablen auf.

**Nicht Teil dieses Features** (bewusst abgegrenzt, Folgearbeit):
- `InternalLedgerAdapter` für die 3 virtuellen Personas (HYPE, CONTRA, CRYPTOR) — eigenes
  Feature, da es eine Fill-/Slippage-Simulation braucht (siehe ADR-0001-Konsequenzen).
- Persistenz in `order_record`/`decision` (DB-Schema existiert noch nicht) — der Adapter
  verlangt zwar eine `decision_id` als Pflichtparameter (siehe unten), schreibt aber selbst
  nichts in die DB.
- Handels-Agent / LangGraph-Anbindung — existiert noch nicht.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate deterministisch | indirekt | Adapter trifft keine Risk-Entscheidungen, nimmt nur fertige Order-Parameter entgegen. Kein LLM ruft diesen Code in diesem Feature auf. |
| #2 Privilege Separation | nein (noch) | Adapter kennt keine Rollen; Durchsetzung "nur Handels-Agent" ist Aufgabe der späteren Agenten-Schicht. |
| #3 Keine Order ohne persistierte Decision | ja | `place_order()` verlangt `decision_id: int` als Pflichtparameter (kein Default) — auch wenn `order_record` als Tabelle noch nicht existiert, verhindert die Signatur schon jetzt "Order aus Freitext ohne Decision-Referenz". |
| #4 GTC-Stop-Loss beim Broker | ja | `place_order()` verlangt `stop_loss_price: float` als Pflichtparameter (kein Fire-and-Forget-Kauf ohne Stop möglich). **Korrigiert nach Integrationstest (siehe §5):** ursprünglich als zwei getrennte Orders geplant (Market-Entry + separate GTC-Stop-Order) — das lehnt Alpaca real als "potential wash trade" ab, sobald die Entry-Order noch nicht gefüllt ist (z. B. Markt geschlossen). Jetzt eine **OTO-Order** (`order_class=OrderClass.OTO`, Stop als Child-Leg), die Alpaca selbst erst nach Fill aktiviert — passt auch inhaltlich besser zur Invariante (ein Stop schützt erst eine tatsächlich existierende Position). |
| #5 Paper/Live-Trennung | ja | `AlpacaPaperAdapter` instanziiert `TradingClient` ausnahmslos mit `paper=True`. Kein Live-Pfad in diesem Feature; `AlpacaLiveAdapter` existiert nicht. |
| #6 Secrets nie im Repo | ja | Keys ausschließlich aus Environment (`ALPACA_PAPER_<PERSONA>_KEY_ID/SECRET_KEY`, bereits in `.env`, gitignored). Kein Hardcoding, kein Default. |
| #10 Fairness | ja | Alle 3 nativen Adapter-Instanzen laufen durch identischen Code-Pfad; kein persona-spezifisches Verhalten im Adapter selbst. |

**Kosten:** keine LLM-Calls, kein Einfluss auf `cost_ledger`.
**Fairness:** kein Informationsvorteil — der Adapter kapselt nur Order-I/O, keine Analyse.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/broker/`), Alpaca-Client vollständig gemockt, keine Netzwerkzugriffe:

1. `place_order` ohne `decision_id` oder ohne `stop_loss_price` → `TypeError` (Pflichtparameter).
2. `place_order` mit gültigen Parametern → ein `submit_order`-Aufruf am gemockten Client:
   OTO-Order (korrekt Symbol/Qty/Side, `time_in_force=GTC`, `stop_loss.stop_price` korrekt),
   Stop-Order-ID wird aus `entry.legs[0].id` extrahiert.
3. `get_positions()` normalisiert Alpaca-`Position`-Objekte in eigene `Position`-Dataclass.
4. `get_account_balance()` normalisiert Alpaca-`TradeAccount` in eigene `AccountBalance`-
   Dataclass (cash, equity, buying_power).
5. `cancel_order(order_id)` ruft `cancel_order_by_id` mit korrekter ID auf.
6. `AlpacaPaperAdapter.__init__` instanziiert `TradingClient` immer mit `paper=True`.
7. Registry: `get_adapter("VULTURE")` liefert `AlpacaPaperAdapter` mit den Keys aus
   `ALPACA_PAPER_VULTURE_KEY_ID/SECRET_KEY` (Env gemockt via `monkeypatch`).
8. Registry: unbekannte Persona → `ValueError`.
9. Registry: virtuelle Persona (z. B. `HYPE`) → `NotImplementedError` mit klarer Meldung
   (`InternalLedgerAdapter` existiert noch nicht) statt stillem Fallback auf Alpaca.

Integrationstest (separat markiert, `@pytest.mark.integration`, übersprungen wenn Keys
fehlen — DoD-Punkt "Integrationstest läuft in CI gegen Alpaca-Paper", ARCHITECTURE.md
Phase-2-DoD): 1 Aktie Market-Buy + GTC-Stop auf dem echten VULTURE-Paper-Account platzieren,
Order-Status abfragen, danach Position + offene Stop-Order wieder glattstellen. Da ein
Market-Order außerhalb der NYSE-Handelszeiten nicht sofort füllt, prüft der Test nur, dass
Alpaca die Order **akzeptiert** (nicht `rejected`/`expired`) — ein tatsächlicher Fill wird
nur verifiziert, wenn der Markt gerade offen ist.

## 4. Implementierung

Siehe `src/broker/protocol.py`, `src/broker/alpaca_paper.py`, `src/broker/registry.py`,
`config/broker.yaml`.

## 5. Testdurchlauf

`uv run pytest tests/broker/ -v --cov=src/broker` → grün, 100 % Line-Coverage
(`src/broker/alpaca_paper.py`, `protocol.py`, `registry.py`). `uv run ruff check src/broker`
und `uv run mypy src/broker` (strict, per `pyproject.toml`-Override) → beide sauber.

**Integrationstest gegen den echten VULTURE-Paper-Account durchgeführt (2026-07-05).**
Erster Versuch mit BTC/USD (24/7-Handel, unabhängig von NYSE-Zeiten) deckte zwei echte
Alpaca-API-Restriktionen auf: Krypto lehnt `time_in_force=day` ab ("invalid crypto
time_in_force") und Krypto akzeptiert generell keine `stop`-Orders ("invalid order type
for crypto order"). Da `AlpacaPaperAdapter` ohnehin nur von den Aktien-Personas
(VULTURE/GUARDIAN/CHARTIST) genutzt wird, wurde der Test auf AAPL umgestellt — dabei ein
dritter, wichtigerer Fund: Eine separate Stop-Order direkt nach der (noch offenen)
Entry-Order einreichen wird von Alpaca als **"potential wash trade"** abgelehnt. Fix: OTO-
Order (Stop als Child-Leg, siehe §2) statt zwei getrennter `submit_order`-Aufrufe. Danach
lief der Integrationstest sauber durch (Order akzeptiert, GTC-Stop als Child-Leg platziert,
Cleanup via `cancel_order` + `close_position`).

Nicht ausgeführt: derselbe Testlauf **in CI** (GitHub Encrypted Secrets) — Folgearbeit,
siehe CI-Workflow-Einrichtung (Phase-2-DoD-Punkt, in Arbeit).

## 6. Rollback-Pfad

Rein additives Feature: neue Dateien in `src/broker/`, `config/broker.yaml`, `tests/broker/`.
Kein bestehender Code wird geändert, nichts importiert dieses Modul bisher (kein Agent
existiert noch). Rollback = Commit/Dateien zurücknehmen, kein Config-Flag nötig.
