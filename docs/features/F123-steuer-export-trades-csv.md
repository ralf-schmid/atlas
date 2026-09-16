# F123 — Steuer-Export: realisierte Trades als CSV (FIFO)

Status: implementiert, gegen Paper-Daten prüfbar
Datum: 2026-09-05
Phase: 6 (DoD-Punkt „Steuer-Export (Trades-CSV für Anlage KAP) generierbar")

## 1. Zieldefinition

**Done heißt:** `scripts/export_trades.py --persona X --year 2026` erzeugt eine
CSV, in der jede realisierte Position mit Anschaffung, Veräußerung, Haltedauer und
Ergebnis auf einer Zeile steht — FIFO gematcht, ohne Handarbeit.

**Scope:** FIFO-Matching über gefüllte Orders, CSV im deutschen Format,
§-23-Kennzeichnung für Krypto innerhalb der Jahresfrist.
**Non-Scope:** die Steuererklärung. Kein Zeilenmapping auf Anlage KAP/SO, keine
Vorabpauschale, keine Verlustverrechnungstöpfe — und **keine
Währungsumrechnung** (s. §2).

## 2. Zwei bewusste Auslassungen

**Keine EUR-Umrechnung.** Alle Beträge stehen in der Kontowährung (USD bei
Alpaca), die CSV führt dafür eine Spalte `waehrung`. Welcher Kurs gilt —
EZB-Referenzkurs des Handelstages oder Monatsdurchschnitt der BMF-Liste — ist eine
steuerliche Entscheidung, und Geld-Themen werden hier nicht geraten (CLAUDE.md).
Die Umrechnung lässt sich später ohne Eingriff in dieses Modul ergänzen.

**Keine steuerliche Wertung.** `paragraph_23` markiert nur den Tatbestand, an dem
die Regel hängt: Krypto-Veräußerung innerhalb eines Jahres (§ 23 EStG, FIFO
vorgeschrieben) gegenüber Wertpapieren unter § 20. Wo eine Zeile in der Erklärung
landet, entscheidet der Steuerberater, nicht dieser Code.

FIFO ist dabei keine Wahl, sondern die gesetzliche Vorgabe für Krypto und die
Praxis der Broker-Lot-Buchhaltung für Aktien.

## 3. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| alle | nein | Reines Lesen über `order_record`/`decision`. Kein LLM (CLAUDE.md-Verbot, Finanz-Kennzahlen gehören in Code), keine Order, kein Risk-Parameter. |

**Datenlücken werden benannt, nicht verschluckt:** Ein Verkauf ohne passenden Kauf
in den Daten (denkbar bei Bestandsübernahme oder einem Datenverlust wie am
10.07.2026) landet in `TaxExport.unmatched` und wird vom CLI als Warnung
ausgegeben. Eine Steuer-CSV, die vollständig aussieht und es nicht ist, wäre der
gefährlichste mögliche Output dieses Moduls.

## 4. Testdefinition (vor der Umsetzung geschrieben)

`tests/metrics/test_tax_export.py`

1. FIFO nimmt das älteste Lot zuerst und teilt ein Lot, wenn der Verkauf kleiner
   ist als der Bestand.
2. `close` realisiert wie `sell` und verteilt seine Gebühren anteilig auf die
   verbrauchten Lots.
3. Offene Positionen erscheinen nicht.
4. Ein Verkauf ohne Kauf wird gemeldet (`unmatched`), nicht als Gewinn gebucht.
5. Krypto innerhalb der Jahresfrist ist als §-23-Fall markiert.
6. Das Exportfenster begrenzt die **Veräußerung**; die Anschaffung darf davor
   liegen und wird mit ihrem Originaldatum ausgewiesen.
7. CSV: `;` als Trenner, Dezimalkomma, Währung in jeder Zeile.

## 5. Rollback

Kein Rollback nötig — der Export ist ein reines Lese-Skript, das nichts im System
verändert und von keinem anderen Pfad aufgerufen wird.
