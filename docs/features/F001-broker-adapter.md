# F001 — BrokerAdapter Protocol + AlpacaPaperAdapter (native Personas)

Status: in Umsetzung
Datum: 2026-07-04
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
| #4 GTC-Stop-Loss beim Broker | ja | `place_order()` verlangt `stop_loss_price: float` als Pflichtparameter (kein Fire-and-Forget-Kauf ohne Stop möglich). Implementiert als zwei getrennte Orders (Market-Entry + separate GTC-Stop-Order), nicht als Alpaca-Bracket-Order — einfacher zu testen/nachzuvollziehen als Parent-Child-Bracket-Semantik. Rein technische Entscheidung, hier dokumentiert statt eigenem ADR. |
| #5 Paper/Live-Trennung | ja | `AlpacaPaperAdapter` instanziiert `TradingClient` ausnahmslos mit `paper=True`. Kein Live-Pfad in diesem Feature; `AlpacaLiveAdapter` existiert nicht. |
| #6 Secrets nie im Repo | ja | Keys ausschließlich aus Environment (`ALPACA_PAPER_<PERSONA>_KEY_ID/SECRET_KEY`, bereits in `.env`, gitignored). Kein Hardcoding, kein Default. |
| #10 Fairness | ja | Alle 3 nativen Adapter-Instanzen laufen durch identischen Code-Pfad; kein persona-spezifisches Verhalten im Adapter selbst. |

**Kosten:** keine LLM-Calls, kein Einfluss auf `cost_ledger`.
**Fairness:** kein Informationsvorteil — der Adapter kapselt nur Order-I/O, keine Analyse.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/broker/`), Alpaca-Client vollständig gemockt, keine Netzwerkzugriffe:

1. `place_order` ohne `decision_id` oder ohne `stop_loss_price` → `TypeError` (Pflichtparameter).
2. `place_order` mit gültigen Parametern → genau zwei `submit_order`-Aufrufe am gemockten
   Client: Market-Entry (korrekt Symbol/Qty/Side) und GTC-Stop-Order (`time_in_force=GTC`,
   korrekter Stop-Preis).
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
Order-Status abfragen, danach Position + offene Stop-Order wieder glattstellen.

## 4. Implementierung

Siehe `src/broker/protocol.py`, `src/broker/alpaca_paper.py`, `src/broker/registry.py`,
`config/broker.yaml`.

## 5. Testdurchlauf

`uv run pytest tests/broker/ -v --cov=src/broker` → 12/12 grün, 100 % Line-Coverage
(`src/broker/alpaca_paper.py`, `protocol.py`, `registry.py`). `uv run ruff check src/broker`
und `uv run mypy src/broker` (strict, per `pyproject.toml`-Override) → beide sauber.

Nicht ausgeführt (kein Teil dieses Durchlaufs, siehe Testdefinition Punkt "Integrationstest"):
der Live-Smoke-Test gegen den echten VULTURE-Paper-Account — noch kein CI-Workflow
vorhanden, der die Keys aus GitHub Encrypted Secrets zieht. Folgearbeit für die
CI-Einrichtung (Phase-2-DoD-Punkt).

## 6. Rollback-Pfad

Rein additives Feature: neue Dateien in `src/broker/`, `config/broker.yaml`, `tests/broker/`.
Kein bestehender Code wird geändert, nichts importiert dieses Modul bisher (kein Agent
existiert noch). Rollback = Commit/Dateien zurücknehmen, kein Config-Flag nötig.
