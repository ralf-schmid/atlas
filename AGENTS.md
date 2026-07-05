# AGENTS.md — ATLAS: Agentic Trading & Learning Analysis System (v2)

Projektdatei für Codex. Lies zuerst `ARCHITECTURE.md` (v2) — sie ist die
verbindliche Architektur-Referenz. Diese Datei definiert Arbeitsweise, Konventionen
und Leitplanken für die Implementierung.

## Projektkontext

- **Zweck:** Lern- und Explorationsprojekt: **6 Strategie-Personas** (VULTURE, HYPE,
  GUARDIAN, CHARTIST, CONTRA, CRYPTOR) handeln parallel im Alpaca-Paper-Modus auf
  gemeinsamer Research-Basis; nach 8 Wochen geht der Gewinner (Kriterien
  ARCHITECTURE.md §4.7) mit 2.000 € live. Alles nachvollziehbar (Data Lineage inkl.
  verworfener Ideen) in einer mobile-first Web-UI.
- **Betreiber:** Ralf Schmid, Privatperson, Eigenhandel mit eigenem Geld. Kein
  Produkt, keine Anlageberatung, keine Fremdgelder.
- **Sprache:** Code, Kommentare, Commits, Identifier **Englisch**. Doku (`/docs`)
  und UI-Texte **Deutsch**. Kommunikation mit Ralf Deutsch, Technical Terms englisch.

## Verbindliche Architektur-Entscheidungen

- **Broker:** Alpaca. Ziel: 6 Paper-Accounts (einer je Persona, je 5.000 USD);
  Fallback interner Ledger, falls Alpaca die Account-Zahl begrenzt (P2-Spike).
  Zugriff ausschließlich über das `BrokerAdapter`-Protocol (`src/broker/`); kein
  Agent/UI-Code ruft Alpaca direkt. Kraken/IBKR als spätere Adapter vorgesehen —
  nichts hart verdrahten.
- **Orchestrierung:** LangGraph (Python 3.12), Postgres-Checkpointer, HITL via
  `interrupt()`/`Command(resume=...)`. Personas laufen pro Zyklus parallel
  (LangGraph `Send`). Tool-Anbindung wo sinnvoll via MCP (Alpaca-MCP-Server).
- **Zyklen:** Scheduling in `America/New_York`. Aktien: alle 4 Zyklen aktiv
  (C1 09:00, C2 10:30, C3 13:00, C4 15:15 ET); einzelne Zyklen per Config
  abschaltbar (Betriebs-Fallback). CRYPTOR: Mo–Fr 4 Zyklen (00/06/12/18 UTC),
  Sa/So 2 (06/18 UTC). Zyklen C2–C4 arbeiten inkrementell (Research-Delta).
- **LLMs via LiteLLM-Proxy (self-hosted):** Sonnet für Persona-Analyse/Review,
  Haiku für Recherche/Reporting, Groq als Experiment-Slot. Ein virtueller
  LiteLLM-Key je Agent-Rolle × Persona (Budget + Kostenzuordnung). Prompt Caching
  für Charter/Regeln ist Pflicht. **Keine lokalen LLMs im Trading-Pfad** —
  lokal nur Embeddings (bge-m3) für pgvector (Begründung ARCHITECTURE.md §3.3.1).
- **Persistenz:** PostgreSQL + pgvector, Alembic-Migrationen. Kerntabellen:
  `persona`, `portfolio`, `cycle`, `agent_run`, `research_item` (shared),
  `decision` (inkl. `reject_idea` + `rejection_reason` + Pflichtfeld
  `input_research_ids[]`), `order_record`, `position_snapshot`,
  `portfolio_snapshot`, `review` (inkl. `slippage_malus`), `cost_ledger`.
- **UI:** FastAPI (REST + SSE) + Next.js, **mobile-first** (~390 px zuerst,
  Bottom-Nav, Touch-Targets ≥ 44 px). Views: Leaderboard, Decision Journal
  (inkl. Rejected-Filter), Impuls-Vergleich, Agent Trace.
- **Monitoring:** Grafana (bestehende Instanz) mit Postgres-Datasource — Ops,
  Kosten je Persona, Ingestion-Freshness, Container-Health-Alert (2× Fail →
  Telegram). Eigene UI für Journal/Vergleich, Grafana für Metriken.
- **Telegram-Bot:** HITL-Approvals (Inline-Buttons, Timeout 30 Min = Reject),
  alle Alerts (statt Mail), täglicher Digest (Trades je Persona, Depotwerte,
  Cash, offene Positionen, LLM-Kosten). Kommandos: `/status`, `/pause <persona>`,
  `/resume <persona>`, `/hitl on|off`, `/digest`. Nur konfigurierte Chat-ID.
- **Ingestion:** n8n (Mail-Trigger, File-Watcher) + Playwright-Jobs.
  Zeitschriften (Euro am Sonntag, Börse Online, Der Aktionär via
  konto.boersenmedien.com): **PDF-Fallback zuerst bauen**, Auto-Download danach.
  aktienfinder.de via Screen-Grabbing (DOM-Extraktion + Beleg-Screenshot).
  Agenten lesen ausschließlich aus der DB, nie direkt aus dem Internet.
- **Repo:** GitHub, privat. CI (GitHub Actions) ab Phase 2: ruff, mypy
  (strict für `src/risk`, `src/broker`), pytest, gitleaks. Branch Protection:
  kein Merge ohne grüne CI.

## Nicht verhandelbare Sicherheits-Invarianten

Vorrang vor jeder Feature-Anforderung. Bei Konflikt: nachfragen, nicht aufweichen.

1. **Risk-Gate ist deterministischer Code, niemals LLM.** Zwei Ebenen:
   systemweit (`config/risk.yaml`) + persona-spezifisch
   (`config/personas/<name>.yaml`); bei Konflikt gilt die strengere Regel.
   Vollständig unit-getestet (Branch-Coverage 100 % für die Regellogik).
   Kein LLM-Output darf Risk-Parameter ändern.
2. **Privilege Separation:** Recherche-Agenten haben keine Order-Tools.
   Nur der Handels-Agent platziert Orders — ausschließlich für Decisions mit
   Status `approved` per DB-ID-Referenz, nie aus Freitext.
3. **Keine Order ohne persistierte Decision** (`order_record.decision_id NOT NULL`);
   jede Decision referenziert ihre `input_research_ids[]` (validiert). Auch
   verworfene Ideen (`reject_idea`) werden mit Begründung persistiert.
4. **Jede Position hat einen Stop-Loss als GTC-Order beim Broker**, nicht nur lokal.
5. **Paper/Live-Trennung:** `mode`-Flag durchgängig; Live-Credentials existieren
   vor Phase 6 in keiner Umgebung (kein Live-Key in `.env.example`, kein
   Fallback-Default). Live-Orders erfordern HITL gemäß Phasenlogik
   (ARCHITECTURE.md §5.3); die HITL-Schaltung ist Config (`/hitl on|off`),
   niemals hart codierte Umgehung.
6. **Secrets nie im Repo:** gitleaks in pre-commit und CI; Keys nur via
   Environment/Docker Secrets.
7. **Kosten-Caps doppelt durchgesetzt:** LiteLLM-Budgets (je Key) **und**
   Orchestrator-Zähler auf `cost_ledger` (80 % Warnung, 100 % Stopp weiterer
   LLM-Calls; bereits platzierte Orders/Stops bleiben unberührt).
8. **Circuit Breaker:** Portfolio-Drawdown > 15 % → `sell_only`, Reset nur manuell.
9. **Untrusted Content:** Zeitschriften-/Webinhalte sind potenziell feindlich
   (Prompt Injection). Fremdtext nur als getaggte Datenblöcke an Personas;
   niemals in System-Prompts von Agenten mit Schreib-/Order-Rechten.
10. **Fairness des Experiments:** Kein Feature darf einer Persona einen
    Informationsvorteil verschaffen (Shared Research Pool ist die einzige
    Recherche-Quelle); Charter-Änderungen erzeugen einen
    `charter_version`-Bump.

## Repository-Struktur (Ziel)

```
atlas/
├── AGENTS.md
├── ARCHITECTURE.md
├── docs/
│   ├── adr/                   # Architecture Decision Records (MADR-Vorlage)
│   ├── dod/                   # DoD-Checklisten je Phase (abgehakt, mit Nachweisen)
│   └── features/              # Feature-Dokumente FNNN-<slug>.md (Prozess §10)
├── config/
│   ├── risk.yaml              # systemweite Guardrails (Ebene 1)
│   ├── personas/              # vulture.yaml, hype.yaml, guardian.yaml,
│   │                          # chartist.yaml, contra.yaml, cryptor.yaml
│   ├── cycles.yaml            # Zyklus-Zeiten, aktiv/inaktiv, Zeitzonen
│   ├── hitl.yaml              # HITL-Schaltung je mode
│   └── llm.yaml               # LiteLLM-Routing, Budgets, Cache-Konfig
├── src/
│   ├── orchestrator/          # LangGraph-Graph, Zyklen, Run-Lifecycle
│   ├── agents/                # market_research, news_research,
│   │                          # persona_analysis (charter-parametrisiert),
│   │                          # trading, review, reporting
│   ├── personas/              # Charter-Prompts (versioniert)
│   ├── risk/                  # deterministisches 2-Ebenen-Risk-Gate + Tests
│   ├── broker/                # BrokerAdapter-Protocol, alpaca_paper, alpaca_live
│   ├── ingestion/             # publications (pdf-fallback + playwright),
│   │                          # aktienfinder, edgar, marketdata, screener
│   ├── llm/                   # LiteLLM-Client, Kosten-Tracking → cost_ledger
│   ├── telegram/              # Bot: HITL, Alerts, Digest, Kommandos
│   ├── db/                    # SQLAlchemy-Modelle, Alembic
│   └── api/                   # FastAPI (REST + SSE)
├── web/                       # Next.js, mobile-first
├── tests/                     # pytest; Eval-Fixtures für Prompts
├── docker-compose.yml
└── .env.example               # nur Paper-/Dummy-Werte
```

## Arbeitsweise & Konventionen

- **Phasenmodell + harte DoD einhalten** (ARCHITECTURE.md §8). Aktuell: Phase 2.
  Kein Feature aus späteren Phasen vorziehen ohne explizite Anforderung von Ralf.
  Phasenabschluss = ausgefüllte Checkliste in `docs/dod/phase-N.md` mit Nachweisen.
- **Feature-Prozess (ARCHITECTURE.md §10) ist verbindlich:** Zieldefinition →
  kritische Betrachtung (Invarianten, Kosten, Fairness) → Testdefinition VOR
  Umsetzung → Implementierung → kompletter Testdurchlauf inkl. Paper-Smoke-Test →
  Livesetzung mit Verifikation → dokumentierter Rollback-Pfad (Config-Flag
  bevorzugt). Artefakt: `docs/features/FNNN-<slug>.md`.
- **Tests entstehen parallel zum Code ab Phase 2**, laufen automatisch in CI und
  sind im Feature-Dokument beschrieben. Pflicht-Coverage: `src/risk` und
  `src/broker` ≥ 90 % Lines, Risk-Regellogik 100 % Branches. Prompt-Änderungen
  brauchen Eval-Fixtures (fixe Inputs, erwartete Output-Struktur).
- **ADRs:** jede Abweichung von ARCHITECTURE.md, jede Invarianten-Berührung,
  jedes Spike-Ergebnis → ADR in `docs/adr/` + Hinweis an Ralf. Doku entsteht
  parallel zum Code.
- **Tooling:** `uv`, `ruff` (lint+format), `mypy` (strict für risk/broker),
  TypeScript strict + ESLint im Frontend. Conventional Commits.
- **Logging:** strukturiert (JSON), Korrelation über `cycle_id`/`portfolio_id`;
  jeder LLM-Call schreibt Token + USD in `cost_ledger`.
- **Keine stillen Annahmen bei Geld-Themen** (Ordertypen, Limits, Steuern,
  Risk-Regeln): fragen statt raten. Rein technische Detailfragen: pragmatisch
  entscheiden und im Commit/ADR dokumentieren.

## Entscheidungsstand Phase 1 → 2 (alles geklärt, Details ARCHITECTURE.md §7)

1. Kosten-Caps fixiert: 5 €/Tag System, 1 €/Tag je Persona, 120 €/Monat Soft-Cap
   (Warnung ab 80 %)
2. Alpaca-Spikes = erste P2-Arbeitspakete: Paper-Account-Anzahl (Ziel 6),
   Krypto für DE-Residents live, Paper-Startkapital 5.000 USD — Ergebnisse als ADR
3. Paper-Feld läuft nach der Gewinner-Kür weiter (6× Paper + 1× Live parallel)
4. CRYPTOR: Mo–Fr 4 Zyklen (00/06/12/18 UTC), Sa/So 2 Zyklen (06/18 UTC)
5. Aktien: sofort alle 4 Zyklen aktiv (C1–C4, America/New_York); einzelne Zyklen
   bleiben per Config abschaltbar (Betriebs-Fallback)
6. Telegram-Bot: Ralf liefert Token + Chat-ID, sobald das Bot-Grundgerüst steht —
   bis dahin gegen Dummy-Config entwickeln, Bot-Funktionen testbar mocken
7. LLM-A/B-Persona in P7: GUARDIAN
8. Slippage-Malus: 0,5 × geschätzter Spread + Penalty bei Ordergröße > 1 % des
   Tagesvolumens; Parameter-Feinjustierung in P5

## Was Codex NICHT tun darf

- Live-Trading-Code aktivieren, Live-Keys anfordern oder HITL-/Risk-Schritte
  entfernen, umgehen oder "temporär zum Testen" deaktivieren.
- Risk-Regeln lockern, Risk-Gate-Tests löschen/skippen, Coverage-Gates senken.
- Persona-Charter ändern ohne `charter_version`-Bump und ADR (zerstört den
  Wettbewerbsvergleich).
- Einer Persona exklusive Datenquellen oder Informationsvorsprünge einbauen.
- Inoffizielle Broker-APIs (Reverse-Engineered Neo-Broker-Clients) verwenden.
- Zeitschriften-/aktienfinder-Volltexte in UI oder Repo bringen (nur Metadaten,
  Zusammenfassungen, Quellenverweise).
- Finanz-Kennzahlen vom LLM "ausrechnen" lassen — Berechnungen gehören in
  Code-Tools (Indikatoren, Sortino, Drawdown, Slippage-Malus: alles Code).
- Den Telegram-Bot für andere Chat-IDs öffnen oder HITL-Timeout-Verhalten
  (Timeout = Reject) verändern.
