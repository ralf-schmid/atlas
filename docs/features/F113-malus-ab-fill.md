# F113 — Slippage-Malus gilt ab dem Fill, nicht erst ab dem Review

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 5 (Wettbewerbskennzahl, wirkt auf F083/F085/F089/F112)
Auslöser: Ralfs Entscheidung zur Folgearbeit aus [F112](F112-leaderboard-malus-transparenz.md) §5

## 1. Zieldefinition

Die slippage-adjustierte Rendite soll **alle** Trades einer Persona einpreisen,
nicht nur die bereits gereviewten.

Heute summiert `slippage_malus_sum` über `review.slippage_malus`. Ein `review`
entsteht aber erst, wenn eine Position geschlossen wurde oder ein Kauf 14 Tage
alt ist (F084). Der Stand vom 15.08.2026:

| Persona | gefüllte Orders | davon mit Malus | Abdeckung |
|---|---|---|---|
| CONTRA | 13 | 3 | 23 % |
| CHARTIST | 9 | 2 | 22 % |
| HYPE | 6 | 3 | 50 % |
| VULTURE | 2 | 1 | 50 % |

Die Kennzahl misst damit nicht die Reibung der Strategie, sondern die Reibung
derjenigen Trades, die der Review-Takt zufällig schon erfasst hat. Alle Daten für
den Malus liegen dagegen **im Moment des Fills** vor: `order_record.fill_price`,
`order_record.spread_bps` (seit F104 gemessen) und das Tagesvolumen aus
`market_bar`.

**Scope:** `slippage_malus_sum` rechnet über alle `FILLED`-Orders statt über
Reviews. Damit ziehen Leaderboard (F085), Wochenreport (F089) und der
§4.7-Score automatisch nach — sie hängen alle an dieser einen Funktion.
**Non-Scope:** die Malus-Formel selbst (F083/F104 bleiben unverändert),
`review.slippage_malus` als Feld des Review-Artefakts, und der Review-Takt.

## 2. Entscheidung: rechnen statt speichern (kein Schema-Change)

Naheliegend wäre eine Spalte `order_record.slippage_malus_usd`, beim Fill
befüllt. Ich habe mich dagegen entschieden, aus drei Gründen:

1. **Konsistente Parametrisierung.** Ein persistierter Malus friert die
   `config/review.yaml`-Parameter des Berechnungszeitpunkts ein. Genau das ist
   heute schon das Problem: die drei CONTRA-Maluswerte stammen aus drei
   Review-Zeitpunkten. Wird gerechnet statt gespeichert, tragen **alle** Trades
   dieselben Parameter — was eine Wettbewerbskennzahl auch soll. §7 Punkt 8 der
   ARCHITECTURE sieht die Feinjustierung der Parameter in P5 ausdrücklich vor;
   nach einer Justierung wäre ein gespeicherter Mischbestand sofort wieder da.
2. **Rückwirkend ohne Backfill.** Die Umstellung gilt sofort für die gesamte
   Saison. Ein Spaltenansatz bräuchte ein Backfill-Skript über alle Bestands-
   Orders — mehr Code und ein zweiter Zustand, der schiefgehen kann.
3. **Kein Migrationskonflikt.** Zum Zeitpunkt dieser Entscheidung lag die noch
   uncommittete Migration des Backtest-Moduls (F111) im Arbeitsverzeichnis, auf
   derselben Basis `c9e8d7f6a5b4`. Eine zweite Migration daneben hätte zwei
   Alembic-Heads ergeben und `alembic upgrade head` beim nächsten Deploy
   zerlegt. *(Nachtrag: F111 wurde noch am selben Tag als `59e5bb7` committet.
   Die Begründung bleibt gültig — sie war der Grund, hier keine dritte Variable
   ins Spiel zu bringen —, aber der Konflikt ist damit Geschichte.)*

**Preis:** Rechenzeit auf dem Leaderboard-Pfad. `compute_slippage_malus` macht je
Order zwei Queries (Decision, Tagesvolumen). Bei ~80 Orders über sechs Portfolios
wären das ~160 Queries pro Seitenaufruf. Deshalb bekommt die Summenfunktion einen
**aufrufweiten Cache** für Decision und Tagesvolumen: die Orders eines Portfolios
betreffen wenige Symbole an wenigen Tagen, der Cache trifft entsprechend oft.

## 3. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, zentral | Die Änderung wirkt auf alle sechs Personas mit derselben Formel und denselben Parametern. Sie **verbessert** die Vergleichbarkeit: bisher hing die Höhe des Malus daran, wie viele Trades einer Persona zufällig schon gereviewt waren, und das korreliert mit der Haltedauer — eine Persona mit kurzen Haltedauern (CONTRA, HYPE) wurde stärker belastet als eine mit langen. |
| #1 Risk-Gate | nein | Kein Risk-Parameter, keine Order-Entscheidung. |
| #7 Kosten-Caps | nein | Kein LLM-Call, reine Arithmetik. |
| Wertung mitten in der Saison | ja | Die adjustierte Rendite aller Personas ändert sich rückwirkend. Das ist der beabsichtigte Effekt und Ralfs ausdrückliche Entscheidung. Die **Roh**-Rendite bleibt unangetastet, ebenso jede Order, jede Position und jeder Depotwert. |

**Wie groß ist der Effekt?** Bei Abdeckungen von 22–50 % steigt der Malus grob um
den Faktor 2–4. In absoluten Zahlen bleibt er winzig: CONTRA hätte statt
0,0893 USD grob 0,39 USD — auf 5.000 USD Startkapital sind das 0,008
Prozentpunkte. Die Rangfolge ändert sich dadurch mit hoher Wahrscheinlichkeit
nicht; der genaue Wert wird in §5 nach dem Deploy nachgetragen.

> **Nachtrag nach dem Deploy: die letzte Aussage war falsch.** Die Rangfolge hat
> sich geändert — CHARTIST und VULTURE tauschen Platz 2 und 3. Details und Zahlen
> in §5. Der Satz bleibt hier stehen, damit die Fehleinschätzung nicht aus der
> Doku verschwindet.

## 4. Testdefinition (vor der Implementierung geschrieben)

In `tests/metrics/test_performance.py`:

1. `test_malus_sum_covers_orders_without_a_review` — eine gefüllte Order ohne
   Review liefert einen Malus > 0. Der Kern der Umstellung; unter der alten
   Implementierung wäre das Ergebnis `None`.
2. `test_malus_sum_counts_every_filled_order` — drei gefüllte Orders, kein
   Review ⇒ Summe der drei Einzelmali.
3. `test_malus_sum_ignores_unfilled_orders` — `CANCELED`/`PARTIALLY_FILLED`
   zählen nicht: ohne Fill gibt es keine Reibung.
4. `test_malus_sum_ignores_orders_before_the_window` — Orders vor `since`
   bleiben draußen (Vorsaison).
5. `test_malus_sum_is_none_without_any_filled_order` — weiterhin `None` statt
   `0`, damit das Leaderboard „adjustiert = roh" korrekt als *unbekannt*
   ausweist und nicht als *gemessene Null* (das Verhalten aus F083).
6. `test_malus_sum_is_scoped_to_one_portfolio` — die Order einer anderen Persona
   fließt nicht ein.
7. `test_malus_sum_reuses_the_volume_lookup_per_symbol_and_day` — der Cache
   greift: zwei Orders auf dasselbe Symbol am selben Tag lösen nur eine
   Volumen-Query aus.

In `tests/api/test_routes.py`:

8. `test_leaderboard_malus_covers_all_trades_after_f113` — `malus_trade_count`
   (F112) entspricht jetzt `trade_count`, die Abdeckung ist vollständig.

## 5. Test & Rollout

- **1074 passed, 26 deselected**; `ruff`, `mypy src`, `tsc --noEmit`, `eslint`
  clean. Neu: die sieben Tests aus §4 plus
  `test_leaderboard_malus_covers_all_trades_after_f113`.
- **Drei bestehende Tests mussten mitziehen**, weil sie die alte Semantik
  festhielten (Malus über ein `review`-Objekt gesetzt). Sie bauen den Malus jetzt
  über eine gefüllte Order mit passendem Volumen auf — inhaltlich derselbe
  Prüfzweck, nur über den Weg, den die Kennzahl jetzt geht. Der F112-Test
  `..._reports_how_many_trades_the_malus_covers` ist durch F113 gegenstandslos
  geworden (die Abdeckung ist per Konstruktion vollständig) und wurde durch den
  neuen ersetzt.
- **Live auf der Box, 15.08.2026** (`api`, `web`). Kein Schema-Change, keine
  Migration.

### Wirkung auf die laufende Saison

| Persona | Malus vorher | Malus nachher | Abdeckung | adjustiert vorher | adjustiert nachher |
|---|---|---|---|---|---|
| CONTRA | 0,0893 $ | **0,5904 $** | 13/13 | 1,8402 % | **1,8302 %** |
| CHARTIST | 0,1876 $ | **0,6343 $** | 9/9 | 0,5962 % | **0,5873 %** |
| HYPE | 0,1322 $ | **0,2634 $** | 6/6 | 0,0758 % | **0,0731 %** |
| VULTURE | 0,0137 $ | **0,0271 $** | 2/2 | 0,5879 % | **0,5877 %** |

**Die Rangfolge hat sich geändert, entgegen meiner Einschätzung in §3.**
CHARTIST und VULTURE tauschen die Plätze 2 und 3:

- roh liegt CHARTIST vorn (0,6000 % gegen 0,5882 %),
- slippage-adjustiert liegt VULTURE vorn (0,5877 % gegen 0,5873 %).

Der Abstand beträgt 0,0004 Prozentpunkte — das ist Rauschen, keine Aussage über
Können. Aber es zeigt, dass die Umstellung nicht nur kosmetisch ist: CHARTIST
handelt größere Volumina und trägt deshalb mehr Reibung, und **genau das** war
unter der alten Rechnung unsichtbar, weil von seinen neun Trades nur zwei
gereviewt waren. Die Rangfolge ist damit nicht „verfälscht", sondern zum ersten
Mal auf einer für alle Personas gleichen Grundlage berechnet.

Die Roh-Rendite, alle Depotwerte, Orders und Positionen sind unverändert.

### Anschlusswirkung

- **Wochenreport (F089):** zieht über dieselbe Funktion automatisch nach.
- **F112-Anzeige:** die Zeile „aus X von Y Trades" erscheint nur noch bei
  unvollständiger Abdeckung und ist damit im Normalbetrieb verschwunden —
  verifiziert an der gerenderten Seite (`Slippage-Malus: 0,59 $ (roh +1,84 %)`).
- **F104-Methodenbruch-Hinweis im Wochenreport bleibt gültig und wird jetzt
  wichtiger:** die Trades vor dem 15.08. haben keinen gemessenen Spread und
  laufen über die Pauschale. Vorher betraf das nur die wenigen gereviewten
  Trades, jetzt alle — der Hinweis beschreibt also weiterhin exakt den Zustand.

**Rollback:** Revert des Commits — `slippage_malus_sum` summiert dann wieder über
`review.slippage_malus`. Kein Datenverlust in beide Richtungen, weil nichts
persistiert wird.
