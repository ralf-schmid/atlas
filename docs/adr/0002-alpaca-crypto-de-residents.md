# Alpaca-Krypto live nicht für DE-Residents verfügbar — CRYPTOR live via Kraken-Adapter

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-04
* Betrifft Invariante(n): keine direkt (Broker-Wahl), aber relevant für #5
  (Paper/Live-Trennung) und §7 Steuer-Gotcha (§23 EStG, FIFO)

## Kontext und Problemstellung

ARCHITECTURE.md §3.1/§7.2/§4.6 markierte als offenen Punkt: "ob CRYPTOR live über Alpaca
oder einen Kraken-Adapter handelt, wird in P2 verifiziert." Alpacas öffentliche
Support-Doku (`alpaca.markets/support/what-regions-support-cryptocurrency-trading`) listet
die für Krypto-Handel zugelassenen Jurisdiktionen. Deutschland ist **nicht** in dieser
Liste enthalten; es gibt auch keinen EU-/EEA-Mitgliedsstaat in der Liste. Die Seite endet
mit: "We're working to broaden our eligibility criteria to more jurisdictions so stay
tuned!" — also aktuell bestätigt nicht verfügbar, ohne festen Termin für eine Änderung.

Paper-Krypto-Handel über Alpaca ist von dieser Einschränkung nicht betroffen (funktioniert
unabhängig vom Wohnsitzland, wie bereits in ARCHITECTURE.md Zeile 122 vermerkt) — die
Restriktion gilt nachweislich nur für die Live-Phase.

## Entscheidungstreiber

* CRYPTOR muss nach der 8-Wochen-Kür ggf. live handeln können (falls CRYPTOR gewinnt)
* Keine Live-Krypto-Keys/-Trading vor Verifikation der rechtlichen Zulässigkeit (Invariante 5)
* Bereits vorgesehener Fallback in ARCHITECTURE.md: Kraken-Adapter
* `BrokerAdapter`-Protocol soll den Wechsel ohne Agent-/UI-Code-Änderungen erlauben

## Betrachtete Optionen

* Abwarten, bis Alpaca Deutschland/EU für Krypto freischaltet (kein fester Termin bekannt)
* Kraken-Adapter für CRYPTOR-Live implementieren, Alpaca bleibt Broker für die anderen 5
  Personas (Aktien) sowie für CRYPTOR-Paper
* CRYPTOR aus der Live-Kür ausschließen

## Entscheidung

Gewählt: **Kraken-Adapter für CRYPTOR-Live**, Alpaca bleibt für Paper-Phase (alle Personen)
und Live-Aktienhandel (alle Nicht-Krypto-Personas). Abwarten wurde verworfen, da kein
Termin für eine Alpaca-Änderung absehbar ist und das Projekt nicht auf eine unklare
externe Zeitschiene warten soll. CRYPTOR-Ausschluss aus der Live-Kür wurde verworfen, weil
er die Wettbewerbsregeln (ARCHITECTURE.md §4.7) verzerren würde — alle 6 Personas müssen
grundsätzlich live gehen können, sonst verliert das Kriterium seinen Sinn.

### Konsequenzen

* Gut, weil die Paper-Phase unverändert komplett auf Alpaca läuft (kein Sonderfall vor P6).
* Gut, weil CRYPTOR weiterhin für die Live-Kür in Frage kommt.
* Schlecht, weil ein zweiter Broker-Adapter (`KrakenAdapter`) implementiert und getestet
  werden muss, nur für den Fall, dass CRYPTOR gewinnt (Aufwand ggf. "for nothing", falls
  eine Aktien-Persona gewinnt) — vertretbar, da `BrokerAdapter`-Pattern genau dafür gebaut
  ist und der Adapter ohnehin laut ARCHITECTURE.md §9 vorgesehen war.
* Schlecht, weil Kraken andere Order-Typen/Limits/Gebührenstruktur hat als Alpaca — Risk-Gate
  (Invariante 1) und Slippage-Malus (§Entscheidungsstand 8) müssen ggf. Kraken-spezifische
  Parameter bekommen.
* Folgearbeit:
  * `KrakenAdapter` erst bauen, wenn absehbar ist, dass CRYPTOR tatsächlich in die
    Live-Kür kommt (kein Vorzieh-Aufwand ohne Bedarf, Phasenmodell beachten) — ADR hier
    dokumentiert nur die **Entscheidung**, nicht die Implementierung.
  * Steuer-Gotcha im Blick behalten: Krypto = §23 EStG, FIFO, 1-Jahres-Haltefrist (bereits
    in ARCHITECTURE.md Zeile 285 vermerkt) — Lot-Tracking-Datenmodell nötig, sobald
    CRYPTOR live geht, unabhängig vom gewählten Broker.
  * Diese Erkenntnis (keine feste Freischaltung in Sicht) in P6-DoD als Prüfpunkt vor
    Live-Gang von CRYPTOR aufnehmen: erneut verifizieren, ob Alpaca inzwischen DE/EU für
    Krypto freigeschaltet hat, bevor der Kraken-Adapter final gewählt wird.

## Pro/Contra der Optionen

### Abwarten auf Alpaca

* Gut, weil kein zweiter Adapter nötig wäre
* Schlecht, weil kein Termin bekannt ist — Projektplanung (8-Wochen-Kür, danach Live) kann
  nicht auf eine unklare externe Änderung warten

### Kraken-Adapter (gewählt)

* Gut, weil CRYPTOR live-fähig bleibt, ohne von Alpacas Zeitplan abhängig zu sein
* Schlecht, weil zusätzlicher Implementierungs- und Testaufwand für einen zweiten Broker

### CRYPTOR aus Live-Kür ausschließen

* Gut, weil kein zweiter Adapter nötig wäre
* Schlecht, weil es die Fairness/Vergleichbarkeit des Wettbewerbs (§4.7) verletzt
