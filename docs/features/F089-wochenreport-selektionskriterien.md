# F089 — §4.7-Wochenreport (Selektionskriterien, automatisch)

**Status:** umgesetzt und deployt (02.08.2026)
**Phase:** 5, Block 4
**Abhängigkeiten:** F082 (Kennzahlen), F083/F084 (Slippage-Malus, Reviews),
F081 (SPY-Benchmark), F090 (Stichtag in `config/competition.yaml`).

## 1. Zieldefinition

DoD-Satz (§8 P5): „Selektionskriterien (§4.7) als automatischer Wochenreport
implementiert."

**Scope:**
- Die fünf in ARCHITECTURE.md §4.7 **vorab fixierten** Kriterien als Code, mit
  ihren Gewichten (Sortino 40 %, Rendite nach Kosten 25 %, Max Drawdown invers
  15 %, Thesen-Qualität 10 %, operative Zuverlässigkeit 10 %).
- Ein gewichteter Gesamtscore je Persona plus Rangfolge.
- Automatischer Telegram-Push sonntags (ARCHITECTURE.md §5.2 „Sonntag:
  Review-Wochenlauf + Leaderboard-/Kriterien-Report") und `/report` on demand.

**Non-Scope:** keine UI-Seite (das Leaderboard [F085](F085-leaderboard-view.md)
zeigt die Einzelkennzahlen bereits), keine Gewinner-Kür — der Report ist ein
Zwischenstand, die Entscheidung nach 8 Wochen trifft Ralf.

## 2. Kritische Betrachtung — die zwei Entscheidungen, die §4.7 offenlässt

§4.7 fixiert **was** zählt und **wie stark**, aber nicht, wie fünf Größen in
fünf verschiedenen Einheiten zu einer Zahl werden. Zwei Festlegungen waren
nötig; beide stehen im Modul-Docstring von `src/metrics/competition_score.py`
und sind jederzeit änderbar:

1. **Min-Max über das Feld statt absoluter Zielwerte.** Je Kriterium bekommt die
   beste Persona 1,0, die schlechteste 0,0, der Rest linear dazwischen. Das ist
   ein Wettbewerb von sechs Agenten auf identischer Datenbasis — „bester im Feld"
   ist der sinnvolle Bezug, eine absolute Skala bräuchte Zielzahlen, die niemand
   fixiert hat. Sind alle gleich (Normalfall in Woche 1: alle exakt 0,00 %),
   bekommen alle 0,5 statt eines Zufallssiegers.
2. **Nicht messbare Kriterien fallen raus, ihr Gewicht wird proportional
   umverteilt.** Sortino braucht 20 Tagesrenditen (F082), Thesen-Qualität
   braucht abgeschlossene Reviews — beides existiert in Woche 1 schlicht nicht.
   Eine Persona dafür mit 0 zu bewerten wäre ein Messartefakt, kein Ergebnis.
   Ein Kriterium zählt nur, wenn **alle** Personas einen Wert haben; sonst würde
   eine Persona an einem Maßstab gemessen, der für die anderen nicht gilt.
   Der Report nennt immer explizit, was gewertet wurde und was nicht.

**Kriterium 5 („Fehlerquote, Risk-Gate-Reject-Quote, Fill-Plausibilität")** ist
in §4.7 nur benannt, nicht definiert. Umsetzung:
- Fehlerquote = `agent_run` mit Status FAILED / alle `agent_run` des Portfolios.
- Risk-Reject-Quote = Decisions mit Status RISK_REJECTED / Decisions, die das
  Gate überhaupt erreicht haben.
- Fill-Plausibilität = gefüllte Orders / Orders mit terminalem Status. Noch
  offene `NEW`-Orders zählen **nicht** mit — sie haben kein Ergebnis, und sie
  mitzuzählen würde eine Persona dafür bestrafen, spät am Tag zu handeln (genau
  der Fall der ADSK-Order vom 02.08.).
- Die drei gehen zu gleichen Teilen ein: §4.7 fixiert keine Untergewichte, und
  ein erfundener 40/30/30-Split wäre eine zweite undokumentierte Annahme.

**Kosten/Invarianten:** reiner Read-Pfad über bestehende Tabellen, kein LLM
(0 USD), keine Order-Rechte, keine Risk-Berührung. Fairness: identische Formel
und identische Datenquelle für alle 6 Personas.

## 3. Fund während der Umsetzung: JSON `null` ≠ SQL NULL

Die Risk-Reject-Quote sollte ursprünglich über `risk_check IS NOT NULL` zählen,
welche Decisions das Gate erreicht haben. Das zählt zu viel: SQLAlchemy legt ein
JSON-Feld, dem Python `None` zugewiesen wird, als **JSON `null`** ab, nicht als
SQL NULL (`none_as_null`-Default). Jede `hold`-Decision passiert damit einen
`IS NOT NULL`-Filter, während sie im ORM als `None` zurückkommt — im Test
6 statt 4 Nenner, live entsprechend eine zu niedrige Reject-Quote. Der Zähler
hängt jetzt am `status` (RISK_REJECTED/HITL_*/APPROVED/EXECUTED/
EXECUTION_FAILED), der eindeutig ist.

## 4. Tests

`tests/metrics/test_competition_score.py` (15) — Gewichte entsprechen §4.7
wörtlich (ein stiller Edit hier würde den Wettbewerb umschreiben);
Min-Max-Normalisierung inkl. Invertierung beim Drawdown und 0,5 bei
Gleichstand; Ranking nach gewichteter Summe (Sortino 40 % schlägt Rendite
25 %); Kriterien ohne Datenbasis fallen raus und die Gewichte summieren sich
wieder auf 1,0; ein Kriterium, das nur ein Teil des Feldes hat, fällt ebenfalls
raus; Zuverlässigkeits-Teilsignale inkl. „keine Trades ⇒ keine Fill-Rate";
Thesen-Quote gegen echte Reviews; Reject-Quote ignoriert `hold` (JSON-null-Fall
oben); offene `NEW`-Orders bleiben außen vor.

`tests/telegram/test_weekly_report.py` (6) — Rangfolge, ausgelassene Kriterien,
Benchmark, archivierte Portfolios bleiben draußen, Rendering zeigt Rangliste,
Gewichte, „Nicht wertbar"-Zeile und §4.7-Disclaimer, „–" für nicht messbare
Werte.

`tests/orchestrator/test_scheduler.py` (2) — Job sonntags 19:00 ET registriert
**auch ohne LLM-Client** (anders als die Review-Sweeps, weil hier kein LLM
beteiligt ist); Job-Fehler wirft nicht.

Gesamtlauf: 880 passed, ruff/mypy grün.

## 5. Live-Verifikation (02.08.2026)

Report gegen die Wettbewerbs-DB gerendert (`docker exec scheduler`). Gewertet wurden „Rendite nach Kosten 25 %", „Max Drawdown 15 %" und
„Operative Zuverlässigkeit 10 %"; Sortino und Thesen-Qualität wurden als nicht
wertbar ausgewiesen und ihr Gewicht umverteilt — korrekt für Handelstag 7 ohne
abgeschlossene Reviews (effektiv 50/30/20 statt 25/15/10).

Ergebnis (Stand 02.08., 7 Handelstage): CRYPTOR, GUARDIAN und HYPE teilen sich
Rang 1 mit Score 1,000 (alle drei bei 0,00 % ohne Trades), CHARTIST 0,933,
VULTURE 0,800 (Reject-Quote 100 % — die beiden Stop-Loss-Rundungsrejects aus
F101), CONTRA 0,157 als einzige Persona mit Trades und realisiertem Verlust.
SPY liegt mit +1,07 % vor dem gesamten Feld.

Zwei Befunde aus dem Live-Render sofort korrigiert: „Drawdown +0,16 %" las sich
wie ein Gewinn (Drawdown, Thesen-Quote und Zuverlässigkeit jetzt vorzeichenlos),
und drei punktgleiche Personas wurden als 1./2./3. ausgegeben — Gleichstand
teilt sich jetzt den Rang (1,1,1,4).

## 6. Rollback

Additiv: neues Modul, neuer Scheduler-Job, neues Bot-Kommando. Rollback =
`git revert` + Rebuild von `scheduler`/`telegram-bot`. Kein Schema-Change, keine
Migration, keine Config-Änderung. Der Job lässt sich zusätzlich einzeln stoppen,
ohne andere Jobs zu berühren.
