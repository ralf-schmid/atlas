# F083 — Slippage-Malus-Berechnung

**Status:** Entwurf (Feature-Schnitt 25.07.2026, Phase 5 noch nicht gestartet)
**Phase:** 5, Block 1 (Messfundament)
**Abhängigkeiten:** keine harten; Ergebnis wird von F084 (Review-Agent) und
F085 (Leaderboard) konsumiert. `review.slippage_malus` (Numeric 10,4) existiert
bereits im Schema.

## 1. Zieldefinition

Die in ARCHITECTURE.md §7 Punkt 8 fixierte Formel als deterministischen Code
implementieren:

```
malus = 0,5 × geschätzter Spread + Penalty, wenn Ordergröße > 1 % des Tagesvolumens
```

Der Malus simuliert Kosten, die im Alpaca-Paper-Modus nicht anfallen (Spread,
Market Impact), damit das Leaderboard eine ehrliche „adjustierte" Performance
ausweisen kann. Ergebnis pro ausgeführter Order: ein USD-Betrag, geschrieben
nach `review.slippage_malus` (durch F084) bzw. abrufbar als Funktion für
Ad-hoc-Berechnungen (F085/F089).

**Scope:**
- Modul `src/review/slippage.py` (oder `src/risk/` — bei Umsetzung entscheiden,
  Tendenz: eigenes `src/review/`-Package, da kein Order-Gate)
- Spread-Schätzung + Volumen-Penalty als reine Funktionen über
  `order_record` + `market_bar`
- Parameter in `config/review.yaml` (neu), mit dokumentierten Defaults
- Unit-Tests mit festen Fixtures

**Non-Scope:**
- Kein Eingriff in Risk-Gate oder Order-Pfad (der Malus ist Reporting, kein Gate)
- Keine Intraday-/Quote-Datenbeschaffung (siehe offene Entscheidung unten)
- Kein LLM-Anteil (CLAUDE.md-Verbot: Kennzahlen sind Code)

### Spread-Schätzmethode — **entschieden 25.07.2026 (Ralf): fixe bps je Assetklasse**

Wir haben **keine Bid/Ask-Daten** — `market_bar` enthält nur DAY-Bars
(OHLCV, 415 Symbole). Geprüfte Optionen: (A) fixe bps je Assetklasse,
(B) Corwin-Schultz-Schätzer aus High/Low-Bars (rauscht bei Einzeltiteln,
kann negativ werden), (C) Live-Quote zum Review-Zeitpunkt (zeitlich nicht
zum Fill passend). **Entscheidung: A** — z. B. Aktien 5 bps, Krypto 15 bps
als Config-Parameter; trivial, robust, transparent. Die konkreten
bps-Werte werden bei der F083-Umsetzung gemeinsam mit Ralf feinjustiert
und hier dokumentiert.

### Penalty-Höhe (Ralf, vor Umsetzung)

§7 gibt nur die Struktur vor („Penalty, wenn > 1 % Tagesvolumen"). Vorschlag:
Penalty = zusätzliche bps proportional zur Überschreitung, z. B.
`10 bps × (Ordervolumen / 1 % Tagesvolumen − 1)`, gekappt bei 50 bps.
Parameter (`penalty_bps_per_x`, `penalty_cap_bps`, `volume_threshold_pct`)
alle in `config/review.yaml`.

## 2. Kritische Betrachtung

- **Invariante 1 (Risk-Gate = Code, kein LLM):** nicht berührt — der Malus ist
  kein Gate. Die Berechnung selbst ist deterministischer Code, kein LLM
  (CLAUDE.md-Verbot eingehalten).
- **Invariante 10 (Fairness):** Der Malus muss für alle 6 Personas identisch
  parametrisiert sein (eine Config, keine Persona-Overrides). Krypto vs. Aktien
  dürfen unterschiedliche Spread-Defaults haben (Assetklasse, nicht Persona) —
  das benachteiligt CRYPTOR nicht unfair, sondern bildet reale Marktstruktur ab.
  Jede Parameter-Änderung während des Wettbewerbs verzerrt den Vergleich →
  Parameter werden zum Stichtag (F090) eingefroren und nur per dokumentierter
  Ralf-Entscheidung geändert (rückwirkende Neuberechnung aller Reviews dann
  Pflicht, sonst inkonsistentes Leaderboard).
- **Kosten:** 0 — reiner Code, keine LLM-Calls.
- **Datenlücken:** Tagesvolumen für Krypto-Symbole in `market_bar` prüfen
  (CRYPTOR-Universum); fehlt das Volumen für ein Symbol → Malus nur aus
  Spread-Anteil, Penalty = 0, und ein WARN-Log (nie stillschweigend 0).
- **Edge Cases:** Teilfills (Malus auf gefüllte Menge), `fees > 0` (Alpaca
  Krypto-Fees existieren — Malus kommt on top, keine Doppelzählung mit echten
  Fees), Orders ohne Bar am Fill-Tag (Fallback: letzter verfügbarer Bar,
  max. 5 Tage alt, sonst WARN + Spread-Default).

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/review/test_slippage.py`), alles feste Fixtures:

1. Formel-Basisfall: bekannter Spread, Ordergröße < 1 % Volumen → Malus =
   0,5 × Spread × Ordervolumen, Penalty = 0
2. Penalty-Fall: Ordergröße > 1 % Tagesvolumen → Penalty gemäß Formel,
   Kappung greift
3. Grenzfall exakt 1 %: keine Penalty (Schwelle strikt „>")
4. Fehlendes Volumen (NULL/0): Penalty 0 + WARN geloggt
5. Fehlender Bar: Fallback-Kette (letzter Bar ≤ 5 Tage → Default-Spread)
6. Krypto vs. Aktie: unterschiedliche Config-Defaults werden korrekt gezogen
7. Config-Validierung: negative bps / fehlende Keys → Startup-Fehler
8. Property-artiger Check: Malus ≥ 0 für alle Fixture-Kombinationen

## 4.–6. Implementierung / Test & Verifikation / Rollback

Wird bei Umsetzung ausgefüllt. Rollback-Pfad (geplant): Config-Flag
`slippage.enabled: false` → `slippage_malus` bleibt NULL, Leaderboard zeigt
dann nur Roh-Performance (F085 muss NULL-tolerant sein).
