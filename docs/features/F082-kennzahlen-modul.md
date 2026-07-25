# F082 — Kennzahlen-Modul (Code, kein LLM)

**Status:** Entwurf (25.07.2026)
**Phase:** 5, Block 1 (Messfundament)
**Abhängigkeiten:** keine. Konsumenten: F085 (Leaderboard), F089
(§4.7-Wochenreport), F084 (Review nutzt ggf. Rendite-Helper).

## 1. Zieldefinition

Wiederverwendbare, unit-getestete Funktionen für alle Performance-Kennzahlen
des Wettbewerbs — heute existiert davon nichts außer der inline
Max-Drawdown-Rechnung in `reporting.py` (running peak vs. equity).
CLAUDE.md-Verbot: Kennzahlen gehören in Code, nie ins LLM.

**Modul:** `src/metrics/__init__.py` + `src/metrics/performance.py`
(eigenes Package — wird von orchestrator, api und review konsumiert,
gehört zu keinem davon). Reine Funktionen über Zeitreihen
(`list[Decimal]` bzw. Snapshot-Rows), keine DB-Zugriffe im Kern —
DB-Adapter (Snapshots → Zeitreihe) als dünne Helper daneben.

**Funktionen (Scope):**

| Funktion | Definition |
|---|---|
| `simple_return(values)` | `(letzter / erster) − 1`, ab Stichtag |
| `daily_returns(values)` | Tagesrenditen aus Snapshot-Serie (1 Snapshot/Tag: letzter je Kalendertag) |
| `sortino_ratio(daily_returns, target=0)` | `mean(r − target) / downside_deviation`, annualisiert √252; Target 0 % (kein Risk-free — 8 Wochen, Einfachheit; Abweichung dokumentiert) |
| `max_drawdown(values)` | max. Peak-to-Trough über die Serie (nicht nur running peak vs. letzter Wert) |
| `trade_count(session, portfolio_id, since)` | Anzahl FILLED `order_record` ab Stichtag |
| `adjusted_return(raw, malus_sum, start_capital)` | Roh-Rendite − Σ Slippage-Malus / Startkapital (F083-Anschluss) |

**Regeln:**
- **Mindest-N für Sortino:** < 20 Tagesrenditen → `None` (keine
  Scheinpräzision; F085 zeigt dann „—"). Downside-Deviation über alle N
  (nicht nur negative Tage zählen — Standard-Sortino: Σ min(r−t,0)²/N).
- Alle negativen Tage = 0 Fälle: downside_deviation 0 → Sortino `None`
  (nicht ∞).
- Durchgängig `Decimal`; Annualisierung als dokumentierte Konstante.

**Non-Scope:**
- Kein §4.7-Gesamtscore (Gewichtung 40/25/15/10/10 ist F089)
- Keine UI/API (F085), kein Backfill/Persistieren berechneter Werte
  (Kennzahlen werden on-the-fly gerechnet, nur Snapshots sind persistent)
- Sharpe, Calmar, Beta etc. — nicht gefordert, YAGNI

## 2. Kritische Betrachtung

- **Korrektheit vor Cleverness:** Sortino hat viele Varianten (Target,
  Annualisierung, N vs. N−1, nur-negative vs. alle Tage). Die gewählte
  Definition steht oben im Doc und als Docstring — jede spätere Änderung
  ändert das Leaderboard rückwirkend und braucht einen dokumentierten
  Entscheid (Fairness: nie mitten im Wettbewerb still ändern).
- **Bestehender Drawdown in `reporting.py`:** rechnet running-peak vs.
  aktuelle Equity und persistiert je Snapshot — das bleibt unangetastet
  (Bestandsdaten!). `max_drawdown()` hier ist die Serien-Variante für
  Leaderboard/Report. Divergenz der beiden ist möglich und ok; F085 nutzt
  ausschließlich die F082-Funktion. Konsolidierung ist bewusst Non-Scope.
- **Snapshot-Kadenz uneinheitlich:** Aktien-Personas 4 Snapshots/Tag
  (Mo–Fr), CRYPTOR bis zu 4/Tag inkl. Wochenende → `daily_returns` nimmt
  den letzten Snapshot je Kalendertag (UTC), damit Sortino aller Personas
  auf vergleichbarer Basis steht. CRYPTOR hat dadurch mehr Datenpunkte
  (Sa/So) — das ist reale Marktexposition, keine Unfairness.
- **Invariante 10:** identische Funktionen für alle Portfolios, Parameter
  (Target, Mindest-N, Annualisierung) global, nie je Persona.
- **Kosten:** 0 (kein LLM).
- **mypy:** Package neu → in strict-Scope aufnehmen (wie risk/broker;
  reine Rechenfunktionen, strict ist billig zu haben).

## 3. Testdefinition (vor Umsetzung)

`tests/metrics/test_performance.py`, handgerechnete Fixtures:

1. `simple_return`: [5000, 5250] → 0.05; Serie mit 1 Element → 0
2. `daily_returns`: Multi-Snapshot-Tage → nur letzter je Tag zählt;
   Wochenend-Lücken (Aktien) erzeugen keine künstliche 0-Rendite
3. `sortino_ratio`: handgerechnetes Beispiel (kleine Serie, Target 0,
   Ergebnis vorab per Hand/Spreadsheet fixiert); N < 20 → None;
   keine negativen Renditen → None
4. `max_drawdown`: [100, 120, 90, 110, 80] → (120−80)/120; monoton
   steigend → 0; Peak am Ende → 0
5. `trade_count`: Fixture-Orders (FILLED/CANCELED/NEW gemischt, vor/nach
   Stichtag) → nur FILLED ab Stichtag
6. `adjusted_return`: Roh 5 %, Malus 25 USD, Start 5000 → 4,5 %;
   `malus_sum=None`/0 → roh
7. Decimal-Reinheit: kein Float in Signaturen; mypy strict grün
8. Property-Checks: max_drawdown ∈ [0,1]; adjusted ≤ roh für Malus ≥ 0

## 4.–6. Implementierung / Test & Verifikation / Rollback

Bei Umsetzung. Rollback-Pfad: reines Library-Modul ohne Seiteneffekte —
Rollback = Konsumenten (F085/F089) deaktivieren; das Modul selbst kann
gefahrlos liegen bleiben.
