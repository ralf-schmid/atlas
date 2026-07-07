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
      `internal_ledger`). [F016](../features/F016-orchestrator-graph-skeleton.md) —
      echter LangGraph-`StateGraph` mit Postgres-Checkpointer: legt einen `cycle` an,
      fanoutet per `Send` parallel über alle 6 aktiven Portfolios (je ein
      `agent_run`). Live verifiziert (2026-07-07): 1 `cycle`, 6 `agent_run`, 7 echte
      Checkpoint-Zeilen. [F017](../features/F017-shared-research-synthesis.md) —
      ersetzt F016s Platzhalter durch echte Synthese von `research_item`-Zeilen aus
      EDGAR/Screener/Publikationen/aktienfinder/Musterdepot, inkrementell seit dem
      letzten Cycle derselben `market_session`. Live verifiziert: 49 echte
      EDGAR-Filings → 49 `research_item`-Zeilen mit echten Titeln/Zeitstempeln.
      **Offen:** echte Persona-Analyse (LLM), Risk-Gate-Anbindung an echte
      Trade-Decisions, HITL, Handels-Agent — noch keine einzige echte `decision`-Zeile
      (bewusst, siehe F016 §1 Non-Scope).
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
2. ~~F016 — LangGraph-Graph-Grundgerüst~~ ✅ erledigt: echter `StateGraph` +
   Postgres-Checkpointer, `cycle`-Lebenszyklus, Send-Fanout über die 6 echten
   Portfolios, Platzhalter-`agent_run` je Persona — bewusst noch ohne
   `decision`-Zeilen (siehe F016 §1 Non-Scope), ohne Order-Pfad, ohne HITL.
3. ~~F017 — Shared-Research-Synthese~~ ✅ erledigt: `research_item`-Zeilen aus den
   bestehenden Ingestion-Tabellen (F009–F012, F014) statt dem F016-Platzhalter;
   `market_bar` bewusst ausgeschlossen (siehe F017 §1 Non-Scope).
4. ~~F018 — Persona-Charter-Prompts~~ ✅ erledigt: `src/personas/charters.py`,
   Philosophie/Universum/Signale wörtlich aus ARCHITECTURE.md §4.1–4.6, Guardrail-
   Zahlen live aus `config/personas/<name>.yaml`. Noch kein LLM-Call.
5. ~~F019 — Cost-Ledger-Enforcement~~ ✅ erledigt: `guarded_complete` prüft
   System-/Persona-Tagesbudget aus echten `cost_ledger`-Summen **vor** jedem
   LiteLLM-Call, schreibt danach den Ledger-Eintrag; `BLOCKED` verhindert den Call
   komplett. Musste vor dem ersten echten LLM-Call stehen (Invariante #7) — daher
   vorgezogen vor den Persona-Analyse-Agenten selbst.
6. Persona-Analyse-Agent (echte LLM-Calls über `guarded_complete`, nutzt F018s
   Charter + F017s Research-Pool), Risk-Gate-Anbindung an echte Trade-Decisions —
   braucht zusätzlich echten Broker-Kontostand (Equity/Cash/offene Positionen) als
   Risk-Gate-Eingabe, siehe F001/F002 BrokerAdapter.
7. HITL-Flow (Telegram-Approval, `interrupt()`/`Command(resume=...)`).
8. Handels-Agent (Order-Pfad, Privilege Separation, GTC-Stop).
9. Reporting-Agent.
10. Zyklen-Scheduling (APScheduler, `config/cycles.yaml`) — schließt auch die
    drei noch offenen Phase-3-Punkte (täglicher aktienfinder-/Screener-Lauf,
    5-Tage-Dauerlauf, PDF-Fallback-Poller).
