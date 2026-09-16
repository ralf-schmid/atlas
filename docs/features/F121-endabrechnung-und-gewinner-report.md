# F121 — Endabrechnung: Schlussbewertung zum Stichtag + Gewinner-Report

Status: implementiert, noch nicht live verifiziert (Stichtag ist der 18.09.2026)
Datum: 2026-09-05
Phase: 5 → 6 (schließt den offenen P5-Punkt und liefert die Grundlage für den
ersten P6-DoD-Punkt „Gewinner-Report … Entscheidung als ADR")
Auslöser: Ralfs Entscheidung vom 16.08.2026 (`docs/dod/phase-5.md`, offene
Entscheidung 4): am Wettbewerbsende noch offene Positionen werden zum Schlusskurs
bewertet, nicht zwangsliquidiert. Umsetzung war ausdrücklich offen.

## 1. Zieldefinition

**Done heißt:** am Abend des 18.09.2026 existiert je Persona eine
Schlusskurs-Bewertung in der DB, und daraus lässt sich jederzeit reproduzierbar
derselbe §4.7-Report erzeugen — auch im Dezember, obwohl das Paper-Feld
weiterläuft.

**Scope:** Stichtags-Snapshot nach US-Close, zeitlich geschlossenes Wertungsfenster
in den Kennzahlen, Endabrechnungs-Report (Markdown-Artefakt + Telegram-Push),
Scheduler-Job + manuelle Fallback-Skripte.
**Non-Scope:** die Gewinner-Entscheidung selbst (ADR, Ralf), das Live-Konto
(→ [F122](F122-live-pfad-vorbereitung.md)), das Anhalten irgendeiner Persona — das
Paper-Feld läuft nach der Kür weiter (ARCHITECTURE.md §4.7).

## 2. Die zwei Lücken, die der Report sonst gehabt hätte

**Lücke 1: der letzte Snapshot des Tages ist keine Schlusskurs-Bewertung.**
`portfolio_snapshot` entsteht ausschließlich im Reporting-Schritt eines Zyklus
(`src/orchestrator/reporting.py`). Der letzte Aktien-Zyklus C4 läuft 15:15 ET —
**45 Minuten vor dem Close**. Ohne zusätzlichen Snapshot wäre die Endabrechnung
eine Nachmittagsbewertung gewesen, und Ralfs Entscheidung („zum Schlusskurs")
wäre formal erfüllt, faktisch aber nicht. Neu: `competition-settlement`, ein
Scheduler-Job um 16:35 ET, der nur am `competition.end_date` etwas tut.

**Lücke 2: alle Kennzahlen waren nach rechts offen.** `daily_portfolio_values`,
`slippage_malus_sum`, `trade_count`, `thesis_quality`, `reliability_inputs`
filterten `>= since` ohne Obergrenze. Da dieselben Portfolios nach dem 18.09.
weiterhandeln, hätte derselbe Report zwei Wochen später eine andere Saison
bewertet — und niemand hätte es gesehen, weil die Zahl weiterhin plausibel
aussieht. Neu: optionales `until` in allen DB-gestützten Kennzahlen
(`time_window`), das auch der Wochenreport benutzt (dort `as_of`, in der Praxis
ohne Wirkung, aber ab jetzt reproduzierbar).

`decision` und `agent_run` tragen keinen eigenen Zeitstempel; sie werden über
`cycle.trading_day` begrenzt. Die Saison ist zusätzlich schon durch
`portfolio_id` abgegrenzt (F090 hat für den Wettbewerb neue Portfolios angelegt) —
die Cycle-Grenze ist die Absicherung für die Zeit *nach* dem Stichtag.

## 3. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Der Stichtags-Snapshot entsteht für alle sechs Portfolios im selben Lauf, mit derselben Preisquelle wie jeder andere Snapshot. CRYPTOR handelt 24/7 und wird trotzdem zum US-Close bewertet — dokumentiert, weil es eine Setzung ist: ein gemeinsamer Stichtagszeitpunkt ist vergleichbarer als sechs verschiedene. |
| #1 Risk-Gate | nein | Kein Risk-Parameter, keine Entscheidung, keine Order. |
| #2 Privilege Separation | nein | Der Settlement-Job liest Kontostand und Positionen, er handelt nicht. |
| #7 Kosten | nein | Kein LLM-Call; der Report ist reine Arithmetik. |

**Fairness-Detail Kriterium 4 (Thesen-Qualität):** Für am 18.09. noch offene
Positionen gibt es kein Review — sie zählen also weiterhin nur über die Kriterien
1–3 (Depotwert). Das ist der Status quo und bleibt bewusst so; Ralfs Entscheidung
vom 16.08. betrifft die Bewertung, nicht die Review-Pflicht. Die Frage „bekommen
offene Positionen am Ende auch ein Review?" ist damit weiterhin offen und in
`docs/dod/phase-6.md` als Entscheidung notiert.

**Kosten/Aufwand:** ein zusätzlicher Snapshot je Portfolio pro Saison. Nichts.

## 4. Testdefinition (vor der Umsetzung geschrieben)

`tests/orchestrator/test_competition_settlement.py`

1. `market_close_utc` liefert 20:00 UTC für den 18.09.2026 (EDT) und 21:00 UTC für
   einen Dezember-Tag (EST) — kein fest verdrahteter Offset.
2. `is_settlement_due` ist wahr ab dem Close des Stichtags, falsch davor
   (C4-Zeitpunkt!), falsch an jedem anderen Tag, falsch ohne `end_date`.
3. `run_final_settlement` schreibt je aktivem Portfolio genau einen Snapshot.
4. Archivierte Vorsaison-Portfolios bleiben außen vor.
5. Ein fehlschlagendes Portfolio wird benannt, die übrigen werden trotzdem
   bewertet (SAVEPOINT je Portfolio statt Commit je Portfolio).
6. `settlement_snapshot_id` nimmt den letzten Snapshot **vor** dem Cutoff, nicht
   den neuesten überhaupt.

`tests/metrics/test_final_report.py`

7. Sieger ist Rang 1; Punktgleichheit wird als Punktgleichheit ausgewiesen.
8. Ein Snapshot nach dem Stichtag verändert die Endabrechnung nicht.
9. Offene Positionen erscheinen mit Marktwert (Ralfs Entscheidung), Nullpositionen
   nicht.
10. Eine Bewertung von vor dem Close wird im Report markiert (⚠️) und in
    `missing_closing_valuation` gemeldet.
11. Benchmark-Rendite über dasselbe geschlossene Fenster.
12. Ohne `end_date` verweigert der Report die Arbeit (kein stillschweigend offenes
    Fenster).
13. Das Markdown enthält, was der ADR braucht: Zeitraum, alle Personas,
    Schlussbewertung, §4.7-Vorbehalt.

`tests/orchestrator/test_scheduler.py` (F121-Block)

14. Job registriert, Mo–Fr, 16:35 America/New_York.
15. An einem normalen Tag: kein Settlement, keine Telegram-Nachricht.
16. Am Stichtag: Settlement + Endabrechnung als Push.
17. Fehlgeschlagene Portfolios stehen in der Push-Nachricht.
18. Ein Fehler alarmiert per Telegram, statt nur zu loggen — anders als beim
    Tagesdigest gibt es hier kein „morgen wieder".

`tests/telegram/test_weekly_report.py`

19. Der Wochenreport endet am Reporting-Datum (Reproduzierbarkeit).

## 5. Umsetzung

- `config/competition.yaml`: `end_date: 2026-09-18`; `CompetitionConfig.end_date`
  + `settlement_cutoff()`.
- `src/metrics/performance.py`: `time_window()` + optionales `until` in allen
  DB-gestützten Kennzahlen.
- `src/metrics/competition_score.py`: `until` in `thesis_quality`/
  `reliability_inputs`; neue Funktion `collect_persona_criteria` — die
  Kriterien-Sammlung, die vorher im Wochenreport stand. Wochenreport und
  Endabrechnung teilen sich damit **eine** Implementierung von §4.7; zwei
  auseinanderdriftende wären der sichere Weg zu einem Report, der einen anderen
  Sieger nennt als das Leaderboard.
- `src/orchestrator/competition_settlement.py`: Stichtags-Snapshot, DST-sicherer
  `market_close_utc`, Fehlerisolation je Portfolio.
- `src/metrics/final_report.py`: `build_final_report` + Markdown- und
  Telegram-Rendering.
- `src/orchestrator/scheduler.py`: Job `competition-settlement`.
- `scripts/final_settlement.py`, `scripts/final_report.py`: manuelle Fallbacks —
  der Container kann am 18.09. um 16:35 aus sein.

## 6. Rollback

Config-Flag im Wortsinn: `competition.end_date` aus `config/competition.yaml`
entfernen. Dann ist `is_settlement_due` immer falsch, der Job ein No-op, und
`build_final_report` verweigert die Arbeit mit einer klaren Fehlermeldung. Der
Rest (das `until` in den Kennzahlen) ist per Default `None` und verhält sich
exakt wie vorher.

## 7. Offen bis zum Stichtag

- **Live-Verifikation:** der Job hat noch nie gefeuert. Vor dem 18.09. einmal
  gegen die Produktions-DB trocken laufen lassen:
  `scripts/final_settlement.py --now <heute nach Close>` schreibt einen
  zusätzlichen Snapshot (harmlos, das tut jeder Zyklus auch) und
  `scripts/final_report.py` rendert den Report auf dem aktuellen Stand.
- **Deploy:** Image-Rebuild nötig — `config/competition.yaml` ist ins Image
  gebacken, ein Restart allein sieht das neue `end_date` nicht.
