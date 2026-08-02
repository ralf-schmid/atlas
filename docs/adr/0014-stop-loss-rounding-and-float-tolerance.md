# ADR-0014: Stop-Loss-Tick-Rundung richtungsbewusst, 1e-9-Toleranz im Fixed-Zweig

* Status: accepted
* Deciders: Ralf Schmid (umgesetzt von Claude, 02.08.2026)
* Datum: 2026-08-02
* Betrifft Invariante(n): **#1** (Risk-Gate ist deterministischer Code), **#4**
  (jede Position hat einen Stop-Loss als GTC-Order)
* Betrifft [F101](../features/F101-trade-activity-root-cause.md)

## Kontext und Problemstellung

Alle 5 Risk-Gate-Rejects der ersten Wettbewerbswoche (27.07.–02.08.2026) waren
keine echten Regelverstöße, sondern Artefakte der Stop-Preis-Rundung:

* `compute_stop_loss_price` rundet den Roh-Stop mit `round()` auf den
  Alpaca-Tick (0,01 USD ab 1 USD, sonst 0,0001 USD). Rundung **zur nächsten**
  Stufe verschiebt den Stop je nach Nachkommastelle nach oben *oder* unten — und
  damit in etwa der Hälfte der Fälle über die Policy-Grenze hinaus.
  Live: CONTRA/AUPH 12,631 → 12,63 = 15,007 % Verlust gegen 15 % Cap;
  CHARTIST/ADSK 214,9364 → 214,94 = 8,2668 % gegen einen 8,2684-%-Floor.
* Zwei VULTURE-Fälle trafen die Grenze exakt (0,76 → 0,57 bei 25 % Cap), und
  `(0.76 - 0.57) / 0.76` ergibt in IEEE-754 `0.25000000000000006`. Der ATR-Zweig
  des Gates trug für genau dieses Problem längst eine `- 1e-9`-Toleranz, der
  Fixed-Zweig nicht.

Nettoeffekt: das Gate lehnte Entscheidungen wegen einer Verletzung ab, die die
eigene Vorstufe erzeugt hatte. Da CLAUDE.md das Lockern von Risk-Regeln verbietet,
ist die Frage nicht „Toleranz ja/nein", sondern wo der Fehler korrekt sitzt.

## Entscheidung

1. **Die Rundung wird richtungsbewusst** (in der Sizing-Schicht, nicht im Gate):
   * Fixed-Policy (`max_loss_pct` = Obergrenze des Verlusts) → Stop wird
     **aufgerundet** (`ROUND_CEILING`), der Verlust bleibt damit ≤ Cap.
   * ATR-Policy (`floor_pct` = Mindestabstand) → Stop wird **abgerundet**
     (`ROUND_FLOOR`), der Abstand bleibt damit ≥ Floor.
   Die Rundung kann den Stop damit nur noch in die *konservative* Richtung
   verschieben. Gerechnet wird mit `Decimal`, nicht mit Float-Arithmetik.
2. **Der Fixed-Zweig des Gates bekommt dieselbe 1e-9-Toleranz wie der
   ATR-Zweig** (`actual_loss_pct <= max_loss_pct + 1e-9`).

## Begründung

* Punkt 1 ist keine Lockerung, sondern eine Verschärfung: der gerundete Stop
  liegt jetzt immer auf der regelkonformen Seite der Grenze, vorher konnte er
  auf beiden Seiten landen.
* Punkt 2 ist eine reine Repräsentationstoleranz. 1e-9 liegt sieben
  Größenordnungen unter einem Basispunkt — bei einem 5.000-USD-Depot und einer
  3-%-Position entspricht das einem Stop-Unterschied von unter 0,000002 USD. Ein
  materieller Regelverstoß (25,01 % gegen 25 % Cap) bleibt ein Reject; dafür gibt
  es einen expliziten Test.
* Die Alternative — Toleranz im Gate großzügiger wählen — wurde verworfen: sie
  hätte die Regel selbst aufgeweicht, statt die Ursache in der Rundung zu beheben.

## Konsequenzen

* Positiv: Ideen scheitern wieder an ihrer Substanz, nicht an der zweiten
  Nachkommastelle. Der Stop, der beim Broker landet, ist immer mindestens so eng
  bzw. mindestens so weit wie die Policy verlangt.
* Negativ: der reale Stop weicht um bis zu einen Tick vom rechnerischen Ideal ab
  — bewusst in die für die jeweilige Policy sichere Richtung.
* Branch-Coverage `src/risk` bleibt bei 100 %; die Grenzfälle (exakt auf der
  Grenze, ein Basispunkt darüber) sind beide getestet.
