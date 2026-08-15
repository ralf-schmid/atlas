# F112 — Der Slippage-Malus im Leaderboard sagt jetzt, wie weit er trägt

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 5 (Nachbesserung an F085/F083)
Auslöser: Nebenbefund beim DoD-Nachweis „Leaderboard weist Roh- und adjustierte
Performance getrennt aus"

## 1. Befund

Der DoD-Punkt war technisch erfüllt: `/api/leaderboard` liefert `raw_return` und
`adjusted_return` getrennt, die Seite hat einen Umschalter, und die Formel
stimmt bis auf die letzte Stelle (nachgerechnet in `docs/dod/phase-5.md`). Beim
Gegenlesen der echten Seite fielen zwei Dinge auf, die die Zahl unehrlicher
machen, als sie sein muss:

**(a) „0 $" statt 0,0893 $.** Der Malus wurde durch denselben `Intl.NumberFormat`
gerendert wie die Depotwerte — mit `maximumFractionDigits: 0`. Ein Malus lebt
naturgemäß in Cent, also stand dort bei jeder Persona `0 $`. Wer die Seite
aufschlägt, liest: der Slippage-Malus ist null, das Feature tut nichts. Tatsächlich
lagen Werte zwischen 0,0137 $ und 0,1876 $ vor.

**(b) Der Malus deckt nur einen Bruchteil der Trades.** `slippage_malus_sum`
summiert `review.slippage_malus` — und ein `review` entsteht erst, wenn eine
Position geschlossen wurde oder ein Kauf die Zwischenreview-Frist von 14 Tagen
erreicht (F084). Live sah das so aus:

| Persona | gefüllte Orders | davon mit Malus |
|---|---|---|
| CONTRA | 13 | 3 |
| CHARTIST | 9 | 2 |
| HYPE | 6 | 3 |
| VULTURE | 2 | 1 |

Die „slippage-adjustierte Performance" preist also die Reibung von einem Viertel
bis der Hälfte der Trades ein und ist damit **systematisch zu optimistisch** —
ohne dass die Zahl das erkennen ließ. Das ist kein Rechenfehler, sondern eine
Aussage, die mehr verspricht als sie hält.

**Was es nicht ist:** kein Fehler in der Malus-Formel (F083/F104 rechnen korrekt),
und keine Verzerrung der Rangfolge — der Effekt liegt bei allen Personas in
derselben Größenordnung und im dritten Nachkommastellenbereich.

## 2. Umsetzung

| Datei | Änderung |
|---|---|
| `src/metrics/performance.py` | `malus_trade_count()` — zählt Reviews mit gesetztem `slippage_malus` |
| `src/api/schemas.py` | `LeaderboardRowOut.malus_trade_count` |
| `src/api/routes.py` | Feld befüllt |
| `web/src/lib/api.ts` | Typ ergänzt |
| `web/src/app/leaderboard/page.tsx` | eigener Malus-Formatter (2 Nachkommastellen) + Abdeckung im Text |

Ergebnis auf der Seite:

> Slippage-Malus: 0,09 $ aus 3 von 13 Trades (roh +1,84 %)

Bewusst **kein** neuer Warnhinweis-Kasten: die Zahl trägt ihre Einschränkung
selbst, das ist ehrlicher und kostet keine Aufmerksamkeit auf einer
mobile-first-Seite.

## 3. Tests

In `tests/api/test_routes.py`:

1. `test_get_leaderboard_reports_how_many_trades_the_malus_covers` — drei
   gefüllte Orders, davon eine gereviewt ⇒ `trade_count == 3`,
   `malus_trade_count == 1`. Der eigentliche Regressionstest.
2. `test_get_leaderboard_subtracts_the_slippage_malus_from_the_adjusted_return`
   — um `malus_trade_count == 1` erweitert.
3. `test_get_leaderboard_without_reviews_reports_adjusted_equals_raw` — um
   `malus_trade_count == 0` erweitert.

Gesamtlauf: **1007 passed, 26 deselected**; `ruff`, `mypy src`, `tsc --noEmit`
und `eslint` clean.

## 4. Rollout

- Deployt am 15.08.2026 (`api`, `web`). Kein Schema-Change, keine Migration.
- **Live verifiziert** gegen die gerenderte Seite: alle vier Personas mit Trades
  zeigen Betrag und Abdeckung (`0,09 $ aus 3 von 13`, `0,19 $ aus 2 von 9`,
  `0,01 $ aus 1 von 2`, `0,13 $ aus 3 von 6`).
- **Rollback:** Revert des Commits. Ein Flag wäre sinnlos — der alte Zustand ist
  die missverständliche Anzeige.

## 5. Folgearbeit

- **Malus ab Fill statt ab Review.** Die eigentliche Lücke aus §1(b) bleibt: die
  Reibung eines Trades ist im Moment des Fills bekannt (seit F104 steht
  `order_record.spread_bps` in der Zeile, das Volumen ebenfalls), aber sie wird
  erst beim Review verbucht. Der Malus direkt am `order_record` würde die
  adjustierte Rendite auf **alle** Trades stellen und die Kennzahl vom
  Review-Takt entkoppeln. Das ist ein eigener Eingriff in eine
  Wettbewerbskennzahl mitten in der laufenden Saison — braucht Ralfs
  Entscheidung, nicht nur sein Go.
