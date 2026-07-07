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
      [F018](../features/F018-persona-charters.md) — Charter-Prompts für alle 6
      Personas. [F019](../features/F019-cost-ledger-enforcement.md) —
      Kosten-Bremse (Invariante 7) vor dem ersten echten LLM-Call.
      [F020](../features/F020-portfolio-risk-inputs.md) — echter Broker-Kontostand
      als Risk-Gate-Eingabe. [F021](../features/F021-persona-analysis-agent.md) —
      **erste echte `decision`-Zeilen.** Persona-Analyse-Agent mit echten LLM-Calls,
      Risk-Gate-Anbindung für `buy` (Sizing per LLM-Konfidenz × `max_position_pct` ×
      Equity), `hold`/`reject_idea` ohne Risk-Gate. Live verifiziert
      (voller lokaler Stack inkl. echtem LiteLLM-Proxy): alle 6 Personas mit echtem
      Sonnet-Call, plausible charaktertypische `hold`-Decisions, 0,13 USD
      Gesamtkosten, korrekte `cost_ledger`-Zeilen. **Offen:** `sell`/`close`
      (brauchen echte, vom Handels-Agenten eröffnete Positionen — noch nicht
      vorhanden), HITL, Handels-Agent (Order-Pfad) selbst.
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
6. ~~F020 — Portfolio-Risk-Gate-Eingaben~~ ✅ erledigt: `read_portfolio_risk_state`
   liest Equity/Cash/offene Positionen live über den echten `BrokerAdapter`
   (F001/F002), Peak-Equity aus der `portfolio_snapshot`-Historie (Kaltstart-Fallback:
   aktuelle Equity), Trades heute aus `order_record`/`decision`.
7. ~~F021 — Persona-Analyse-Agent~~ ✅ erledigt: echte LLM-Calls über
   `guarded_complete`, nutzt F018s Charter + F017s Research-Pool + F020s
   Risk-Inputs; `hold`/`reject_idea` direkt, `buy` durchs Risk-Gate (Sizing-Formel
   mit Ralf abgestimmt: `conviction × max_position_pct × equity`). `sell`/`close`
   bewusst zurückgestellt bis der Handels-Agent echte Positionen erzeugt.
8. HITL-Flow (Telegram-Approval, `interrupt()`/`Command(resume=...)`).
9. Handels-Agent (Order-Pfad, Privilege Separation, GTC-Stop).
10. Reporting-Agent.
11. Zyklen-Scheduling (APScheduler, `config/cycles.yaml`) — schließt auch die
    drei noch offenen Phase-3-Punkte (täglicher aktienfinder-/Screener-Lauf,
    5-Tage-Dauerlauf, PDF-Fallback-Poller).
