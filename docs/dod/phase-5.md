# Phase 5 — Review, Journal & Wettbewerbsstart: Planung & Definition of Done

Checkliste aus ARCHITECTURE.md §8. **Status:** Planung erstellt 25.07.2026.
Voraussetzung Phase-4-Abschluss ist erfüllt — der letzte offene Punkt, der
Crash-Recovery-Test, wurde am 15.08.2026 durchgeführt (Nachweis in
`phase-4.md`, Abschnitt am Ende).

- [x] Review-Agent verarbeitet fällige Decisions automatisch; jede geschlossene
      Position hat binnen 7 Tagen ein Review mit Verdict
      **Nachweis geführt am 15.08.2026** gegen die Produktions-DB. Definition wie
      im Code (`src/review/agent.py`): eine geschlossene Position ist eine
      `EXECUTED`-Decision mit `SELL`/`CLOSE` und einer `FILLED`-Order; das
      Ergebnis ist im Moment des Fills realisiert. Vorsaison-Portfolios
      (`archived_at`) zählen nicht mit.

      | | |
      |---|---|
      | geschlossene Positionen seit Stichtag 27.07. | **6** |
      | davon mit Review **binnen 7 Tagen** | **6** |
      | mit Review, aber zu spät | 0 |
      | ohne Review, Frist noch offen | 0 |
      | ohne Review, Frist gerissen | **0** |

      Vorlauf Fill → Review: min 0,09 d, Median 1,60 d, max 4,40 d. Verdicts:
      2× `thesis_confirmed`, 1× `thesis_failed`, 3× `inconclusive`.

      **Der Nachweis hat einen Bug gefunden, der ihn zunächst verhinderte.** Zwei
      der sechs Positionen (VULTURE/LUNG, CHARTIST/ADSK) standen bei der ersten
      Messung ohne Review da. Ursache war nicht der Scheduler und kein
      Budget-Stopp, sondern ein überzähliges Komma in der JSON-Antwort des
      Modells, an dem der Review-Parser scheiterte —
      [F110](../features/F110-review-json-trailing-comma.md). Behoben und
      deployt; danach liefen beide Reviews durch, und der Sweep meldet
      `failed=0`. Die Zahlen oben sind der Stand **nach** dem Fix. Ohne den
      Nachweis wäre die Fehlerquote weitergelaufen: `find_due_decisions` ist
      stateless, die Decisions kamen täglich wieder, scheiterten täglich neu und
      hinterließen nur eine Log-Zeile, die der nächste Container-Rebuild
      wegräumt.
- [x] Slippage-Malus implementiert; Leaderboard weist Roh- und adjustierte
      Performance getrennt aus
      **Nachweis geführt am 15.08.2026** gegen die Produktions-DB und die live
      gerenderte Seite. Malus-Formel F083/F104 (`src/review/slippage.py`),
      Ausweisung F085 (`/api/leaderboard`, `web/src/app/leaderboard/page.tsx`),
      Umschalter Roh ↔ Slippage-adjustiert serverseitig über `?sort=`.

      | Persona | roh | adjustiert | Malus USD | aus Trades |
      |---|---|---|---|---|
      | CONTRA | 1,8420 % | 1,8402 % | 0,0893 | 3 von 13 |
      | CHARTIST | 0,6000 % | 0,5962 % | 0,1876 | 2 von 9 |
      | VULTURE | 0,5882 % | 0,5879 % | 0,0137 | 1 von 2 |
      | HYPE | 0,0784 % | 0,0758 % | 0,1322 | 3 von 6 |
      | CRYPTOR / GUARDIAN | 0,0000 % | 0,0000 % | — | 0 von 0 |

      Von Hand gegengerechnet, damit die Zahl nicht sich selbst bestätigt:
      CONTRA 0,018420 − 0,0893/5000 = **0,01840214** — exakt der ausgelieferte
      Wert. CHARTIST 0,006000 − 0,1876/5000 = **0,00596248**, ebenfalls exakt.
      Die Formel `adjusted = raw − malus / start_capital` stimmt also bis auf
      die letzte Stelle.

      **Der Nachweis hat zwei Darstellungsmängel aufgedeckt, beide behoben
      ([F112](../features/F112-leaderboard-malus-transparenz.md)):**

      1. Der Malus lief durch den Depotwert-Formatter mit `maximumFractionDigits:
         0` und wurde als **„0 $"** angezeigt — bei einem echten Wert von
         0,0893 $. Die Seite behauptete damit optisch, es werde gar nicht
         gerechnet. Jetzt eigener Formatter mit zwei Nachkommastellen.
      2. Der Malus stammt ausschließlich aus **gereviewten** Trades
         (`slippage_malus_sum` summiert `review.slippage_malus`), also bei CONTRA
         aus 3 von 13. Die adjustierte Rendite ist dadurch systematisch zu
         optimistisch, ohne dass man es der Zahl ansah. Das Leaderboard weist die
         Abdeckung jetzt aus: „Slippage-Malus: 0,09 $ **aus 3 von 13 Trades**
         (roh +1,84 %)".

      Damit ist der DoD-Punkt erfüllt — und die Zahl sagt dazu, wie weit sie
      trägt.

      **Nachtrag 15.08.2026:** die damals verbliebene Lücke (Malus erst ab Review)
      ist auf Ralfs Entscheidung hin geschlossen —
      [F113](../features/F113-malus-ab-fill.md). Der Malus zählt jetzt ab dem
      Fill und deckt alle Trades ab. Die Zahlen der Tabelle oben sind damit
      historisch; aktuell: CONTRA 0,5904 $ (13/13), CHARTIST 0,6343 $ (9/9),
      HYPE 0,2634 $ (6/6), VULTURE 0,0271 $ (2/2). Entgegen meiner Prognose hat
      sich dabei doch eine Platzierung gedreht (CHARTIST ↔ VULTURE, Abstand
      0,0004 Prozentpunkte) — Begründung in F113 §5.
- [x] UI komplett (Leaderboard, Decision Journal inkl. Rejected-Filter,
      Impuls-Vergleich, Agent Trace); auf realem Smartphone getestet
      **Erledigt: Views vollständig (02.08.2026), Smartphone-Test von Ralf am
      15.08.2026 bestätigt („GUI sieht gut aus, Test erfolgreich"):**
      [F100](../features/F100-portfolio-history-chart.md) Verlaufs-Charts auf der
      Startseite, [F085](../features/F085-leaderboard-view.md) Leaderboard (roh
      und slippage-adjustiert, SPY-Benchmark),
      [F086](../features/F086-decision-journal.md) Decision Journal mit
      Rejected-Filter, [F087](../features/F087-impuls-vergleich.md)
      Impuls-Vergleich, [F088](../features/F088-agent-trace.md) Agent Trace —
      alle live auf der Box verifiziert und von Ralf auf dem Smartphone
      gegengesehen.
- [x] Lineage-Probe: für 5 zufällige Trades die Kette
      Quelle→Research→Decision→Order→Fill→Review lückenlos in der UI
      nachvollzogen
      **Von Ralf durchgeklickt am 15.08.2026, keine Auffälligkeiten.** Die
      ursprünglich vorgesehenen Screenshots liegen nicht bei — die Probe fand am
      Gerät statt, das Ergebnis ist Ralfs Feststellung. Damit ist der Punkt
      erfüllt; wer die Kette später nachvollziehen will, findet sie unverändert
      in der UI (Decision Journal → Agent Trace) und in der DB
      (`research_item.id` → `decision.input_research_ids[]` →
      `order_record.decision_id` → `review.decision_id`).
- [x] Selektionskriterien (§4.7) als automatischer Wochenreport implementiert
      **Erledigt (02.08.2026, [F089](../features/F089-wochenreport-selektionskriterien.md)):**
      alle 5 Kriterien mit ihren Gewichten als Code (`src/metrics/competition_score.py`),
      gewichteter Score + Rangfolge, Telegram-Push sonntags 19:00 ET und `/report`
      on demand. Live gegen die Wettbewerbs-DB gerendert; Sortino und
      Thesen-Qualität werden in Woche 1 korrekt als „nicht wertbar" ausgewiesen
      und ihr Gewicht umverteilt.
- [x] **Wettbewerb offiziell gestartet (26.07.2026, [F090](../features/F090-competition-reset-and-start.md)):**
      Stichtag Mo 27.07.2026 (`config/competition.yaml`), alle 6 Portfolios auf
      5.000 USD flat / 0 Positionen (verifiziert), Vorsaison via `archived_at`
      archiviert. SPY-Benchmark (F081) aktiviert sich am Stichtag selbst
      (berechneter Wert in `portfolio_snapshot.benchmark_value`).

## Ist-Stand bei Planungserstellung (25.07.2026)

Was P5 vorfindet — relevant für Scoping und Reihenfolge:

- **Review:** Tabelle `review` existiert (Schema §3.6 inkl. `slippage_malus`,
  `verdict`, `lessons_text`), aber **0 Zeilen** — es gibt weder Review-Agent
  noch Review-Scheduling. 24 `EXECUTED`-Decisions (mit `order_record`) und
  582 `RECORDED`-Decisions warten als Datenbasis.
- **Sell/Close:** [F077](../features/F077-sell-close-decision-path.md) hat den
  Verkaufs-Pfad gebaut — geschlossene Positionen (der Review-Trigger
  "Position geschlossen") existieren damit erst seit Kurzem.
- **Reporting-Lücken (bewusste P4-Non-Scopes, jetzt fällig):**
  `portfolio_snapshot.benchmark_value` ist durchgängig `NULL`
  (`src/orchestrator/reporting.py` — "SPY benchmark portfolio is P5 scope");
  Sortino/Drawdown-Berechnung existiert nirgends im Code.
- **UI:** vorhanden sind nur Dashboard (`web/src/app/page.tsx`) und
  Persona-Detail (`personas/[name]/page.tsx`, inkl. Holding-Charts F074).
  Es fehlen: echtes Leaderboard (roh vs. adjustiert), Decision Journal mit
  Rejected-Filter, Impuls-Vergleich, Agent Trace.
- **API:** `src/api/routes.py` liefert bereits snapshot/profile/holdings/
  chart/transactions/decisions je Persona — Journal-nahe Endpoints sind
  teilweise da, Leaderboard-/Vergleichs-/Trace-Endpoints fehlen.
- **Slippage-Malus:** Formel ist vorab fixiert (ARCHITECTURE.md §7 Punkt 8):
  `malus = 0,5 × geschätzter Spread + Penalty, wenn Ordergröße > 1 % des
  Tagesvolumens`; Parameter-Feinjustierung ist explizit P5-Aufgabe.
  Berechnung gehört in Code, nicht ins LLM (CLAUDE.md-Verbot).
- **Kosten-Headroom:** Tageskosten aktuell ~2,6–3,0 USD bei 5-USD-Cap
  (Stichprobe 22.–24.07., `phase-4.md`). Der Review-Agent (Sonnet, §5) kommt
  on top. **Achtung:** der Sonnet-5-Intro-Preis (2 $/10 $) läuft am
  31.08.2026 aus → +50 % auf die Sonnet-Kosten. Beides zusammen kann das
  5-USD-Tagescap reißen — Kostenabschätzung ist Teil des
  Review-Agent-Features, ggf. Cap-Anpassung als bewusste Entscheidung von
  Ralf (nie stillschweigend).

## Geplante Feature-Reihenfolge (Vorschlag, Stand 25.07.2026)

Nummerierung fortlaufend ab F079; jede Umsetzung folgt dem Feature-Prozess
(ARCHITECTURE.md §10) mit eigenem `docs/features/FNNN-<slug>.md`.

**Block 0 — P4-Abschluss + Aufräumer (vor dem P5-Start):**

1. ✅ **Crash-Recovery-Test** (letzter offener P4-DoD-Punkt): Container-Kill
   mitten im Zyklus → Resume via Postgres-Checkpointer nachweisen. **Erledigt
   am 15.08.2026**, Nachweis am Ende von `phase-4.md`: 369 Research-Zeilen vor
   und nach dem Resume, 6 offene `persona_analysis`-Tasks liefen nach.
2. ✅ **F079 — Sizing erzeugt keine Sub-1-Aktien-Orders mehr** (25.07.2026,
   `9cf0509`): die
   Ganzaktien-Rundung (F052) sitzt erst im Broker-Adapter; die Sizing-Schicht
   (`decision_sizing.py`/`persona_analysis`) produzierte noch am 21.07. eine
   0,04-Aktien-Decision, die nie ausführbar war (Befund `phase-4.md`,
   25.07.2026). Rundung/Mindestgrößen-Check nach vorn in die Sizing-Schicht;
   zu kleiner Rest → `reject_idea` statt APPROVED-Leiche.
3. ✅ **F080 — Stuck-Decision-Sweep unterscheidet permanent/transient**
   (25.07.2026, `b98db47`): `retry_stuck_decisions` retryte 6 nie ausführbare Decisions 10 Tage lang
   alle 15 Minuten (~530 ERROR-Logs/Tag). Permanente Fehler (`ValueError`
   aus dem Adapter) → Decision terminal markieren + einmaliger
   Telegram-Alert; transiente (Netzwerk/5xx) → weiter retryen.
   Optional dabei: Retry für transiente Broker-Fehler in `persona_analysis`
   (6× Alpaca-DNS-Fehler in 9 Tagen, siehe `phase-4.md`).

**Block 1 — Messfundament (ohne das ist kein Leaderboard ehrlich):**

4. **F081 — SPY-Benchmark-Portfolio:** virtuelles Buy-and-Hold-Portfolio
   (5.000 USD in SPY am Stichtag), täglicher Snapshot;
   `portfolio_snapshot.benchmark_value` füllen. Reiner Code, kein LLM.
5. **F082 — Kennzahlen-Modul (Code, kein LLM):** Sortino (tägliche
   Snapshots), Max Drawdown, Trade-Count, Roh-Rendite je Portfolio als
   wiederverwendbare Funktionen + Tests. Grundlage für Leaderboard,
   Wochenreport und §4.7-Auswertung.
6. **F083 — Slippage-Malus-Berechnung:** Formel aus §7 Punkt 8 als Code
   (Spread-Schätzung + Volumen-Penalty), Parameter in Config
   (`config/risk.yaml` oder eigenes `config/review.yaml`) — Feinjustierung
   mit Ralf, jede Änderung dokumentiert. Schreibt `review.slippage_malus`.

**Block 2 — Review-Agent (Kern der Phase):**

7. **F084 — Review-Agent:** Scheduler-Job findet fällige Decisions
   (geschlossene Position → binnen 7 Tagen; §5-Definition "fällig" im
   Feature-Doc präzisieren, inkl. Umgang mit noch offenen Positionen am
   Wettbewerbsende). Code rechnet expected vs. actual + Slippage-Malus
   (F083); LLM (Sonnet) liefert nur `verdict` + `lessons_text`.
   Kostenabschätzung + Cap-Check Teil des Feature-Docs (siehe
   Kosten-Headroom oben). Lessons landen via pgvector im Analyse-Kontext
   (Retrieval existiert: `research_search.py` — Anbindung prüfen).

**Block 3 — UI-Ausbau (parallelisierbar zu Block 2):**

8. **F085 — Leaderboard-View:** 6 Personas + SPY; roh und
   slippage-adjustiert getrennt, Max Drawdown, Trade-Count, offene
   Positionen; Sparklines, mobile-first (~390 px).
9. **F086 — Decision Journal:** chronologisch je Portfolio, Thesis,
   verlinkte `input_research_ids`, Erwartung vs. Ist, Review-Verdict,
   **Rejected-Filter** (`reject_idea` + `rejection_reason`).
10. **F087 — Impuls-Vergleich:** Einstieg über ein `research_item`: was hat
    jede Persona daraus gemacht (gekauft/verworfen/ignoriert) und warum.
11. **F088 — Agent Trace:** pro Zyklus Läufe, Token/Kosten (`cost_ledger`,
    `agent_run`), Fehler, HITL-Ereignisse.

**Block 4 — Wettbewerbsstart (Abschluss der Phase):**

12. **F089 — §4.7-Wochenreport:** automatischer Report (Telegram und/oder
    UI) mit allen 5 Kriterien inkl. Gewichtung; rein Code auf F082/F084-Daten.
13. **F090 — Wettbewerbs-Reset & offizieller Start:** Stichtag (Ralfs
    Entscheidung), alle 6 Portfolios zurück auf 5.000 USD (native
    Alpaca-Paper-Accounts: Reset-Verfahren klären — Spike; virtuelle
    Ledger: Neuinitialisierung), SPY-Benchmark startet am selben Tag,
    `charter_version`-Stand dokumentieren. Statistischer Disclaimer aus
    §4.7 wird im Report/der UI ausgewiesen.

## Offene Entscheidungen für Ralf (vor/während P5 — Geld-Themen, nie stillschweigend)

1. **Wettbewerbs-Stichtag: ✅ vorgezogen auf Montag, 27.07.2026** (Ralf,
   26.07.2026; ursprünglich 03.08. vom 25.07.). Grund: die 3 nativen
   Alpaca-Accounts wurden bereits jetzt auf 5.000 neu angelegt (F090/ADR-0009) —
   statt sie eine Woche idle zu lassen, startet der Wettbewerb am ersten
   Handelstag nach dem Reset. 8 Wochen → Ende Fr 18.09.2026. Reset aller
   Portfolios auf 5.000 USD; der bisherige Paper-Verlauf (seit 08.07.) wird zur
   archivierten "Vorsaison" (F090). F084 (Review-Agent) darf nach dem Start
   nachziehen (Reviews sind rückwirkend berechenbar).
2. **Slippage-Parameter: Spread-Methode ✅ entschieden 25.07.2026 — fixe bps
   je Assetklasse** (Details/Begründung in
   [F083](../features/F083-slippage-malus-berechnung.md)). Noch offen:
   konkrete bps-Werte + Penalty-Höhe — Feinjustierung bei F083-Umsetzung.
3. **Kosten-Cap nach Intro-Preis-Ende (31.08.) + Review-Agent-Mehrkosten:**
   ✅ teilentschieden 25.07.2026 — System-Tagescap 5 → 10 USD, Monats-Soft-Cap
   120 → 240 USD, Per-Persona unverändert 1 USD ([ADR-0008](../adr/0008-raise-daily-cost-cap-to-10-usd.md)).
   Offen bleibt die endgültige Modell-Mix-/Frequenz-Bewertung nach dem
   Intro-Preis-Ende (31.08.), falls die neuen Caps sich als zu eng erweisen.
4. **Review-Fälligkeit im Detail:** §8 sagt "jede geschlossene Position binnen
   7 Tagen" — was gilt für am Wettbewerbsende noch offene Positionen und für
   `hold`-Ketten ohne Position?
5. **Alpaca-Paper-Reset-Verfahren:** ✅ Spike erledigt 26.07.2026
   ([ADR-0009](../adr/0009-alpaca-paper-reset-via-new-accounts.md)). Befund:
   Alpaca hat den In-Place-Reset abgeschafft — für exakt 5.000 USD müssen **neue**
   Paper-Accounts angelegt werden (Startbetrag frei wählbar, aber **neue API-Keys**;
   max. 3 Accounts/Login → alte vorher löschen; kein Trading-API-Reset-Endpoint).
   Manuelle Ralf-Aufgabe (Accounts + Keys), die 3 virtuellen Personas werden per
   Code (Ledger-Reset auf 5.000) zurückgesetzt. Offene F090-Detailpunkte im ADR.
