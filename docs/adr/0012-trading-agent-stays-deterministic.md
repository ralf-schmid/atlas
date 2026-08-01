# ADR-0012: Handels-Agent bleibt deterministisch (kein LLM)

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-31
* Betrifft Invariante(n): **#2** (Privilege Separation), **#3** (keine Order ohne
  persistierte Decision)
* Betrifft ARCHITECTURE.md **§5.1** (Rollenmodell)

## Kontext und Problemstellung

ARCHITECTURE.md §5.1 beschrieb den Handels-Agenten als „toolgesteuert,
minimal-LLM". Der Code ist es nicht: `src/orchestrator/trading.py` sagt in seinem
Modul-Docstring ausdrücklich

> „Takes an already-loaded, already-`APPROVED` `Decision` row (never free text,
> never an LLM response directly) and turns it into a real order + `order_record`."

Aufgefallen bei der Umsetzung von F095 („baue die Rollen so, wie sie dokumentiert
sind"). Die Doku war an dieser Stelle **schwächer als der Code** — ein Umbau auf
„minimal-LLM" hätte eine Sicherheitsinvariante aufgeweicht, um eine Doku-Zeile zu
erfüllen.

## Entscheidung

**Der Handels-Agent bleibt deterministisch.** ARCHITECTURE.md §5.1 wird auf
„kein LLM" korrigiert, der Code bleibt unverändert.

## Begründung

* **Kein funktionaler Gewinn.** Zum Zeitpunkt der Ausführung steht die Decision
  fest — Instrument, Aktion, Menge, Stop. Es gibt nichts zu entscheiden, nur
  auszuführen.
* **Invariante #2/#3 werden hier direkt in Code umgesetzt.** Ein LLM im
  Order-Pfad vergrößert die Angriffsfläche (Prompt Injection über Research-Text,
  der bis in die Thesis reicht) ohne Gegenwert.
* **Fehlersuche.** Ein deterministischer Ausführungspfad ist reproduzierbar; ein
  LLM-gesteuerter ist es nicht — bei Geld-Themen der ausschlaggebende Punkt.

## Konsequenzen

* §5.1 und der Code sagen wieder dasselbe.
* Sollte künftig doch Tool-Steuerung gewünscht sein (z. B. Order-Splitting über
  mehrere Tranchen), ist das ein eigenes Feature mit eigenem ADR — und muss
  weiterhin per `decision_id` gebunden bleiben, nie über Freitext.
