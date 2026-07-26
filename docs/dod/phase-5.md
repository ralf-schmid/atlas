# Phase 5 — Review, Journal & Wettbewerbsstart: Planung & Definition of Done

Checkliste aus ARCHITECTURE.md §8. **Status:** Planung erstellt 25.07.2026,
Phase noch nicht gestartet. Voraussetzung: Phase-4-Abschluss — davon fehlt
nur noch der Crash-Recovery-Test (siehe `phase-4.md`, Update 25.07.2026).

- [ ] Review-Agent verarbeitet fällige Decisions automatisch; jede geschlossene
      Position hat binnen 7 Tagen ein Review mit Verdict
- [ ] Slippage-Malus implementiert; Leaderboard weist Roh- und adjustierte
      Performance getrennt aus
- [ ] UI komplett (Leaderboard, Decision Journal inkl. Rejected-Filter,
      Impuls-Vergleich, Agent Trace); auf realem Smartphone getestet
- [ ] Lineage-Probe: für 5 zufällige Trades die Kette
      Quelle→Research→Decision→Order→Fill→Review lückenlos in der UI
      nachvollzogen (Screenshots im DoD-Dokument)
- [ ] Selektionskriterien (§4.7) als automatischer Wochenreport implementiert
- [ ] **Wettbewerb offiziell gestartet:** Stichtag dokumentiert, alle 6
      Portfolios auf 5.000 USD, SPY-Benchmark-Portfolio (virtuell,
      Buy-and-Hold) läuft mit

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

1. **Crash-Recovery-Test** (letzter offener P4-DoD-Punkt): Container-Kill
   mitten im Zyklus → Resume via Postgres-Checkpointer nachweisen. Kein
   Feature, ein dokumentierter Test in `phase-4.md`. Jetzt gefahrlos möglich,
   da der 5-Tage-Nachweis steht.
2. **F079 — Sizing erzeugt keine Sub-1-Aktien-Orders mehr:** die
   Ganzaktien-Rundung (F052) sitzt erst im Broker-Adapter; die Sizing-Schicht
   (`decision_sizing.py`/`persona_analysis`) produzierte noch am 21.07. eine
   0,04-Aktien-Decision, die nie ausführbar war (Befund `phase-4.md`,
   25.07.2026). Rundung/Mindestgrößen-Check nach vorn in die Sizing-Schicht;
   zu kleiner Rest → `reject_idea` statt APPROVED-Leiche.
3. **F080 — Stuck-Decision-Sweep unterscheidet permanent/transient:**
   `retry_stuck_decisions` retryte 6 nie ausführbare Decisions 10 Tage lang
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

1. **Wettbewerbs-Stichtag: ✅ entschieden 25.07.2026 — Montag, 03.08.2026.**
   8 Wochen → Ende Fr 25.09.2026. Reset aller Portfolios auf 5.000 USD;
   der bisherige Paper-Verlauf (seit 08.07.) wird zur "Vorsaison".
   Konsequenz: Block 0 + Block 1 (F079–F083) + Alpaca-Reset-Spike + F090
   müssen in der Woche 28.07.–01.08. fertig werden — ambitioniert, bewusst
   so gewählt. F084 (Review-Agent) darf nach dem Start nachziehen (Reviews
   sind rückwirkend berechenbar).
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
