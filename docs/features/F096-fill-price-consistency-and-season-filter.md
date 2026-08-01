# F096 — `FILLED` ohne Fill-Preis + fehlender Saison-Filter im Review-Agenten

**Status:** Implemented
**Phase:** 5 (Härtung)
**Deployed:** 2026-08-01
**Abhängigkeiten:** `src/orchestrator/trading.py`, `src/orchestrator/scheduler.py`,
`src/review/agent.py`, `tests/db/factories.py`, Migration `b7c8d9e0f1a2`
Berührt Invariante **#10** (Fairness).

## 1. Zieldefinition

Auslöser war ein Nebenbefund aus dem F084-Bestandslauf: ein Review merkte an, die
Position sei *„offenbar nie gefüllt (fill_price null, position_open true)"*. Ralfs
Auftrag: dem nachgehen.

Die Spur führte zu **zwei** Defekten — der zweite deutlich schwerer als der
gemeldete.

## 2. Befund

### 2.1 `FILLED` ohne `fill_price` ist ein darstellbarer Zustand

```
 status | gesamt | mit_preis | ohne_preis
--------+--------+-----------+------------
 FILLED |     28 |        26 |          2
```

Ursache in `trading.py`: der Status wurde **allein aus `filled_at`** abgeleitet,
`fill_price` unabhängig davon gesetzt.

```python
status=OrderRecordStatus.FILLED if result.filled_at is not None else OrderRecordStatus.NEW,
fill_price=Decimal(str(result.fill_price)) if result.fill_price is not None else None,
```

Meldet ein Adapter das eine ohne das andere, entsteht ein Fill, den nachgelagert
niemand bepreisen kann — Review-`deviation`, Slippage-Malus (F083) und die
Holdings-Charts lesen ihn trotzdem. Dieselbe Lücke steckte in
`reconcile_order_fills`: Alpaca kann `FILLED` ohne `filled_avg_price` melden.

### 2.2 Der eigentliche Fund: Review-Agent ignoriert den Saison-Filter

```
        saison         | reviews
-----------------------+---------
 ARCHIVIERTE Vorsaison |      16
```

**Alle 16 Reviews aus dem Bestandslauf vom 31.07. stammen aus archivierten
Vorsaison-Portfolios.** `find_due_decisions` filterte nicht auf
`Portfolio.archived_at IS NULL` — ein Filter, den F090 überall sonst etabliert hat
(`graph.list_active_portfolios`). Beim Schreiben von F084 wurde er nicht übernommen.

Folgen:

* 0,25 USD für Reviews einer Saison, die nicht mehr zählt.
* Die am 31.07. berichtete Verteilung (CHARTIST 6/6 bestätigt, VULTURE 4/4
  gescheitert) ist **kein Datenpunkt des laufenden Wettbewerbs** — das war eine
  Fehlaussage und ist hiermit korrigiert.
* Sobald der Lessons-Rückfluss existiert (F084 §7), würde Vorsaison-Wissen in den
  laufenden Wettbewerb bluten → **Invariante #10**.

## 3. Kritische Betrachtung

**Die 2 fehlenden Preise sind nicht rekonstruierbar.** Geprüft:

* Der interne Ledger (`data/ledger/*.json`) wurde beim F090-Reset geleert —
  `CRYPTOR.json` enthält keine Positionen mehr, `CONTRA.json` nur Einträge ab 29.07.
* `market_bar` hat für beide Symbole nur DAY-Bars. Ein Tages-Close ist **nicht** der
  Fill-Preis um 06:15 bzw. 18:01.

Einen geschätzten Preis als `fill_price` zu schreiben hieße, Finanzhistorie zu
erfinden — in einem System, dessen Zweck Nachvollziehbarkeit ist, das schlechtere
Übel gegenüber einer ehrlichen Lücke. Beide Zeilen gehören ohnehin zur
archivierten Vorsaison und sind seit 2.2 vom Review ausgeschlossen.

Deshalb: **CHECK-Constraint als `NOT VALID`** — greift für jeden künftigen Insert
und Update, validiert die Historie aber nicht nach.

## 4. Umsetzung

| Änderung | Ort |
|---|---|
| `_fill_status(filled_at, fill_price)` — `FILLED` nur wenn **beides** vorliegt | `trading.py`, beide Schreibstellen |
| Alpaca meldet `FILLED` ohne Preis → Zeile bleibt `NEW`, Warnung, nächster Sweep pollt erneut | `scheduler.reconcile_order_fills` |
| `Portfolio.archived_at IS NULL` + `fill_price IS NOT NULL` in der Fälligkeits-Query | `review/agent.py` |
| CHECK `status <> 'FILLED' OR fill_price IS NOT NULL` (NOT VALID) | Migration `b7c8d9e0f1a2` |

## 5. Tests

Der Constraint hat beim ersten Lauf **10 bestehende Tests** umgeworfen — allesamt
Fixtures, die den jetzt unmöglichen Zustand bauten. `make_order_record` in
`tests/db/factories.py` setzte `status=FILLED` per Default und ließ `fill_price`
leer; die Invariante steckt jetzt in der Factory selbst.

Neue Tests:

| Test | Sichert |
|---|---|
| `test_fill_status_requires_both_timestamp_and_price` | alle vier Kombinationen von `filled_at`/`fill_price` |
| `test_archived_pre_season_decisions_are_never_due` | §2.2 |
| `test_active_season_decisions_are_still_due` | Gegenprobe — der Filter darf nicht alles wegschneiden |

**Ergebnis:** 785 passed (vorher 782), `ruff` und `mypy` sauber.

## 6. Live-Verifikation (2026-08-01)

```
1) Constraint blockt den Widerspruch:
   ERROR: new row for relation "order_record" violates check constraint
          "ck_order_record_filled_has_price"

2) pg_constraint: convalidated = f   (NOT VALID, Historie unangetastet)

3) Review-Agent, fällig (nur aktive Saison): 0
```

Die 0 ist korrekt und keine Überfilterung — gegengeprüft:

```
    saison     | status | count |       aeltester_fill
---------------+--------+-------+----------------------------
 aktive Saison | FILLED |     3 | 2026-07-29 19:54:03
 Vorsaison     | FILLED |    25 | 2026-07-10 19:00:30
```

Die aktive Saison hat drei gefüllte Orders, die älteste 3 Tage alt — unter der
14-Tage-Schwelle für Zwischen-Reviews, und noch kein Sell/Close. Der erste echte
Review der laufenden Saison fällt also ab dem 12.08. an.

## 7. Rollback

Code-Revert + `alembic downgrade a1b2c3d4e5f6` (löscht nur den Constraint). Keine
Daten werden verändert, in keiner Richtung.

## 8. Offen

**Die 16 Vorsaison-Reviews stehen weiterhin in der DB.** Sie sind fachlich
wertlos und kosteten 0,25 USD. Löschen ist eine Datenentscheidung für Ralf, nicht
für Claude — der Filter stoppt die Blutung, mehr habe ich ungefragt nicht getan.
