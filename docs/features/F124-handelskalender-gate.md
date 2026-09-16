# F124 — Handelskalender-Gate für die US-Aktienzyklen

Status: implementiert, **per Config noch aus** (`calendar_gate: false`) — Scharfschaltung
nach der Endabrechnung am 18.09.2026, siehe §6
Datum: 2026-09-16
Phase: 5+ (Betriebshärtung des Schedulers, ergänzt F025/F061)
Auslöser: Ralf, nach der Auswertung des Alpaca-Newsletters vom 16.09.2026
([ADR-0018](../adr/0018-alpaca-newsletter-0926-nachbewertung.md))

## 1. Zieldefinition

`src/orchestrator/scheduler.py` registriert die Aktienzyklen als Cron-Job mit
`day_of_week="mon-fri"` — und sonst nichts. Der Scheduler weiß nicht, ob die NYSE
an diesem Montag überhaupt öffnet.

**Zwei konkrete Fehlerbilder, beide heute aktiv:**

1. **Feiertage.** An Thanksgiving, Good Friday, Memorial Day, Independence Day,
   Labor Day, Juneteenth, MLK Day, Presidents' Day, Christmas, New Year's Day —
   rund zehn Tage im Jahr — laufen C1/C3/C4 gegen die Daten des Vortages. Jede
   dabei entstehende BUY-Decision wird bei Alpaca angenommen und bis zur nächsten
   Eröffnung **gequeued**: Fill und Pflicht-Stop entstehen dann zu einem Kurs, den
   die Entscheidung nie gesehen hat.
2. **Half-Days.** An verkürzten Tagen (Close 13:00 ET — Tag nach Thanksgiving,
   Heiligabend, oft 3. Juli) liegen **C3 (13:00) und C4 (15:15) hinter dem
   Schlusskurs**. Gleiches Problem, nur häufiger unbemerkt, weil der Tag ansonsten
   ein normaler Handelstag ist.

Dazu kommt der Nebeneffekt, der am billigsten zu beziffern ist: drei Zyklen × fünf
Aktien-Personas LLM-Kosten für Analysen, die per Konstruktion keinen neuen Input
haben.

**Done heißt:** Ein Aktienzyklus startet nur, wenn der Tag laut Alpaca-Handels-
kalender ein Handelstag ist **und** der Zyklus-Zeitpunkt vor dem Börsenschluss
dieses Tages liegt. Krypto bleibt unberührt.

**Scope:** ein Kalender-Modul mit Prozess-Cache, ein Gate am Anfang von
`_run_cycle_job`, ein Config-Flag als Rollback-Pfad.
**Non-Scope:** siehe §5.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate | nein | Das Gate sitzt **vor** dem Zyklus, nicht im Risk-Pfad. Es ändert keinen Risk-Parameter und trifft keine Handelsentscheidung — es entscheidet, ob überhaupt gerechnet wird. Rein deterministischer Code, kein LLM. |
| #2/#3 Order-Pfad | nein | Kein Order-Tool, keine Decision, kein Schreibzugriff. Ein übersprungener Zyklus erzeugt gar nichts — auch keine `cycle`-Zeile. |
| #5 Paper/Live | nein | Der Kalender ist kontounabhängig; abgefragt wird er über den geteilten Marktdaten-Key gegen den **Paper**-Endpoint. Kein Live-Pfad, keine neue Credential. |
| #6 Secrets | nein | Keine neue Env-Var. `ALPACA_MARKET_DATA_KEY_ID`/`_SECRET_KEY` existieren seit F002. |
| #7 Kosten-Caps | positiv | Spart je Feiertag drei Zyklen × fünf Aktien-Personas an `persona_analysis` (Sonnet), dem mit ~81 % größten Kostenblock. Der Kalender-Call selbst ist kein LLM-Call. |
| #10 Fairness | **ja, geprüft — neutral** | Das Gate wirkt auf den Zyklus, nicht auf eine Persona: an einem Feiertag entfällt der Zyklus für **alle fünf** Aktien-Personas gleichzeitig (VULTURE, GUARDIAN, CHARTIST, HYPE, CONTRA), unabhängig vom Adapter-Typ. CRYPTOR behält seine Zyklen — nicht als Vorteil, sondern weil der Kryptomarkt an US-Feiertagen tatsächlich geöffnet ist. Kein Informationsvorsprung für irgendwen. |
| Persona-Charter | nein | Kein `charter_version`-Bump. Die Charter beschreiben, *wie* eine Persona entscheidet, nicht *wann* der Scheduler sie aufruft. |
| Versuchsbedingungen | **ja — deshalb aus** | Eine Scheduler-Änderung 48 Stunden vor der Endabrechnung eines Achtwochen-Experiments ist schlechte Praxis, auch wenn sie nachweisbar neutral ist (zwischen dem 16. und 18.09.2026 liegt weder Feiertag noch Half-Day, das Gate würde also keinen einzigen Zyklus anfassen). Das Flag steht deshalb auf `false` bis zur Endabrechnung — siehe §6. |

## 3. Entscheidungen

Vollständig begründet in [ADR-0019](../adr/0019-handelskalender-gate-fail-open.md);
hier nur das Ergebnis:

**(a) Fail-open.** Ist der Kalender nicht beschaffbar (Key fehlt, Alpaca-API down,
Netzwerk weg) und der Cache leer, läuft der Zyklus — mit `WARNING` im Log.
Fail-closed würde einen transienten API-Aussetzer in einen *still* ausgefallenen
echten Handelstag verwandeln, und das ist der teurere Fehler: ein überflüssiger
Feiertagszyklus kostet ein paar Cent und eine gequeuete Order, ein verschluckter
Handelstag kostet einen Zyklus im laufenden Wettbewerb. Fail-open ist zudem exakt
das heutige Verhalten — das Gate kann damit nie schlechter sein als der Status quo.

**(b) Kein Open-Check, nur ein Close-Check.** C1 liegt um 09:00 ET und damit
**absichtlich 30 Minuten vor der Eröffnung** (ARCHITECTURE.md §5.2: Analyse auf
Basis der Vorbörse, Orders laufen in die Eröffnungsauktion). Ein naives
„läuft die Session gerade?" würde C1 jeden Tag abwürgen. Geprüft wird deshalb
ausschließlich `now >= close` — das ist die Bedingung, die an Half-Days greift und
an normalen Tagen nie.

**(c) Prozess-Cache statt DB-Tabelle.** Der Handelskalender eines Datums ändert
sich nicht mehr. Ein Dict im Scheduler-Prozess mit einem 45-Tage-Fenster braucht
weder Migration noch Modell noch Refresh-Job und überlebt genau so lange wie der
Scheduler selbst. Nach einem Container-Restart wird beim ersten Aktienzyklus neu
geholt — ein Call.

**(d) Nur Aktienzyklen.** Begründung je Job in §5.

**(e) Geteilter Marktdaten-Key.** `ALPACA_MARKET_DATA_KEY_ID` ist laut
`config/broker.yaml` bewusst persona-unabhängig. Der Kalender ist
kontounabhängige Börseninfrastruktur — ihn über einen Persona-Key zu ziehen würde
eine Kopplung erfinden, die es fachlich nicht gibt.

**Gotcha, live gegen `alpaca-py` 0.43.5 verifiziert:** `Calendar.open`/`.close`
sind **naive `datetime`** in Börsen-Lokalzeit (ET), nicht `time` und nicht
UTC — `Calendar.__init__` klebt `date` und den `"%H:%M"`-String zusammen. Der
Vergleich läuft deshalb gegen `now` in `America/New_York`, und das Modul
speichert bewusst nur `.time()`.

## 4. Testdefinition (vor der Umsetzung geschrieben)

`tests/orchestrator/test_market_calendar.py` — das Kalender-Modul:

1. Ein regulärer Handelstag (09:30–16:00) lässt einen 09:00-Zyklus durch —
   Nachweis, dass **nicht** auf „Markt offen" geprüft wird (Entscheidung b).
2. Derselbe Tag lässt 13:00 und 15:15 durch.
3. Ein Datum, das der Kalender nicht zurückgibt (Feiertag), wird abgelehnt mit
   `reason="not_a_trading_day"`.
4. Ein Half-Day (Close 13:00) lässt 09:00 durch, lehnt 13:00 und 15:15 ab mit
   `reason="after_close"` — inkl. der Grenze „genau zum Close".
5. Ein Fehler der Quelle führt zu `allowed=True`, `reason="calendar_unavailable"`
   (Fail-open, Entscheidung a).
6. Zwei Abfragen desselben Datums lösen genau **einen** Quell-Aufruf aus (Cache).
7. Ein Datum außerhalb des gecachten Fensters löst einen zweiten Aufruf aus.
8. Nach einem gescheiterten Abruf wird beim nächsten Aufruf erneut versucht —
   ein Fehlschlag darf sich nicht als „Kalender leer" einbrennen.
9. `get_market_calendar()` liefert prozessweit dieselbe Instanz (sonst wäre der
   Cache wertlos).

`tests/orchestrator/test_scheduler.py` — das Gate im Job:

10. `_run_cycle_job` mit `US_EQUITY` an einem Nicht-Handelstag ruft
    `run_one_cycle` **nicht** auf und loggt strukturiert `cycle skipped`.
11. `_run_cycle_job` mit `US_EQUITY` an einem Handelstag ruft `run_one_cycle` auf.
12. `_run_cycle_job` mit `CRYPTO` fragt den Kalender **gar nicht erst** —
    Nachweis, dass der 24/7-Markt unberührt bleibt (Entscheidung d).
13. Bei `calendar_gate=false` wird der Kalender nicht befragt (Rollback-Pfad).
14. Ein übersprungener Zyklus setzt den Failure-Zähler nicht und alarmiert nicht.

`tests/orchestrator/test_cycles_config.py`:

15. `calendar_gate` wird aus `config/cycles.yaml` gelesen; fehlt der Schlüssel,
    gilt `true` (der Zielzustand — die Abschaltung muss bewusst dastehen).

## 5. Non-Scope, je Job begründet

| Job | Warum kein Gate |
|---|---|
| Krypto-Zyklen | 24/7-Markt, kein Handelskalender. Ein Gate wäre schlicht falsch. |
| `daily-digest` (16:30 ET) | Berichtet über den Tag, inkl. CRYPTOR am Wochenende — feuert bewusst täglich (F070). An einem Feiertag meldet er null Trades, und das ist die korrekte Aussage. |
| `competition-settlement` (16:35 ET) | Ohnehin datumsgebunden auf den letzten Wettbewerbstag (`is_settlement_due`, F121). Der 18.09.2026 ist ein regulärer Handelstag. |
| `review-sweep`, `meta-review-sweep`, `weekly-report` | Lesen ausschließlich die DB, kein Marktbezug. |
| `order-fill-reconciliation` | Soll gerade an einem geschlossenen Markt laufen: eine Freitag-Abend-Order kann am Montag füllen. |
| `hitl-timeout-sweep`, `stuck-decision-retry-sweep` | Sicherheitsnetze — an einem Feiertag abzuschalten wäre das Gegenteil von dem, wofür sie da sind. |
| `scripts/run_cycle.py` | Manueller Einstiegspunkt. Wer von Hand einen Zyklus startet, tut das absichtlich; ein Gate würde die Debug-Fähigkeit nehmen. |

## 5a. Testdurchlauf und Smoke-Test (16.09.2026)

Alle Gates lokal grün: `ruff check`, `ruff format --check`, `mypy src`,
`pytest tests/ --cov=src --cov-fail-under=90` (1260 Tests, 92,07 %), das
100-%-Branch-Gate für `src/risk`/`src/broker`. `src/orchestrator/market_calendar.py`
steht bei 100 % Branch-Coverage.

**Smoke-Test gegen die echte Alpaca-API** (read-only, `get_calendar`, keine Order):

| Zeitpunkt (ET) | Erwartung | Ergebnis |
|---|---|---|
| Do 17.09.2026, 09:00 (regulär) | läuft | `trading_day` |
| Fr 18.09.2026, 15:15 (Wettbewerbsende) | läuft | `trading_day` |
| Sa 19.09.2026, 09:00 | Skip | `not_a_trading_day` |
| Do 26.11.2026, 09:00 (Thanksgiving) | Skip | `not_a_trading_day` |
| Fr 27.11.2026, 09:00 (Half-Day) | läuft | `trading_day` |
| Fr 27.11.2026, 13:00 (Half-Day C3) | Skip | `after_close` |
| Fr 27.11.2026, 15:15 (Half-Day C4) | Skip | `after_close` |
| Fr 25.12.2026, 09:00 (Christmas) | Skip | `not_a_trading_day` |

Alpaca meldet für den 27.11.2026 tatsächlich `open 09:30 / close 13:00` — der
Half-Day-Fall ist damit nicht nur angenommen, sondern an echten Daten belegt. Die
ersten beiden Zeilen sind zugleich der Nachweis, dass das Gate an den verbleibenden
Wettbewerbstagen keinen einzigen Zyklus angefasst hätte.

## 6. Livesetzung

**Bewusst noch nicht scharf.** `config/cycles.yaml` steht auf
`stock.calendar_gate: false`. Grund in §2 letzte Zeile: der Wettbewerb endet am
Fr 18.09.2026, und in diesen zwei Tagen liegt kein Feiertag und kein Half-Day —
das Gate hätte null Nutzen und ein Restrisiko.

Scharfschaltung ab **19.09.2026**, nach der Endabrechnung:

```bash
# config/cycles.yaml: stock.calendar_gate: true
# config/ ist ins Image gebacken -> Rebuild, nicht nur Restart:
ssh atlas-ugreen 'cd /mnt/.../atlas && docker compose build api && docker compose up -d'
```

**Verifikation nach dem Deploy** (kein Feiertag nötig — der Erlaubt-Pfad ist der
tägliche Normalfall):

1. Im Log des ersten Aktienzyklus muss `calendar gate passed` mit
   `reason=trading_day` stehen, und der Zyklus muss normal durchlaufen.
2. Erst der nächste echte Nachweis ist **Do 26.11.2026** (Thanksgiving,
   geschlossen) bzw. **Fr 27.11.2026** (Half-Day, Close 13:00): erwartet wird
   `cycle skipped` mit `not_a_trading_day` bzw. `after_close` für C3/C4 — und ein
   normal laufendes C1 am 27.11.

## 7. Rollback

`config/cycles.yaml` → `stock.calendar_gate: false`, `docker compose build api &&
docker compose up -d`. Der Scheduler verhält sich dann exakt wie vor F124; das
Kalender-Modul wird nicht einmal importiert aufgerufen. Kein DB-Zustand, keine
Migration, nichts zurückzudrehen.
