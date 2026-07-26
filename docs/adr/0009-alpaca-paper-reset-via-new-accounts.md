# Alpaca-Paper-Reset für den Wettbewerbsstart: neue Accounts statt In-Place-Reset

* Status: accepted — **umgesetzt 26.07.2026** (F090: 3 neue Accounts à 5.000,
  neue Keys/IDs, Reset gefahren, alle 6 Personas 5.000 flat verifiziert; Stichtag
  auf Mo 27.07.2026 vorgezogen)
* Deciders: Ralf Schmid
* Datum: 2026-07-26
* Betrifft Invariante(n): #5 (Paper/Live-Trennung), #10 (Fairness des Experiments)
* Betrifft: ARCHITECTURE.md §4.7 (Wettbewerbsstart), `docs/dod/phase-5.md`
  (offene Entscheidung #5, DoD "alle 6 Portfolios auf 5.000 USD"), F090
  (Wettbewerbs-Reset & offizieller Start), [ADR-0001](0001-alpaca-paper-account-limit.md)

## Kontext und Problemstellung

Der 8-Wochen-Wettbewerb startet am 03.08.2026 (phase-5.md), DoD-Punkt: **alle 6
Portfolios auf exakt 5.000 USD**. Für die 3 nativen Alpaca-Personas
(VULTURE, GUARDIAN, CHARTIST — die 3 virtuellen HYPE/CONTRA/CRYPTOR laufen auf dem
`InternalLedgerAdapter`, ADR-0001) war offen (phase-5.md Entscheidung #5), **ob
Alpaca einen Reset der bestehenden Paper-Accounts auf exakt 5.000 USD zulässt oder
ob neue Accounts nötig sind.** Spike am 26.07.2026 zur Klärung.

## Untersuchung (Spike 26.07.2026)

- **Ist-Stand der 3 nativen Accounts** (read-only `get_account_balance` über den
  laufenden Scheduler-Container, echte Keys): VULTURE equity 4945,11 / 3 offene
  Positionen; GUARDIAN 4992,56 / 1; CHARTIST 5087,50 / 2. Alle von 5.000 USD
  abgedriftet und **nicht flat** — ein Reset ist für den fairen Start zwingend.
- **Alpaca-Doku (`docs.alpaca.markets/us/docs/paper-trading`, Stand Juli 2026):**
  Der frühere In-Place-Reset ist **abgeschafft**. Die aktuelle Dashboard-Logik ist
  „create and delete paper accounts, rather than resetting them" — Paper-Account
  anlegen über „Open New Paper Account", Startkapital ist ein **frei wählbarer
  Betrag** (5.000 USD damit möglich). **Ein neuer Paper-Account bekommt zwingend
  neue API-Keys** (Doku: „generate new API keys for any newly created account").
- **Kein programmatischer Reset:** Die Trading API (`paper-api.alpaca.markets`,
  die dieses Projekt via `alpaca-py` nutzt) hat **keinen** Reset-/Recreate-Endpoint
  — Anlegen/Löschen ist Dashboard-only. Es gibt also keinen Code-Weg, den Claude
  automatisieren könnte.
- **Account-Limit (ADR-0001):** Alpaca erlaubt **max. 3 Paper-Accounts pro Login**.
  Da wir bereits 3 native Accounts nutzen, können **nicht** 3 zusätzliche neue
  parallel existieren — die alten müssen vor (bzw. je Persona unmittelbar vor) dem
  Anlegen des Ersatzes gelöscht werden.

## Entscheidung

Der F090-Reset der 3 nativen Alpaca-Accounts erfolgt durch **Löschen der alten und
Anlegen von 3 neuen Paper-Accounts mit je 5.000 USD Startkapital über das Alpaca-
Dashboard**, mit anschließender **Key-Rotation** in der Box-`.env`
(`ALPACA_PAPER_{VULTURE,GUARDIAN,CHARTIST}_KEY_ID` / `_SECRET_KEY`). Ein In-Place-
Reset (gleiche Keys, nur Cash zurück) ist von Alpaca nicht mehr angeboten und
damit keine Option.

Dies ist eine **manuelle Aufgabe von Ralf** — Claude kann keine Alpaca-Accounts
anlegen/löschen und keine API-Keys generieren (analog CI-Ruleset ADR-0007,
LiteLLM-Key-Budgets ADR-0008). Claude liefert den Klickpfad und übernimmt den
Code-/DB-seitigen Teil.

Die 3 virtuellen Personas (HYPE/CONTRA/CRYPTOR) werden **per Code** zurückgesetzt:
Neuinitialisierung des JSON-Ledgers auf `_STARTING_CASH = 5000.0`
(`src/broker/registry.py`, `JSONLedgerStore`) — kein externer Eingriff, kein
Account-Limit betroffen.

## Konsequenzen und F090-Folgearbeit

- **Gut:** Der einzige von Alpaca angebotene Weg führt zu einem sauberen,
  positionsfreien Start mit exakt 5.000 USD — genau der DoD-Zustand. Fairness
  (Invariante 10) bleibt gewahrt: native und virtuelle Personas starten identisch
  bei 5.000 USD, flat.
- **Reihenfolge/Timing (harte Abfolge wegen des 3-Account-Limits):** je Persona
  alten Account löschen → neuen mit 5.000 USD anlegen → neue Keys notieren; danach
  Box-`.env` aktualisieren und die betroffenen Container **neustarten** (die Keys
  kommen aus `.env`/Environment, **nicht** ins Image gebacken → Restart genügt,
  kein Rebuild). Vor dem 03.08.-Start abzuschließen.
- **Schlecht / zu beachten:** Die alten Broker-Accounts (samt Order-/Fill-Historie
  auf Alpaca-Seite) sind nach dem Löschen weg. Die Vorsaison-Daten in unserer
  Postgres-DB (Decisions, order_records, Snapshots) bleiben erhalten, referenzieren
  aber ab dem Reset broker-seitig nicht mehr existente Accounts — rein historisch,
  unkritisch für den Wettbewerb.
- **Offene F090-Detailentscheidungen (Ralf, nicht Teil dieses Spikes):**
  1. Umgang mit den Vorsaison-DB-Daten beim Reset — archivieren (eigene
     `portfolio`-Zeilen / Kennzeichnung „Vorsaison") oder belassen und ab Stichtag
     frisch zählen? Betrifft Leaderboard/§4.7-Auswertung.
  2. Ob die `portfolio`-/Snapshot-Historie der virtuellen Personas analog behandelt
     wird wie die der nativen (Konsistenz der Auswertung).
  3. Genauer Ablauf-Zeitpunkt am/vor dem 03.08. und wer den Dashboard-Teil wann
     ausführt.
- **Verifikation vor Ausführung:** Der konkrete Dashboard-Flow (Wortlaut,
  Mindest-/Standardbeträge) kann sich ändern — beim tatsächlichen Reset im Dashboard
  gegenprüfen, dass exakt 5.000 USD wählbar ist, bevor der alte Account gelöscht wird.

## Betrachtete Optionen

* **In-Place-Reset der bestehenden Accounts** (gleiche Keys, Cash zurück auf 5.000):
  von Alpaca nicht mehr angeboten → nicht möglich.
* **Neue Paper-Accounts mit 5.000 USD + Key-Rotation** (gewählt): einziger von
  Alpaca unterstützter Weg zu exakt 5.000 USD und flat.
* **Bestehende Accounts unverändert lassen und ab Ist-Stand starten:** verworfen —
  verletzt den DoD („alle 6 Portfolios auf 5.000 USD") und die Fairness (Personas
  starten mit unterschiedlichem Kapital/Positionen).
