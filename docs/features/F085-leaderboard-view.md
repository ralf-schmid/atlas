# F085 — Leaderboard-View

**Status:** Entwurf (Feature-Schnitt 25.07.2026, Phase 5 noch nicht gestartet)
**Phase:** 5, Block 3 (UI-Ausbau)
**Abhängigkeiten (hart):** F081 (SPY-Benchmark füllt `benchmark_value`),
F082 (Kennzahlen-Modul: Sortino, Max Drawdown, Roh-Rendite als Code).
**Abhängigkeit (weich):** F083/F084 — die adjustierte Spalte braucht
`review.slippage_malus`; solange Reviews fehlen, zeigt das Leaderboard
adjustiert = roh mit Hinweis „noch keine Reviews".

## 1. Zieldefinition

DoD-Satz (§8 P5): „Leaderboard weist Roh- und adjustierte Performance
getrennt aus" + UI-Checkliste „Leaderboard … auf realem Smartphone getestet".

**Scope:**
- API: `GET /api/leaderboard` (neuer Endpoint in `src/api/routes.py`) —
  aggregiert je Portfolio: Roh-Rendite seit Stichtag, adjustierte Rendite
  (roh − Σ `slippage_malus`), Sortino, Max Drawdown, Trade-Count, offene
  Positionen, Sparkline-Daten (Tages-Snapshots); plus SPY-Benchmark-Zeile
  (aus `benchmark_value`, F081). Alle Kennzahlen aus F082-Funktionen —
  **keine Berechnung im Frontend, keine im LLM.**
- UI: neue Route `web/src/app/leaderboard/page.tsx`, mobile-first (~390 px):
  Rangliste 6 Personas + SPY, Umschalter roh/adjustiert, Sparklines
  (bestehende Chart-Komponente aus F074 wiederverwenden, prüfen),
  Touch-Targets ≥ 44 px, Eintrag in die Bottom-Nav
- Statistischer Disclaimer aus §4.7 (8 Wochen ≈ 40 Handelstage sind
  statistisch schwach) sichtbar im View
- Test auf realem Smartphone (Ralf), Screenshot ins DoD-Dokument

**Non-Scope:**
- Kein §4.7-Gesamtscore/Gewichtung (das ist F089 Wochenreport; Leaderboard
  zeigt Einzelkennzahlen, keine Gewinner-Formel)
- Kein Decision Journal / Impuls-Vergleich / Agent Trace (F086–F088)
- Keine Zeitraum-Filter über „seit Stichtag" hinaus (YAGNI; kommt bei Bedarf)

**Stichtag-Kopplung:** Vor F090 (offizieller Start) gibt es keinen Stichtag —
das Leaderboard rechnet bis dahin ab Portfolio-Start (08.07.2026,
„Vorsaison") und kennzeichnet das als solche. Der Stichtag wird Config
(`config/competition.yaml` o. ä., legt F090 fest), nicht hartcodiert.

## 2. Kritische Betrachtung

- **Kennzahlen = Code (CLAUDE.md-Verbot):** Sortino/Drawdown/Rendite kommen
  ausschließlich aus F082 (`src/…/metrics.py`), unit-getestet. Der API-Layer
  aggregiert nur.
- **Invariante 10 (Fairness):** Leaderboard ist reine Anzeige — kein
  Informationsrückfluss in Agenten. Identische Kennzahlen-Pipeline für alle
  6 Portfolios; SPY-Zeile ist virtuell (F081) und nimmt nicht am Ranking
  teil (Benchmark, kein Wettbewerber — Darstellung entsprechend abgesetzt).
- **Ehrlichkeit der adjustierten Spalte:** Σ Malus existiert nur für
  reviewte Decisions. Solange F084 hinterherhängt, ist „adjustiert"
  systematisch zu optimistisch → UI zeigt Review-Abdeckung an
  (z. B. „12/24 Trades reviewt"), damit die Zahl einordbar ist.
- **Sortino-Datenbasis:** 18 Tage tägliche Snapshots vorhanden (seit
  08.07.). Sortino auf < ~20 Datenpunkten ist wackelig → F082 definiert
  Mindest-N (Vorschlag: unter 20 Tagen Anzeige „—" statt Scheinpräzision).
  Downside-Deviation-Definition (Target 0 % vs. risk-free) legt F082 fest.
- **Kosten:** 0 LLM. API-Query-Last trivial (6 Portfolios × Tages-Snapshots).
- **Mobile-first:** 8 Spalten passen nicht auf 390 px → Karten-Layout je
  Persona (Rang, Name, Rendite groß, Sekundär-Kennzahlen klein, Sparkline)
  statt Tabelle; Umschalter roh/adjustiert als Segmented Control.

## 3. Testdefinition (vor Umsetzung)

1. F082-Unit-Tests decken die Kennzahlen ab (dort definiert, hier nur
   konsumiert — kein Nachrechnen im API-Test)
2. API-Test: Fixture-Portfolios mit bekannten Snapshots/Reviews →
   Endpoint liefert erwartete Roh-/Adjustiert-Werte, SPY-Zeile, Abdeckung
3. API-Test NULL-Toleranz: keine Reviews / kein `benchmark_value` →
   definierte Fallbacks (adjustiert = roh + Flag; SPY-Zeile fehlt + Flag),
   kein 500er
4. API-Test Mindest-N: < 20 Snapshots → Sortino null im JSON
5. Frontend: ESLint/tsc strict; Render-Test der Seite mit Mock-Daten
   (bestehendes Test-Setup in `web/` prüfen — falls keines existiert,
   bleibt es beim manuellen Smartphone-Test, das ist der DoD-Nachweis)
6. Smartphone-Test (real, Ralf): Lesbarkeit 390 px, Touch-Targets,
   Screenshot → `docs/dod/phase-5.md`

## 4.–6. Implementierung / Test & Verifikation / Rollback

Bei Umsetzung. Rollback-Pfad (geplant): Route/Nav-Eintrag entfernen ist
rückstandsfrei; API-Endpoint ist additiv und bricht nichts Bestehendes.
