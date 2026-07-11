# aktienfinder-Screener als dynamische Kandidatenquelle statt statischer 6er-Liste

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-11
* Betrifft Invariante(n): #10 Fairness (Shared Research Pool)

## Kontext und Problemstellung

[F037](../features/F037-aktienfinder-candidate-list-and-scheduling.md) (2026-07-08)
entschied sich bewusst gegen einen echten Fundamental-Screener für aktienfinder:
"dafür bräuchte es einen kostenpflichtigen Datenanbieter [...] unverhältnismäßig
zum Ziel 'GUARDIAN bekommt überhaupt Daten'." Stattdessen: eine statische,
6 ISINs umfassende, von Ralf manuell gepflegte Liste.

Ralf (2026-07-11): *"6 aktienfinder Aktien ist viel zu wenig. Eigentlich möchte
ich gar keine Einschränkung, wenn es nicht anders geht brauchen wir min. 100
verschiedene Papiere. Ich habe ein kostenpflichtiges Abo von aktienfinder, wir
haben also genau die Daten, die wir benötigen. Vorherige Aussage ist
widerrufen. Nutze das Tool aktiv für die Suche nach der Anmeldung."*

Der Kostenblocker aus F037 existiert damit nicht mehr — Ralf hat bereits
Zugriff auf genau die Daten, die ein Fundamental-Screener bräuchte.

## Entscheidungstreiber

* Ralfs expliziter Widerruf der F037-Prämisse ("kein kostenpflichtiger
  Datenanbieter") — er hat den Zugriff bereits.
* Mindestens 100, möglichst mehr Wertpapiere als Kandidatenbasis.
* Keine unnötige Serverlast/Scrape-Zeit gegen einen fremden Dienst (auch bei
  bezahltem Zugriff bleibt Rücksichtnahme geboten).
* Invariante #10: keine Persona darf einen Informationsvorsprung bekommen —
  jede neue Quelle muss in den gemeinsamen Research-Pool fließen.

## Betrachtete Optionen

* **A — Statische Liste weiter von Hand erweitern** (z. B. auf 100 ISINs).
  Erfüllt die Zahl, aber keine Dynamik — genau das Wartungsproblem, das F037
  schon als Nachteil benannte ("wird von nichts automatisch erweitert").
* **B — Kompletten Screener-Grid abschöpfen** (alle ~7 800 getrackten Werte,
  78 Seiten). Maximale Abdeckung, aber unverhältnismäßige Scrape-Zeit/-Last
  für einen täglichen Job, und die meisten Zeilen sind ohnehin nicht
  Alpaca-handelbar (internationale Börsenplätze).
* **C — Paginierte Discovery mit Ziel-/Obergrenze, Regions-Vorfilter,
  Alpaca-Tradability als finaler Filter.** Gewählt.

## Entscheidung

Gewählt: **Option C**. Ein neuer Ingestion-Job
(`src/ingestion/aktienfinder_screener.py`) loggt sich ein, paginiert das
Screener-Tool-Grid (`/aktienfinder`, DataTables, live bestätigt: ISIN *und*
Ticker direkt im DOM jeder Zeile, ~65 weitere Spalten inkl. Kursziel,
Stabilitäts-Scores, KGV, Kursgewinn-Historie), sammelt Zeilen mit
`Region == "Nordamerika"` bis `target_candidates` (Default 150, Config)
erreicht oder `max_pages` (Default 10) ausgeschöpft ist, filtert das Ergebnis
gegen Alpacas echtes Tradable-Asset-Verzeichnis (dieselbe Quelle wie
VULTUREs Screener) und persistiert nur, was wirklich handelbar ist.

Beide Grenzen (`target_candidates`, `max_pages`) sind Config, keine
Konstanten — Ralfs "eigentlich keine Einschränkung" wird durch
Hochsetzbarkeit ohne Code-Änderung erfüllt, ohne dass ein einzelner
Scrape-Lauf standardmäßig alle 78 Seiten durchläuft.

### Konsequenzen

* Gut, weil GUARDIAN (und über den gemeinsamen Pool alle 6 Personas) jetzt
  routinemäßig 100+ statt 6 Kandidaten mit echten Preis-/Qualitätsdaten
  bekommt.
* Gut, weil kein manuelles Pflegen einer ISIN-Liste mehr nötig ist — die
  Liste aktualisiert sich täglich selbst.
* Gut, weil pro Kandidat kein Profilseiten-Besuch mehr nötig ist (Grid-Zeile
  liefert alle Felder) — schneller als ein äquivalent breiter Ausbau des
  bisherigen Per-ISIN-Deep-Grabs gewesen wäre.
* Schlecht, weil ein täglicher Login + mehrseitiger Scrape gegen Ralfs
  eigenen Account eine gewisse Fragilität gegenüber Layout-Änderungen der
  Fremdseite mitbringt (gleiches Risiko wie der bereits bestehende
  Deep-Grab-Pfad, F012).
* Folgearbeit: die bestehende 6er-`candidate_isins`-Liste (F037) bleibt für
  den tieferen Profilseiten-Grab (Dividenden-Historie, Screenshot-Beleg)
  bestehen — kein Widerspruch, beide Pfade sind komplementär. Der
  vorbestehende ISIN-vs-Ticker-Mismatch in diesem alten Pfad (`symbol` =
  ISIN statt Ticker, siehe [F067](../features/F067-aktienfinder-ticker-mapping.md))
  bleibt unangetastet als bekannter, separat zu behebender Punkt.

## Pro/Contra der Optionen

### A — Statische Liste erweitern

* Gut, weil einfachste Änderung.
* Schlecht, weil sie sich nicht selbst aktuell hält und Ralfs "keine
  Einschränkung"-Wunsch nicht wirklich erfüllt (Zahl bleibt hart codiert).

### B — Kompletten Grid abschöpfen

* Gut, weil maximale Abdeckung.
* Schlecht, weil ~7 800 Zeilen/78 Seiten für einen täglichen Job
  unverhältnismäßig sind und die meisten Zeilen ohnehin nicht
  Alpaca-handelbar sind (Zeitaufwand ohne Nutzen).

### C — Begrenzte, konfigurierbare Discovery (gewählt)

* Gut, weil skalierbar (Config-Wert hochsetzen) ohne Standardmäßig
  unverhältnismäßig zu sein.
* Gut, weil der finale Filter (Alpaca-Tradability) verhindert, dass
  nicht handelbare Kandidaten den Pool verwässern.
* Schlecht, weil zwei Konfigurationswerte (`target_candidates`, `max_pages`)
  gegeneinander abgewogen werden müssen, statt einer einzigen Zahl.
