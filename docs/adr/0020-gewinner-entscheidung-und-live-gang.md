# Gewinner-Entscheidung nach §4.7 und Weg in die Live-Phase

* Status: proposed — Entscheidung liegt bei Ralf
* Deciders: Ralf Schmid
* Datum: 2026-10-17
* Betrifft Invariante(n): #5 (Paper/Live-Trennung), #10 (Fairness) — je nach Option

## Kontext und Problemstellung

Der 8-Wochen-Wettbewerb (27.07.–18.09.2026) ist ausgewertet
([Endabrechnung](../reports/endabrechnung-2026-09-18.md),
[Abschlussbewertung](../reports/abschlussbewertung-2026-10-17.md)). Sieger nach
den vorab fixierten Kriterien (ARCHITECTURE.md §4.7) ist **CRYPTOR** (Score
0,909 vor CONTRA 0,547), in jeder geprüften Gewichtungsvariante. Der erste
P6-DoD-Punkt verlangt die Entscheidung als ADR.

Drei Befunde machen das mehr als eine Formalie:

1. Alpaca-Krypto ist für DE-Residents live nicht verfügbar
   ([ADR-0002](0002-alpaca-crypto-de-residents.md)). Für CRYPTOR gibt es heute
   keinen Live-Broker-Pfad; der vorbereitete `AlpacaLiveAdapter` (F122) deckt nur
   Aktien ab.
2. Das Ergebnis ist statistisch nicht von Null zu unterscheiden (95-%-Intervall
   CRYPTOR-Sortino ≈ −2,0 … +6,6), und keine Persona schlug SPY (+3,08 %).
3. CRYPTOR handelte 12-mal und war am Stichtag zu 93 % in Cash, laut
   [F120](../features/F120-guardian-cryptor-inaktivitaet.md) wegen der
   Research-Auswahl, nicht wegen seines Charters.

## Entscheidungstreiber

* §4.7: Kriterien sind vorab fixiert, kein Post-hoc-Auswählen
* Geld-Thema: 2 000 € echtes Kapital, keine stillen Annahmen
* Aufwand eines Kraken-Adapters gegenüber der Aussagekraft des Ergebnisses
* Paper-Feld läuft ohnehin weiter, Re-Evaluation ist vorgesehen (§4.7)

## Betrachtete Optionen

* **A** — CRYPTOR geht live, vorher Kraken-Adapter (oder Alpaca-DE-Krypto, falls
  inzwischen freigeschaltet)
* **B** — CRYPTOR als Sieger festhalten, Live-Gang vertagen; erst F120-Fixes und
  eine zweite Saison, danach erneute Kür
* **C** — CONTRA (Rang 2) geht live über den fertigen Alpaca-Live-Pfad

## Entscheidung

*Offen.* Claudes Empfehlung: **Option B** (Begründung: Abschlussbewertung §6).

### Konsequenzen

* A: regelkonform; neues Feature „Kraken-Adapter" inkl. Lot-Tracking (§23 EStG),
  Kraken-Gebühren im Malus-Modell, eigener Paper-Smoke-Test.
* B: regelkonform; P6-DoD-Punkt 1 erledigt, Punkte 2–5 ruhen; F120-Fixes und
  Saison-2-Planung werden die nächsten Arbeitspakete.
* C: Abweichung von §4.7, hier ausdrücklich zu begründen; Live-Gang über F122
  sofort vorbereitbar, offene Positionsgrößen-Entscheidung (phase-6.md §5.3).
