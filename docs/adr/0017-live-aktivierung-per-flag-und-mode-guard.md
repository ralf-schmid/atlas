# Live-Handel wird per Environment-Flag aktiviert, nicht per Config-Eintrag — plus Mode-Guard im Order-Pfad

* Status: accepted
* Deciders: Ralf Schmid (Vorbereitung durch Claude, 2026-09-05 — Aktivierung selbst bleibt Ralfs Entscheidung)
* Datum: 2026-09-05
* Betrifft Invariante(n): #5 (Paper/Live-Trennung), berührt #2 (Privilege Separation) und #4 (Stop-Loss) nicht

## Kontext und Problemstellung

Phase 6 braucht einen Live-Adapter. Invariante #5 verlangt, dass Live-Credentials
vor Phase 6 in keiner Umgebung existieren und dass es keinen Fallback-Default gibt.
Offen war, wie der Live-Pfad im Code vorbereitet werden kann, ohne dass er
versehentlich erreichbar wird — bis heute prüfte **kein** Code im Order-Pfad
`portfolio.mode`, weil es schlicht nichts Live-fähiges zu verwechseln gab.

## Entscheidungstreiber

* Der Order-Pfad ist gegen einen echten Broker gehärtet; eine zweite
  Implementierung für Live wäre die schlechtere Variante an der teuersten Stelle.
* Eine einzelne Zeile Config (`adapter: alpaca_live`) darf nicht ausreichen, um
  echtes Geld zu bewegen.
* Der umgekehrte Fehler (Live-Portfolio am Paper-Konto) ist genauso schädlich und
  fällt ohne Prüfung erst beim Steuer-Export auf.

## Betrachtete Optionen

* Live-Adapter erst in P6 schreiben (nichts vorbereiten)
* Live-Adapter als eigenständige Klasse mit kopiertem Order-Pfad
* Live-Adapter als Subclass des Paper-Adapters, Aktivierung über ein
  Environment-Flag, zusätzlich ein Mode-Guard in `execute_decision`

## Entscheidung

Gewählt: **Subclass + Flag + Mode-Guard** (F122). `AlpacaLiveAdapter` überschreibt
genau ein Klassenattribut (`_paper = False`) und erbt den vollständigen,
erprobten Order-Pfad inklusive Bracket-Stop. Erreichbar wird er nur, wenn drei
unabhängige Bedingungen zusammenkommen: ein `adapter: alpaca_live`-Eintrag in
`config/broker.yaml`, Live-Keys im Environment und
`ATLAS_LIVE_TRADING_ENABLED=true`. Zusätzlich lehnt `execute_decision` jede Order
ab, bei der `portfolio.mode` und der Modus des Adapters auseinanderfallen.

### Konsequenzen

* Gut, weil die Aktivierung eine bewusste Handlung bleibt und keine Nebenwirkung
  eines Config-Edits ist.
* Gut, weil Live denselben getesteten Order-Pfad benutzt wie Paper — inklusive
  Pflicht-Stop (Invariante #4).
* Gut, weil der Mode-Guard beide Fehlrichtungen abfängt, nicht nur die teure.
* Schlecht, weil `AlpacaLiveAdapter` von einer Klasse namens `AlpacaPaperAdapter`
  erbt — die Vererbung ist inhaltlich richtig, der Name des Basistyps liest sich
  falsch. Eine spätere Umbenennung in einen neutralen Basistyp bleibt möglich.
* Folgearbeit: Live-Portfolio-Anlage (`mode=live`) im Seed, Entscheidungen zu
  Kontowährung und Positionsgröße bei 2.000 € (siehe `docs/dod/phase-6.md` §5),
  und — falls CRYPTOR gewinnt — ein Kraken-Adapter nach ADR-0002.

## Pro/Contra der Optionen

### Erst in P6 schreiben

* Gut, weil garantiert nichts vorbereitet herumliegt.
* Schlecht, weil der Live-Start dann unter Zeitdruck an Code hängt, der noch nie
  gelaufen ist — genau die Situation, in der Fehler mit echtem Geld passieren.

### Eigenständige Klasse mit kopiertem Order-Pfad

* Gut, weil Paper und Live sich technisch nicht beeinflussen können.
* Schlecht, weil jede Härtung (F052, F077, F079, F027) doppelt gepflegt werden
  müsste und die weniger getestete Kopie ausgerechnet die mit echtem Geld wäre.
