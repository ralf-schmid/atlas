# Kosten-Caps in EUR spezifiziert, aber als USD-Zahlenwert durchgesetzt — bewusste Näherung, kein FX-Umrechnung

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-07
* Betrifft Invariante(n): #7 (Kosten-Caps doppelt durchgesetzt)

## Kontext und Problemstellung

Security-Audit 2026-07-07, Finding P7: CLAUDE.md spezifiziert die Kosten-Caps in
EUR (5 €/Tag System, 1 €/Tag je Persona, 120 €/Monat Soft-Cap), aber
`config/llm.yaml` (`system_daily_usd`, `persona_daily_usd`,
`monthly_soft_cap_usd`) und `cost_ledger.cost_usd` führen und vergleichen diese
Zahlen als USD — ohne Umrechnung wird aus "5 € Tages-Cap" faktisch "5 $
Tages-Cap" (aktuell ca. 8 % mehr Spielraum bei EUR/USD ≈ 1,08).

## Entscheidungstreiber

* Aufwand vs. Nutzen: ein FX-Umrechnungspfad (Live-Kurs holen, cachen,
  Rundungsverhalten bei Cap-Vergleichen definieren) für einen Cap, der laut
  CLAUDE.md ohnehin nur eine Sicherheitsmarge für ein Experiment mit eigenem Geld
  ist (keine Rechnungsstellung an Dritte, keine buchhalterische Genauigkeit
  nötig).
* LiteLLM selbst liefert Kosten nur in USD (`x-litellm-response-cost`,
  provider-nativ) — jede Umrechnung würde on top passieren, mit eigenem
  Kurs-Provider/Cache, zusätzlicher Fehlerquelle (Invariante 7 will *zuverlässige*
  Durchsetzung, nicht zusätzliche bewegliche Teile).
* Die Differenz ist zur Kappungs-Grenze hin sicherheitsseitig: bei aktuellem
  Kurs (EUR stärker als USD wäre der Extremfall) verschiebt sich der Cap nach
  oben (mehr Ausgaben zugelassen als die 5-€-Absicht), nie nach unten in einer
  Weise, die den Betrieb gefährden würde.

## Betrachtete Optionen

* FX-Umrechnung mit Live-Kurs (z. B. täglich gecachter EZB-Referenzkurs)
* FX-Umrechnung mit fest hinterlegtem Kurs (z. B. 1 EUR = 1.05 USD, periodisch
  manuell nachgezogen)
* Zahlenwerte unverändert als USD interpretieren, Diskrepanz dokumentieren
  (Status quo)

## Entscheidung

Gewählt: "Zahlenwerte unverändert als USD interpretieren", weil der Cap eine
Sicherheitsmarge für Ralfs eigenes Experiment ist, keine wirtschaftlich exakte
Buchhaltungsgröße — die reale Kostenkontrolle liegt im LiteLLM-Key-Budget (zweite
Ebene, Invariante 7) und im tatsächlichen `cost_ledger`, das die realen USD-Kosten
korrekt abbildet. Eine FX-Schicht würde Komplexität für eine Genauigkeit
hinzufügen, die hier nicht gebraucht wird.

### Konsequenzen

* Gut, weil keine zusätzliche Abhängigkeit (Kurs-API, Cache-Invalidierung,
  Rundungsregeln) in einem sicherheitskritischen Pfad.
* Schlecht, weil der tatsächliche Tages-Cap je nach Wechselkurs um wenige Prozent
  von der in CLAUDE.md genannten 5-€-Absicht abweicht — bei aktuellem Kurs nach
  oben (mehr Spielraum), was für ein Soft-Limit auf Experiment-Ebene akzeptabel
  ist.
* Folgearbeit: keine geplante Code-Änderung. Falls der Wechselkurs sich massiv
  verschiebt oder die Caps strenger eingehalten werden müssen, kann dieses ADR
  revidiert werden (`superseded by`).

## Pro/Contra der Optionen

### FX-Umrechnung mit Live-Kurs

* Gut, weil der Cap tatsächlich ~5 € entspricht, unabhängig vom Kurs.
* Schlecht, weil ein neuer externer Abhängigkeitspunkt in Invariante 7 (Kosten-Caps
  „doppelt durchgesetzt" soll robuster werden, nicht von einer dritten API
  abhängig).

### FX-Umrechnung mit fest hinterlegtem Kurs

* Gut, weil kein Live-Abruf nötig, geringe Komplexität.
* Schlecht, weil der Kurs veraltet, ohne dass es auffällt — falsche Genauigkeit
  vorgetäuscht (sieht exakt aus, ist es aber nicht).

### Status quo (Zahlenwerte als USD)

* Gut, weil einfachster, robustester Pfad — keine neue Fehlerquelle.
* Schlecht, weil die Doku (CLAUDE.md) und das tatsächliche Verhalten leicht
  auseinanderlaufen, wenn man es nicht kennt (durch dieses ADR jetzt explizit
  dokumentiert).
