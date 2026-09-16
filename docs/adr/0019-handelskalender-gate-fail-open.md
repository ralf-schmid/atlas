# ADR-0019: Handelskalender-Gate — Fail-open, kein Open-Check, nur Aktienzyklen

* Status: accepted — beauftragt von Ralf am 16.09.2026, umgesetzt als
  [F124](../features/F124-handelskalender-gate.md); per Config bis zur
  Endabrechnung am 18.09.2026 abgeschaltet
* Deciders: Ralf Schmid
* Datum: 2026-09-16
* Betrifft Invariante(n): **#10** (Fairness) — geprüft und neutral; **#7**
  (Kosten-Caps) — positiv. Keine wird aufgeweicht.
* Betrifft ARCHITECTURE.md **§5.2** (Zyklen): „Aktien: C1–C4, Mo–Fr" wird zu
  „an Handelstagen der NYSE, vor Börsenschluss"
* Vorgänger: [ADR-0018](0018-alpaca-newsletter-0926-nachbewertung.md) D.3

## Kontext und Problemstellung

Der Scheduler kennt den Börsenkalender nicht (`scheduler.py`, Cron
`day_of_week="mon-fri"`). An US-Feiertagen und an verkürzten Handelstagen laufen
Aktienzyklen ohne Marktbezug; dabei entstehende Orders werden bei Alpaca bis zur
nächsten Eröffnung gequeued und füllen zu einem Kurs, den die Entscheidung nie
gesehen hat. Fehlerbilder und Kostenwirkung: F124 §1.

`TradingClient.get_calendar` liefert die Handelstage samt Öffnungs- und
Schlusszeiten. Offen sind vier Entwurfsfragen, die sich nicht aus der API ergeben.

## Entscheidungstreiber

* Ein Gate, das fälschlich sperrt, ist im laufenden Wettbewerb teurer als eines,
  das fälschlich durchlässt — ein verlorener Handelstag ist nicht nachholbar.
* C1 liegt um 09:00 ET **absichtlich vor der Eröffnung** (ARCHITECTURE.md §5.2).
* Der Scheduler ist ein langlebiger Singleton-Prozess; Restarts sind selten.
* CLAUDE.md verlangt einen Rollback-Pfad, bevorzugt als Config-Flag.
* Invariante #10: kein Mechanismus darf eine Persona gegenüber einer anderen
  bevorzugen.

## Betrachtete Optionen

Vier unabhängige Fragen, je Frage die Alternativen:

* **(1) Verhalten bei nicht beschaffbarem Kalender:** fail-open | fail-closed
* **(2) Zeitprüfung:** „Session offen" (open ≤ t < close) | nur `t < close`
* **(3) Cache:** DB-Tabelle mit Refresh-Job | Prozess-Cache | kein Cache
* **(4) Geltungsbereich:** alle Scheduler-Jobs | nur US-Aktienzyklen

## Entscheidung

### (1) Fail-open

Gewählt, weil die beiden Fehlerrichtungen unterschiedlich viel kosten. Ein
fälschlich durchgelassener Feiertagszyklus kostet Cent-Beträge an LLM-Kosten und
im schlimmsten Fall eine gequeuete Order — sichtbar, korrigierbar, nicht
existenzgefährdend. Ein fälschlich gesperrter echter Handelstag kostet einen
Zyklus im laufenden Wettbewerb und fällt niemandem auf, weil ein nicht gelaufener
Zyklus keine Spur hinterlässt. Dazu kommt: Fail-open **ist** das heutige
Verhalten, das Gate kann damit nie schlechter sein als der Status quo.

Protokolliert wird der Fall als `WARNING` mit `reason="calendar_unavailable"`,
nicht als `ERROR` — der Zustand ist degradiert, nicht kaputt, und ein `ERROR` würde
im Log neben echten Zyklusfehlern stehen.

### (2) Nur `t >= close` prüfen

Gewählt, weil C1 um 09:00 ET per Design 30 Minuten vor der Eröffnung liegt: die
Persona analysiert die Vorbörse, die Order läuft in die Eröffnungsauktion. Ein
Open-Check würde C1 **jeden einzelnen Handelstag** abwürgen und damit ein Drittel
des Zyklusplans stilllegen — ein Feature, das den Scheduler repariert, indem es
ihn kaputtmacht. Der Close-Check dagegen greift genau dort, wo das reale Problem
sitzt (Half-Days), und an regulären Tagen nie.

Die Grenze ist `>=`, nicht `>`: ein Zyklus, der exakt zum Schlusskurs startet,
platziert seine Orders in einen bereits geschlossenen Markt.

### (3) Prozess-Cache mit 45-Tage-Fenster

Gewählt, weil der Handelskalender eines Datums unveränderlich ist — der klassische
Fall, in dem ein Cache keine Invalidierung braucht. Eine DB-Tabelle würde
Migration, Modell und Refresh-Job kosten und wäre nur dann überlegen, wenn der
Prozess ständig neu startet; das tut er nicht. Ein Dict überlebt genau so lange
wie der Scheduler, nach einem Restart kostet die Wiederbeschaffung einen Call.

Ein **fehlgeschlagener** Abruf wird ausdrücklich nicht gecacht: sonst würde ein
einzelner API-Aussetzer als „dieses Fenster hat keine Handelstage" hängenbleiben
und wochenlang jeden Zyklus sperren — die Fail-open-Entscheidung aus (1) wäre
damit unterlaufen.

### (4) Nur US-Aktienzyklen

Gewählt; die Begründung je Job steht in F124 §5. Kern: Krypto kennt keinen
Handelskalender, die Reporting-Jobs haben keinen Marktbezug, und die Sicherheits-
netze (HITL-Timeout, Stuck-Decision-Retry, Fill-Reconciliation) sollen gerade an
einem geschlossenen Markt weiterlaufen.

**Fairness-Prüfung (#10):** Das Gate wirkt auf den Zyklus, nicht auf eine Persona.
An einem Feiertag entfällt er für alle fünf Aktien-Personas gleichzeitig,
unabhängig davon, ob sie über einen nativen Alpaca-Account oder den internen
Ledger handeln. CRYPTOR behält seine Zyklen — nicht als Privileg, sondern weil der
Kryptomarkt an US-Feiertagen tatsächlich handelt.

### Konsequenzen

* Gut, weil ~10 Feiertage und ~3 Half-Days pro Jahr keine inhaltsleeren Zyklen und
  keine gequeueten Orders mehr erzeugen.
* Gut, weil das Gate rein deterministisch ist, kein LLM berührt und keinen
  Risk-Parameter anfasst.
* Gut, weil es die LLM-Kosten senkt, ohne eine Persona zu benachteiligen.
* Schlecht, weil Fail-open bedeutet: bei gleichzeitigem Ausfall von Cache und
  Alpaca-API bleibt das alte Fehlverhalten bestehen. Bewusst akzeptiert, sichtbar
  im Log.
* Schlecht, weil der Kalender aus einem Prozess-Cache kommt, dessen Zustand von
  außen nicht einsehbar ist — im Zweifel hilft nur das Log.
* Folgearbeit: Config-Flag `stock.calendar_gate` auf `true` setzen und die API neu
  bauen (Config ist ins Image gebacken), nach der Endabrechnung am 18.09.2026 —
  siehe F124 §6.

## Pro/Contra der wesentlichen Alternativen

### (1) Fail-closed statt fail-open

* Gut, weil eine unbekannte Kalenderlage konservativ als „nicht handeln"
  interpretiert würde — die vorsichtigere Haltung bei Geld.
* Schlecht, weil ein transienter API-Fehler damit still einen echten Handelstag
  löscht. Der Ausfall ist unsichtbar (kein Zyklus = keine Zeile, kein Alert), und
  im Achtwochen-Vergleich wiegt ein fehlender Zyklus schwerer als ein überflüssiger.

### (2) „Session offen" statt nur Close-Check

* Gut, weil es der intuitiv vollständigere Test ist.
* Schlecht, weil er C1 (09:00 ET, vorbörslich by design) täglich blockieren würde.
  Der Test wäre formal korrekt und fachlich falsch.

### (3) DB-Tabelle statt Prozess-Cache

* Gut, weil der Kalender damit auch in Grafana sichtbar wäre und Restarts nichts
  kosten.
* Schlecht, weil Migration, Modell, Refresh-Job und ein zweiter
  Freshness-Zustand für Daten anfallen, die sich nie ändern und deren
  Wiederbeschaffung einen einzigen API-Call kostet.
