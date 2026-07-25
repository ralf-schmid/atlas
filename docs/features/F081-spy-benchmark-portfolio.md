# F081 — SPY-Benchmark-Portfolio

**Status:** Entwurf (25.07.2026)
**Phase:** 5, Block 1 (Messfundament)
**Abhängigkeiten:** keine — SPY ist bereits im täglichen `market_bar`-Sync-
Universum (`config/ingestion.yaml`, 62 DAY-Bars vorhanden). Konsumenten:
F085 (Leaderboard-SPY-Zeile), F089 (Wochenreport).

## 1. Zieldefinition

DoD-Satz (§8 P5): „SPY-Benchmark-Portfolio (virtuell, Buy-and-Hold) läuft
mit." Bisher: `portfolio_snapshot.benchmark_value` ist durchgängig NULL
(`src/orchestrator/reporting.py:59` — bewusster P4-Non-Scope).

**Modell (virtuell, kein Broker-Account, kein Order-Pfad):**

```
shares      = 5000 USD / SPY-Schlusskurs am ersten Handelstag ≥ Stichtag
benchmark_value(t) = shares × letzter SPY-Schlusskurs ≤ t   (aus market_bar)
```

Stichtag: **Mo 03.08.2026** (Ralf-Entscheidung 25.07.2026, siehe
`docs/dod/phase-5.md`). Konfiguriert in einer neuen
`config/competition.yaml` (`start_date`, `start_capital_usd`,
`benchmark_symbol: SPY`) — F090 nutzt dieselbe Datei.

**Scope:**
- Funktion `benchmark_value(session, now)` (Vorschlag:
  `src/orchestrator/benchmark.py`) — reiner Code, liest `market_bar`
- Aufruf in `generate_portfolio_snapshot()` statt des `None`-Hardcodes;
  identischer Wert für alle 6 Portfolios im selben Snapshot-Lauf
- `config/competition.yaml` + Loader mit Validierung
- Vor dem Stichtag (und falls kein SPY-Bar ≥ Stichtag existiert):
  `benchmark_value = None` — kein Fehler, WARN-Log nur einmal je Zyklus

**Non-Scope:**
- Kein Backfill der „Vorsaison" (Snapshots vor 03.08. bleiben NULL —
  die Vorsaison ist kein Wettbewerb)
- Keine Dividenden-Reinvestition (SPY-Kursindex genügt; Abweichung über
  8 Wochen ≲ 0,3 %, als bekannte Unschärfe dokumentiert)
- Kein eigener Portfolio-/Broker-Datensatz für SPY (kein `portfolio`-Row;
  die Benchmark ist eine Spalte, kein Teilnehmer)

## 2. Kritische Betrachtung

- **Invariante 10 (Fairness):** Benchmark ist Anzeige, kein Teilnehmer —
  kein Order-Pfad, kein Research-Zugriff, keine Persona bekommt dadurch
  Information (SPY-Bars liegen ohnehin im Shared Pool).
- **Kennzahlen = Code:** reine Arithmetik auf `market_bar`, kein LLM.
- **Wochenend-Problem (wichtigster Edge Case):** CRYPTOR erzeugt Snapshots
  Sa/So, SPY hat dann keinen neuen Bar → „letzter Schlusskurs ≤ t" trägt
  den Freitagswert fort. Das ist korrekt (Buy-and-Hold hat am Wochenende
  denselben Wert), muss aber im Test fixiert sein.
- **Stichtag = Montag:** erster SPY-Bar ≥ 03.08. ist der 03.08. selbst
  (Handelstag). Falls Feiertag/Datenlücke: „erster Bar ≥ Stichtag"
  deckt das ab, Einstandskurs verschiebt sich dann ehrlich nach hinten.
- **Konsistenz je Zyklus:** alle 6 Snapshots eines Laufs bekommen denselben
  `benchmark_value` (einmal berechnen, durchreichen) — sonst zeigt das
  Leaderboard je Persona minimal andere Benchmark-Werte.
- **Kosten:** 0 (kein LLM, ein zusätzlicher indexierter SELECT je Zyklus).
- **Rückwirkende Stichtag-Änderung:** ändert Ralf den Stichtag nach dem
  ersten Snapshot, stimmen alte `benchmark_value`-Zeilen nicht mehr →
  bewusst kein Auto-Rewrite; so ein Fall wäre eine dokumentierte
  Neuberechnung (einmaliges Skript), nicht stillschweigend.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_benchmark.py`, feste `market_bar`-Fixtures:

1. Basisfall: Bars am 03.08. (Close 100) und 05.08. (Close 104) →
   shares = 50, benchmark_value(05.08.) = 5200.00
2. Vor Stichtag: `now` < 03.08. → None
3. Stichtag-Bar fehlt noch (Sync-Verzögerung am 03.08. früh): → None,
   kein Fehler; sobald Bar da ist → Wert
4. Wochenende: kein Bar am Sa → Freitags-Close wird fortgetragen
5. Feiertags-Stichtag: erster Bar ≥ Stichtag ist der 04.08. →
   Einstand auf 04.08.-Close
6. Rundung: Decimal-Arithmetik, Ergebnis auf 2 Nachkommastellen
   (Numeric(18,2)-Spalte)
7. Integration: `generate_portfolio_snapshot()` schreibt den Wert;
   zwei Portfolios im selben Lauf → identischer `benchmark_value`
8. Config-Validierung: fehlender/ungültiger `start_date` → Startup-Fehler

## 4.–6. Implementierung / Test & Verifikation / Rollback

Bei Umsetzung. Rollback-Pfad (geplant): `benchmark.enabled: false` in
`config/competition.yaml` → Spalte bleibt NULL (Zustand wie heute);
F085 ist laut eigenem Doc NULL-tolerant.
