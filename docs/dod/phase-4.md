# Phase 4 — Agenten-Core: Definition of Done

Checkliste aus ARCHITECTURE.md §8.

**Status:** gestartet 2026-07-07, nicht abgeschlossen. Voraussetzung aus Phase 3 (die
zwei noch offenen Live-Nachweise ohne Scheduler-Abhängigkeit) vorab geklärt, siehe
`docs/dod/phase-3.md` Update 2026-07-07.

- [ ] Vollständiger Zyklus läuft automatisch für alle 6 Portfolios; jede Persona
      erzeugt decisions inkl. `reject_idea`; `input_research_ids`-Pflicht wird
      DB-seitig validiert
      **Teilweise:** [F015](../features/F015-persona-portfolio-seed.md) — die 6
      echten `persona`/`portfolio`-Zeilen existieren jetzt (idempotenter Seed, live
      gegen die lokale DB verifiziert: native Personas mit den echten
      Alpaca-Paper-Account-IDs aus ADR-0001, virtuelle Personas mit
      `internal_ledger`). **Offen:** der eigentliche LangGraph-Graph (Shared
      Research → Send-Fanout → Persona-Analyse → Risk-Gate → HITL → Handels-Agent →
      Reporting) existiert noch nicht — kommt als nächstes Feature.
- [ ] Risk-Gate: beide Regelebenen implementiert, 100 % Branch-Coverage der
      Regellogik; je Regelklasse mindestens ein echter Reject im Testlauf
      dokumentiert
      **Vorarbeit aus Phase 2** ([F004](../features/F004-risk-gate.md)): Regellogik
      + Coverage-Ziel bereits erfüllt. **Offen:** der "echte Reject im Testlauf"
      braucht den laufenden Orchestrator-Zyklus, nicht nur Unit-Tests.
- [ ] HITL: Approve, Reject und Timeout alle drei end-to-end nachgewiesen;
      `/hitl off` wirkt ohne Neustart
- [ ] 5 Handelstage in Folge: alle geplanten Zyklen (4/Tag Aktien +
      CRYPTOR-Plan) gelaufen, 0 unbehandelte Exceptions; Crash-Recovery getestet
      (Container-Kill mitten im Zyklus → Resume via Postgres-Checkpointer)
- [ ] Tageskosten ≤ Cap; `cost_ledger` stimmt stichprobenhaft mit
      LiteLLM-Abrechnung überein
- [ ] Telegram-Tagesdigest kommt täglich; Zahlen gegen DB-Query verifiziert

## Geplante Feature-Reihenfolge (Stand 2026-07-07, kann sich ändern)

1. ~~F015 — Persona/Portfolio-Seed~~ ✅ erledigt.
2. F016 — LangGraph-Graph-Grundgerüst: Dependency-Entscheidung (`langgraph` +
   Postgres-Checkpointer-Paket), Zyklus-Lebenszyklus (`cycle`-Zeile anlegen),
   Send-Fanout über die 6 echten Portfolios, Platzhalter-Persona-Knoten (erzeugt
   echte `reject_idea`-Decisions mit validierten `input_research_ids`, noch ohne
   LLM-Analyse) — bewusst ohne Order-Pfad, ohne HITL, ohne echte Persona-Logik.
3. Shared-Research-Synthese: `research_item`-Zeilen aus den bestehenden
   Ingestion-Tabellen (F008–F014) ableiten statt Platzhaltern.
4. Persona-Analyse-Agent (echte LLM-Calls über LiteLLM, Charter-Prompts aus
   `src/personas/`), Risk-Gate-Anbindung an echte Trade-Decisions.
5. HITL-Flow (Telegram-Approval, `interrupt()`/`Command(resume=...)`).
6. Handels-Agent (Order-Pfad, Privilege Separation, GTC-Stop).
7. Reporting-Agent, Kosten-Tracking-Anbindung an `cost_ledger`.
8. Zyklen-Scheduling (APScheduler, `config/cycles.yaml`) — schließt auch die
   drei noch offenen Phase-3-Punkte (täglicher aktienfinder-/Screener-Lauf,
   5-Tage-Dauerlauf, PDF-Fallback-Poller).
