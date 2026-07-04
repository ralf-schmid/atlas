# Alpaca begrenzt Paper-Accounts pro Login auf 3 — Hybrid-Modell (3 nativ + 3 virtuell)

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-04
* Betrifft Invariante(n): #4 (Stop-Loss als GTC-Order), #10 (Fairness des Experiments)

## Kontext und Problemstellung

ARCHITECTURE.md §3.1/§7.2 sah als Zielbild einen Alpaca-Paper-Account je Persona (6 Stück)
vor, mit einem geprüften Fallback (interner Ledger mit virtuellen Sub-Portfolios), falls
Alpaca die Anzahl begrenzt. Spike durchgeführt: im Alpaca-Dashboard
(`app.alpaca.markets/dashboard/overview` → Account-Switcher → "New Paper Account") zeigt
der Erstellungs-Dialog explizit:

> "Create a new paper account to simulate trades and test strategies. **You can have up to
> 3 paper accounts.**"

Damit ist die Zahl 6 nicht erreichbar; es braucht ein Hybrid-Modell.

## Entscheidungstreiber

* Zielbild "1 Broker-Account je Persona" für saubere Cash-/Fill-Trennung (§3.1)
* Invariante 10 (Fairness): kein Feature darf einer Persona einen Informations- **oder
  Modellierungsvorteil** verschaffen — native Broker-Fills vs. simulierte Fills dürfen sich
  nicht systematisch unterscheiden
* Invariante 4: jede Position braucht einen GTC-Stop-Loss beim Broker, nicht nur lokal —
  bei virtuellen Accounts gibt es keinen Broker, der das durchsetzt
* Aufwand: `BrokerAdapter`-Protocol soll beide Varianten kapseln, ohne Agent-/UI-Code zu
  verzweigen (bereits so in ARCHITECTURE.md §9 angelegt)

## Betrachtete Optionen

* Alle 6 Personas virtuell (interner Ledger, konsistente Modellierung)
* 3 Personas nativ auf echten Alpaca-Paper-Accounts, 3 Personas virtuell auf internem Ledger
* Mehrere Alpaca-Logins (zusätzliche E-Mail-Adressen) für weitere native Accounts

## Entscheidung

Gewählt: **3 nativ + 3 virtuell**, weil es sowohl echte Broker-Mechanik (Fills, Order-Typen,
API-Verhalten) im Projekt belässt als auch das 6-Personas-Ziel ohne Mehrfach-Logins erreicht.
Mehrfach-Logins wurden verworfen (ToS-Risiko, zusätzlicher KYC-/Support-Aufwand, kein
Lerneffekt). Volles Virtualisieren wurde verworfen, weil dann nirgends im Projekt echte
Broker-Order-Mechanik getestet würde.

### Konsequenzen

* Gut, weil das Ziel "6 Personas parallel" ohne Mehrfach-Konten/ToS-Risiko erreicht wird.
* Gut, weil weiterhin mindestens 3 Personas echte Alpaca-Order-/Fill-Mechanik durchlaufen
  (Wert für den Lerneffekt, §Projektkontext).
* Schlecht, weil zwei unterschiedliche Ausführungspfade gepflegt werden müssen
  (`AlpacaPaperAdapter` + neuer `InternalLedgerAdapter`).
* Schlecht, weil die Fairness (Invariante 10) aktiv sichergestellt werden muss:
  * Der `InternalLedgerAdapter` muss Fills **auf denselben Alpaca-Marktdaten** (Bid/Ask/Last)
    simulieren wie die native Order-Ausführung, mit vergleichbarer Fill-Logik ("sofort
    ausgeführt, sobald marketable" — analog zum bekannten Alpaca-Paper-Verhalten,
    ARCHITECTURE.md Zeile 245) und demselben Slippage-Malus-Mechanismus (§4.7-Kriterium 2),
    damit kein Account-Typ systematisch bessere/schlechtere Fills bekommt.
  * Der `InternalLedgerAdapter` muss Stop-Loss-Positionen selbst pro Zyklus prüfen und
    auslösen (deterministischer Code, kein LLM — Invariante 1), da kein Broker-GTC-Stop
    existiert. Das ist funktional äquivalent zu Invariante 4, aber technisch eine eigene
    Implementierung; muss in `src/risk`-Testabdeckung (100 % Branches) einbezogen werden.
* Folgearbeit:
  * `BrokerAdapter`-Registry (ARCHITECTURE.md §9) um `InternalLedgerAdapter` erweitern.
  * Zuordnung Persona → nativ/virtuell in Config (`config/personas/<name>.yaml` oder eigene
    Broker-Registry-Config), nicht hart codiert.
  * **Zuordnung (entschieden 2026-07-04):** nativ = VULTURE, GUARDIAN, CHARTIST;
    virtuell = HYPE, CONTRA, CRYPTOR. Begründung: CRYPTOR geht im Live-Fall ohnehin über
    den Kraken-Adapter ([ADR-0002](0002-alpaca-crypto-de-residents.md)), nicht über Alpaca —
    der Lerneffekt "reale Alpaca-Order-/Fill-Mechanik" wäre für CRYPTOR beim Live-Übergang
    hinfällig. Die 3 nativen Slots gehen deshalb an Personas, deren Live-Pfad (falls sie
    gewinnen) ebenfalls über Alpaca läuft, damit die Paper-Phase möglichst repräsentativ für
    ihren eigenen späteren Live-Broker ist.
  * Eval-Fixture/Test: Vergleichstest, der für dieselbe Order auf beiden Adaptern
    (simuliert) ein äquivalentes Fill-Ergebnis erwartet (Toleranzband dokumentieren).

## Durchführung (2026-07-04)

Die 3 nativen Accounts wurden im Alpaca-Dashboard angelegt:

| Persona  | Account-ID     | Startkapital | Shorting | Max Margin Multiplier |
|----------|----------------|--------------|----------|------------------------|
| VULTURE  | PA32N1PG3J5G   | $5.000       | aus      | 1 (kein Hebel)         |
| GUARDIAN | PA3NCUB9NOCJ   | $5.000       | aus      | 1 (kein Hebel)         |
| CHARTIST | PA3SLPCA9U5V   | $5.000       | aus      | 1 (kein Hebel)         |

Zwei zusätzliche Erkenntnisse aus der Durchführung, die diese ADR ergänzen:

* **Das 3-Account-Limit gilt inklusive bereits vorhandener Accounts.** Der ursprüngliche
  Default-Paper-Account (PA3VUAQVF0N4, $100.000, aus der Zeit vor diesem Projekt) zählte
  zum Limit und blockierte den dritten neuen Slot. Er wurde in "CHARTIST" umbenannt,
  anschließend gelöscht und mit denselben Einstellungen wie VULTURE/GUARDIAN neu angelegt
  (identisches Startkapital, damit kein Fairness-Unterschied durch abweichendes Kapital
  entsteht).
* **Alpaca-Paper-Accounts sind per Default Margin-Accounts mit Shorting.** Neu angelegte
  Accounts hatten "Shorting Enabled" = an und effektive Buying Power = 4× Cash (RegT-Margin).
  Das widerspricht der Architektur-Vorgabe "Kein Margin, kein Leverage, kein Short im
  Startumfang" (ARCHITECTURE.md §6.1, Zeile 361). Für alle 3 nativen Accounts wurde unter
  Account → Configure "Shorting Enabled" deaktiviert und "Max Margin Multiplier" auf **1**
  gesetzt (verifiziert über Balances: RegT Buying Power = Cash = $5.000, kein Hebel mehr).
  Das Risk-Gate (Invariante 1) bleibt die primäre Durchsetzung; diese Broker-Einstellung ist
  zusätzliche Absicherung auf Broker-Ebene (defense in depth), kein Ersatz dafür.

Die 3 virtuellen Personas (HYPE, CONTRA, CRYPTOR) benötigen keinen Alpaca-Account — deren
`InternalLedgerAdapter`-Implementierung ist Folgearbeit (siehe oben).

## Pro/Contra der Optionen

### Alle 6 virtuell

* Gut, weil maximale Konsistenz (keine Zwei-Klassen-Fairness-Diskussion nötig)
* Schlecht, weil kein Persona-Fluss die reale Broker-Mechanik testet
* Schlecht, weil mehr Eigenbau (Order-Simulation, Fill-Modell) für alle 6 statt für 3 nötig

### 3 nativ + 3 virtuell (gewählt)

* Gut, weil Broker-Realismus für die Hälfte der Personas erhalten bleibt
* Schlecht, weil Fairness zwischen den beiden Gruppen aktiv durch identische
  Marktdaten/Fill-Logik/Slippage-Malus hergestellt werden muss (siehe Konsequenzen)

### Mehrere Alpaca-Logins

* Gut, weil alle 6 Personas nativ liefen
* Schlecht, weil ToS-Grauzone (mehrere Accounts einer Person), zusätzlicher
  Verifizierungs-/Support-Aufwand, kein Lerneffekt gegenüber dem Broker-Adapter-Pattern
