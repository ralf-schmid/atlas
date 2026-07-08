# 0005 — Analysten-Rating-Historie für CONTRA vorerst zurückgestellt

* Status: accepted
* Deciders: Ralf Schmid, Claude Code
* Datum: 2026-07-08
* Betrifft Invariante(n): keine (reine Datenquellen-Entscheidung, kein Eingriff
  in Risk-Gate/Fairness)

## Kontext und Problemstellung

CONTRAs erster Live-Zyklus lehnte einen Trade explizit mit der Begründung ab,
es fehle eine "belastbare Analysten-Rating-Historie" (neben RSI/%-Rückgang,
die [F036](../features/F036-technical-indicator-research-items.md) inzwischen
liefert). Frage: Gibt es eine kostenlose, verlässliche Quelle für
Analysten-Rating-Verläufe (Upgrade-/Downgrade-Kaskaden), die sich in die
bestehende Ingestion-Architektur einfügt?

## Entscheidungstreiber

* Kein Feature soll eine erfundene/unzuverlässige Datenquelle vortäuschen, nur
  um CONTRAs Charter-Anforderung technisch "abzuhaken".
* Die im Projekt etablierten Kosten-Caps (5 €/Tag System, 120 €/Monat) sind für
  einen kostenpflichtigen Fundamentaldaten-Feed nicht vorgesehen.
* CONTRA soll trotzdem nicht komplett ohne Signal dastehen.

## Betrachtete Optionen

* Kostenpflichtiger Fundamentaldaten-Anbieter (Refinitiv/LSEG, S&P Capital IQ,
  Zacks, Benzinga Pro) — liefert Analysten-Rating-Historien flächendeckend.
* Gratis-Tiers von Finnhub/Alpha Vantage o. ä. — haben Analyst-Rating-Endpunkte,
  aber typischerweise stark rate-limitiert, lückenhaft oder US-fokussiert.
* Zurückstellen, kein Code — CONTRA nutzt vorerst nur RSI/%-Rückgang (F036).

## Entscheidung

Gewählt: "Zurückstellen, kein Code" — bis Ralf einen konkreten Anbieter mit
akzeptablen Kosten und ToS nennt, wird keine Analysten-Rating-Quelle gebaut.

### Konsequenzen

* Gut, weil keine unzuverlässige/instabile Gratis-Quelle ins System kommt, die
  später stillschweigend ausfällt oder CONTRA falsche Sicherheit vorgaukelt.
* Gut, weil CONTRA durch F036 (RSI < 30 auf Qualitätswerten) bereits ein
  echtes, neues Signal bekommt — nicht komplett blockiert.
* Schlecht, weil CONTRAs Charter-Anforderung "Downgrade-Kaskaden" vorerst
  unerfüllt bleibt.
* Folgearbeit: keine automatisch — **Revisit-Trigger:** sobald Ralf einen
  spezifischen Anbieter (kostenlos oder mit vertretbarem Preis) benennt, wird
  diese Entscheidung neu bewertet und ggf. ein neues Feature (F0NN) analog zu
  F035-F040 aufgesetzt.

## Pro/Contra der Optionen

### Kostenpflichtiger Anbieter

* Gut, weil vollständige, verlässliche Datenabdeckung.
* Schlecht, weil laufende Kosten außerhalb des bestehenden Cap-Modells
  (ARCHITECTURE.md §3.3.3/§6.3) — bräuchte eine eigene Budget-Entscheidung von
  Ralf.

### Gratis-Tier (Finnhub/Alpha Vantage)

* Gut, weil kostenlos, kein neuer Cap nötig.
* Schlecht, weil Rate-Limits/Lückenhaftigkeit nicht dem Anspruch "belastbar"
  genügen, den CONTRAs eigene Charter explizit fordert ("bis belastbarere
  quantitative Signale vorliegen").

### Zurückstellen

* Gut, weil ehrlich — kein Vortäuschen einer Datenquelle, die es nicht gibt.
* Schlecht, weil eine Charter-Anforderung offen bleibt.
