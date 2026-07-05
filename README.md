# ATLAS — Agentic Trading & Learning Analysis System

**Ein Multi-Agent-Experiment:** Sechs KI-Personas mit gegensätzlichen Anlage-Philosophien handeln parallel im Alpaca-Paper-Modus auf gemeinsamer Research-Basis. Nach 8 Wochen geht der Gewinner mit 2.000 € echtem Kapital live. Jede Entscheidung — auch jede verworfene Idee — ist vollständig nachvollziehbar.

---

## Kurzbeschreibung

**ATLAS** ist ein Lern- und Explorationsprojekt, das ausloten soll, was mit heutigen Agentic-AI-Mitteln im Finanzumfeld möglich ist. Das System funktioniert als geschlossenes Ökosystem:

- **6 Strategie-Personas** (VULTURE, HYPE, GUARDIAN, CHARTIST, CONTRA, CRYPTOR) analysieren identische Marktinformationen und treffen parallel Handelsentscheidungen
- **Shared Research Layer:** Teure Forschungsagenten laufen 1× pro Zyklus; alle Personas bewerten dieselben Impulse durch ihre eigene "Brille"
- **Deterministische Guardrails:** Ein LLM-freies Risk-Gate setzt Positionsgrößen, Stop-Loss-Pflichten und Budget-Limits durch — kein LLM darf seine eigenen Limits ändern
- **Data Lineage:** Jede Order — und jede verworfene Idee — ist bis zur Quelle rückverfolgbar
- **Demo → Live Workflow:** 8 Wochen Paper-Wettbewerb, dann geht der Gewinner (nach vorab fixierten Kriterien, nicht post-hoc-Sympathie) ins echte Geld
- **Transparente Metriken:** Rohleistung vs. slippage-adjustierte Performance je Persona; ehrlicher statistischer Disclaimer: 8 Wochen sind Rauschen

---

## Kern-Features

| Feature | Details |
|---------|---------|
| **Agenten-Framework** | LangGraph (Python 3.12) + Postgres-Checkpointing für Crash-Recovery |
| **Tool-Anbindung** | MCP (Model Context Protocol), Alpaca-MCP-Server für Trading + Marktdaten |
| **LLMs** | Claude Sonnet (Analyse/Review), Claude Haiku (Recherche), über LiteLLM-Proxy mit Budget-Enforcement |
| **Broker** | Alpaca (Paper + Live), Fallback/Ausbau: Kraken (Krypto), IBKR (EU-Assets) |
| **Zyklen** | 4 pro Handelstag (09:00, 10:30, 13:00, 15:15 ET) + CRYPTOR 24/7 mit Wochenend-Reduktion |
| **Ingestion** | Börsenmedien-Abos (PDF + Auto), aktienfinder-Grabbing, EDGAR, Web-Search |
| **UI** | Next.js/React, mobile-first; 4 Views: Leaderboard, Decision Journal, Impuls-Vergleich, Agent Trace |
| **Monitoring** | Grafana (Ops, Kosten/Persona, Container-Health → Telegram), PostgreSQL-Datasource |
| **Alerts & HITL** | Telegram-Bot: Approvals (Inline-Buttons, 30 Min Timeout = Reject), Alerts, täglicher Digest |

---

## Architektur

Die verbindliche Architektur ist in zwei Dokumenten definiert:

1. **`ARCHITECTURE.md`** — vollständige technische Architektur, Datenmodell, Agenten-Design, Guardrails, Phasenplan mit harten DoD (Definition of Done), Feature-Einbau-Prozess, Risiken & Mitigationen. **Lesen Sie dieses Dokument zuerst.**

2. **`AGENTS.md`** — Projektdatei für Codex: Konventionen, Repo-Struktur, nicht verhandelbare Sicherheits-Invarianten, Arbeitsweise. Definiert, was Code NICHT darf (z.B. Live-Keys vor Phase 6, Risk-/HITL-Umgehung, Persona-Bevorzugung).

**Die Doku entsteht parallel zum Code, nicht danach.** Architecture Decision Records (ADRs) gehören nach `docs/adr/`.

---

## Projekt-Status

### Phase 1: Architektur ✅
- Alle Entscheidungen getroffen und konsistent (Entscheidungsstand §7 in ARCHITECTURE.md)
- 6 Personas rationale definiert, Data-Lineage-Modell entworfen, Feature-Prozess etabliert
- Kosten-Modell und Guardrails fixiert
- **Freigegeben für Phase 2**

### Phase 2: Fundament ✅ abgeschlossen
- [x] Docker-Compose-Stack auf der UGREEN live deployt; API, Web, Postgres und LiteLLM laufen healthy
- [x] GitHub Actions CI mit ruff, mypy und pytest ist grün; Branch Protection ist auf dem privaten Free-Repo strukturell nicht verfügbar
- [x] Alembic-Schema für die Kerntabellen aus ARCHITECTURE.md §3.6 steht und ist upgrade/downgrade-getestet
- [x] Broker-Adapter: Alpaca-Paper-Order inklusive GTC-Stop getestet; interner Ledger als Fallback vorhanden
- [x] LiteLLM-Proxy mit Anthropic + Groq verifiziert; Orchestrator-Kostenbremse getestet
- [x] Telegram-Bot-Grundgerüst inklusive HITL-Inline-Callbacks, Chat-ID-Gate, Timeout = Reject und DB-Persistenz auf `decision.hitl`
- [x] FastAPI + Next.js zeigen Portfolio-Snapshots aus der DB; mobile Lighthouse-Ziele erreicht
- [x] Alpaca-Spikes als ADRs dokumentiert

Details und Nachweise stehen in `docs/dod/phase-2.md`. Der Container-Health-Alert
in Ralfs bestehender Grafana-/Monitoring-Instanz ist als separater Ops-Task
aus Phase 2 ausgelagert.

### Weitere Phasen
Phase 3 (Ingestion), Phase 4 (Agenten-Core), Phase 5 (Review & Wettbewerb-Start), Phase 6 (Live), Phase 7 (Autonomie & Experimente) — siehe ARCHITECTURE.md §8 für vollständige DoD.

---

## Getting Started (Phase 2+)

### Voraussetzungen
- **Hosting:** UGREEN DXP4800 Pro (TrueNAS), Docker Compose
- **Broker:** Alpaca-Konto + Paper-Accounts (6 geplant)
- **Secrets:** Alpaca-Keys, LLM-API-Keys (via LiteLLM-Proxy), Telegram-Bot-Token + Chat-ID (von Ralf)
- **VPN:** Zugriff nur via bestehende Tailscale/VPN

### Lokal entwickeln/testen
```bash
# Repo klonen
git clone <privates-repo>
cd atlas

# Umgebung vorbereiten
cp .env.example .env
# .env ausfüllen: nur Paper-Keys + Dummy-Werte für P2

# Docker-Stack starten (erfordert TrueNAS/Docker)
docker compose up -d

# Tests laufen
pytest tests/

# Lint/Format
ruff check src/
ruff format src/
mypy src/risk src/broker --strict
```

### Dateistruktur
```
atlas/
├── ARCHITECTURE.md        # Verbindliche Architektur (lesen Sie zuerst!)
├── AGENTS.md             # Projektdatei für Codex
├── README.md             # Diese Datei
├── config/               # Konfiguration (Risk-Regeln, Personas, Zyklen, HITL)
├── src/                  # Python: Orchestrierung, Agenten, DB, Broker, API
├── web/                  # Next.js Frontend
├── tests/                # pytest
├── docker-compose.yml    # Stack-Definition
└── docs/                 # Architektur-Entscheidungsrecords (ADRs), DoD-Checklisten, Features
```

---

## Wichtigste Konventionen

- **Sprache:** Code/Commits/Identifier auf Englisch; Doku/UI auf Deutsch; Kommunikation mit Ralf auf Deutsch (Technical Terms englisch)
- **Sicherheits-Invarianten:** 10 nicht verhandelbare Regeln (AGENTS.md) — bei Konflikt: nachfragen, nicht aufweichen
- **CI/CD:** GitHub Actions ab Phase 2 — ruff, mypy strict, pytest, gitleaks (keine Live-Keys im Repo)
- **Feature-Prozess:** Zieldefinition → kritische Betrachtung → Testdefinition (vor Code!) → Umsetzung → Paper-Smoke-Test → Livesetzung (ARCHITECTURE.md §10)
- **Tests:** Risk-Gate und Broker-Adapter müssen 100 % Branch-Coverage haben; Prompt-Prompts brauchen Eval-Fixtures
- **Secrets:** niemals im Repo; nur via `.env` (in `.gitignore`) oder Docker Secrets; `.env.example` enthält nur Dummies

---

## Kostenmodell & Budgets (Phase 2+)

| Budget | Limit | Details |
|--------|-------|---------|
| **täglich (System)** | 5 € | Hard Cap: LiteLLM + Orchestrator stoppen LLM-Calls bei Überschreitung |
| **täglich (je Persona)** | 1 € | Hard Cap via LiteLLM-Key-Budget |
| **monatlich (Soft Cap)** | 120 € | Telegram-Warnung ab 80 %; kein Hard Stop, aber Aufmerksamkeitsschwelle |

LLMs werden über **LiteLLM-Proxy** mit Konto-Budgets pro Rolle × Persona — Kosten landen in Grafana, Kostenzuordnung fällt gratis ab. Prompt Caching für Charter/Regeln ist Pflicht.

---

## Live-Phase (Phase 6+)

Das System läuft 8 Wochen im Paper-Modus, danach wird der Gewinner nach vorab fixierten Kriterien (Sortino Ratio, adjustierte Rendite, Max Drawdown, Thesen-Qualität, operative Zuverlässigkeit) bestimmt. Der Gewinner geht dann mit **2.000 € echtem Kapital** live; die übrigen 5 Personas laufen im Paper-Modus weiter (Quartals-Re-Evaluation des Live-Gewinners gegen das Feld).

**Human-in-the-Loop Phasenlogik:**
- Paper Wochen 1–2: HITL an (Telegram-Approve je Order)
- Paper Wochen 3–8: HITL aus (Config-Flag)
- Live Start: HITL wieder an
- Live nach 4 Wochen ohne Risk-Inzidenz: HITL aus (per ADR)

---

## Erfolgskriterien

1. **8+ Wochen autonomer Betrieb** (Paper) + 8+ Wochen Live ohne manuelle Eingriffe in den Kern-Loop
2. **Vollständige Data Lineage:** jede Order und jede verworfene Idee bis zur Quelle rückverfolgbar (UI-Nachweis)
3. **Impuls-Vergleich:** Dokumentierte Beispiele, wie 6 Philosophien denselben Input unterschiedlich bewerten
4. **Transparente Performance:** alle Personas gegen S&P-500-Benchmark; Underperformance ist ein valides Ergebnis
5. **Übertragbares technisches Wissen:** LangGraph, MCP, Guardrail-Design, HITL, Kosten-Governance — beruflich referenzierbar

---

## Wichtige Warnung

🚨 **Dies ist ein Lern- und Explorationsprojekt, kein Finanzprodukt.**

- **Kein Renditeversprechen.** Die Wahrscheinlichkeit, dass automatisierte Agenten eine Markt-Nullhypothese schlagen, ist niedrig.
- **Kein Fremdkapital.** Eigenhandel mit eigenem Geld; keine Dienstleistung für Dritte.
- **Eigenverantwortung.** Trading mit echtem Geld birgt reales Verlust-Risiko. Der Live-Betrieb startet mit konservativ dimensioniertem Kapital und expliziten Kill-Switches (Circuit Breaker bei 15 % Drawdown).

Alle Risikomodelle, Guardrails und Testpläne sind in ARCHITECTURE.md §12 dokumentiert.

---

## Kontakt & Autor

**Maintainer:** Ralf Schmid  
**Betreiber:** Privatperson (Eigenhandel)  
**Status:** Aktives Lernprojekt (Phase 2)  
**Lizenz:** Privat (nicht publiziert)

**Kommunikation:** Deutsch über GitHub Issues/Discussions oder direkt mit Ralf; Code-Sprache: Englisch.

---

## Weitere Ressourcen

- **ARCHITECTURE.md** — vollständige technische Architektur, Datenmodell, Phasenplan, Risk-Modell, Persona-Rationale
- **AGENTS.md** — Projektdatei für Codex, Repo-Struktur, Konventionen, nicht verhandelbare Regeln
- **docs/adr/** — Architecture Decision Records (entsteht parallel zum Code)
- **docs/dod/** — Definition-of-Done-Checklisten je Phase (mit Nachweisen)
- **docs/features/** — Feature-Dokumentation (Zieldefinition, Testplan, Rollback, Deployment-Datum)

---

## Danksagungen

Dieses Projekt entstand in enger Zusammenarbeit mit Claude (Anthropic) für die Architektur-Design, Phase-Planung und Multi-Agent-Orchestrierung. Die technische Realisierung verbindet LangGraph, MCP, FastAPI, PostgreSQL und Alpaca-APIs in einem durchgängig nachvollziehbaren System.

---

**Zuletzt aktualisiert:** Juli 2026  
**Phase:** 2 (Fundament abgeschlossen)  
**Status:** UGREEN-Stack live, CI grün, bereit für Phase 3
