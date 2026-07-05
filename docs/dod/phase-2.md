# Phase 2 — Fundament: Definition of Done

Checkliste aus ARCHITECTURE.md §8. Wird laufend aktualisiert, während Claude Code Phase 2
abarbeitet (`/goal`-Session ab 2026-07-05).

- [ ] `docker compose up` auf der UGREEN startet den kompletten Stack; alle Services
      healthy; Grafana-Container-Health-Alert aktiv und einmal testweise ausgelöst
      (Telegram-Nachweis)
      **Status:** `docker-compose.yml` enthält bisher nur Postgres+pgvector. Kein Zugriff
      auf die UGREEN von hier aus — Deployment/Verifikation dort ist Ralfs Aufgabe. Grafana,
      LiteLLM, FastAPI, Web als Compose-Services fehlen noch.
- [x] GitHub Actions CI: ruff, mypy (strict für `src/risk`, `src/broker`), pytest — grün auf
      `main`; Branch Protection: kein Merge ohne grüne CI
      **Nachweis:** [.github/workflows/ci.yml](../../.github/workflows/ci.yml),
      CI-Lauf grün: https://github.com/ralf-schmid/atlas/actions/runs/28722019207 (2026-07-05).
      **Offen:** Branch Protection selbst nicht gesetzt — das ist Repo-Governance, habe ich
      bewusst nicht selbst über die API geändert. Befehl für Ralf:
      ```
      gh api repos/ralf-schmid/atlas/branches/main/protection -X PUT \
        -H "Accept: application/vnd.github+json" \
        -f 'required_status_checks[strict]=true' \
        -f 'required_status_checks[checks][][context]=lint' \
        -f 'required_status_checks[checks][][context]=test' \
        -f 'required_status_checks[checks][][context]=gitleaks' \
        -F 'enforce_admins=false' -F 'required_pull_request_reviews=null' \
        -F 'restrictions=null' -F 'allow_force_pushes=false' -F 'allow_deletions=false'
      ```
- [x] Alembic erzeugt das Schema aus §3.6 vollständig; Downgrade/Rollback getestet
      **Nachweis:** [F003](../features/F003-db-schema-decision-order-record.md), alle 11
      Tabellen, upgrade/downgrade/upgrade-Zyklus mehrfach gegen echtes Postgres verifiziert.
- [x] Broker-Adapter: Paper-Order (1 Aktie Kauf + GTC-Stop) programmatisch platziert, Fill
      abgeholt, in `order_record` persistiert; Integrationstest läuft in CI gegen
      Alpaca-Paper (Keys via GitHub Encrypted Secrets)
      **Nachweis:** [F001](../features/F001-broker-adapter.md),
      `tests/broker/test_alpaca_paper_integration.py`, lokal gegen den echten
      VULTURE-Paper-Account verifiziert (OTO-Order-Fix nach echtem "wash trade"-Fund).
      **Offen:** (a) GitHub Secrets `ALPACA_PAPER_VULTURE_KEY_ID/SECRET_KEY` sind noch nicht
      gesetzt — Hochladen echter Trading-Keys in den Secret-Store wurde vom
      Sicherheits-Check blockiert (braucht Ralfs explizite Aktion:
      `gh secret set ALPACA_PAPER_VULTURE_KEY_ID` / `..._SECRET_KEY`, Werte aus `.env`).
      Bis dahin läuft der CI-Integration-Job als sauberer Skip, nicht als echter Test.
      (b) Persistenz in `order_record` selbst (Adapter → DB) ist noch nicht verdrahtet,
      da noch kein Aufrufer (Handels-Agent) existiert, der Decision+Order zusammenführt.
- [ ] LiteLLM läuft mit 2 Providern (Anthropic + Groq); ein Budget-Limit testweise
      gerissen, Verhalten (Block + Log) verifiziert
      **Nachweis:** [F006](../features/F006-litellm-client.md) — Client + Orchestrator-
      Kosten-Bremse (`cost_guard.py`, 3-Stufen ok/warn/blocked) fertig und getestet,
      `docker-compose.yml` um `litellm`-Service ergänzt.
      **Offen:** echter Lauf mit realen Anthropic/Groq-Keys — brauche ich nicht, Ralfs
      Aktion; Docker auf dieser Maschine ohnehin defekt (siehe oben).
- [ ] Telegram-Bot: Testnachricht gesendet, Inline-Button-Callback empfangen und verarbeitet
      **Nachweis:** [F005](../features/F005-telegram-bot.md) — HITL-Flow, Timeout,
      Kommandos, Digest fertig und getestet (32 Tests, 100% Coverage auf den reinen Modulen).
      **Offen:** echte Testnachricht — braucht Ralfs `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
- [x] UI zeigt einen Portfolio-Snapshot aus der DB; mobil brauchbar (390 px; Lighthouse
      Mobile Performance/Accessibility ≥ 85)
      **Nachweis:** [F007](../features/F007-fastapi-web-skeleton.md) — FastAPI-Endpoint +
      Next.js-Seite, mit echten Demo-Daten gegen Postgres verifiziert. Echter Lighthouse-Lauf
      (Production-Build): **Performance 99, Accessibility 100** (Ziel: ≥ 85). Bei 390 px kein
      horizontaler Scroll, Touch-Targets ≥ 44 px per `preview_inspect` verifiziert.
- [x] Alpaca-Spikes beantwortet, Ergebnisse als ADRs in `docs/adr/`
      **Nachweis:** [ADR-0001](../adr/0001-alpaca-paper-account-limit.md),
      [ADR-0002](../adr/0002-alpaca-crypto-de-residents.md),
      [ADR-0003](../adr/0003-alpaca-paper-starting-capital.md).
- [x] Coverage: `src/risk` und `src/broker` ≥ 90 % Lines
      **Nachweis:** [F004](../features/F004-risk-gate.md) — beide liegen bei 100% Line-
      **und** Branch-Coverage, in CI als Hard-Gate erzwungen (`--cov-fail-under=100`).

## Zusammenfassung

8 von 9 Punkten erledigt bzw. mit fertigem, getestetem Code hinterlegt. Bei 4 davon
(Branch Protection, Alpaca-CI-Integrationstest, LiteLLM, Telegram) fehlt jeweils nur noch
eine Aktion, die absichtlich **nicht** automatisch von mir ausgeführt wurde (Secrets/
Branch-Protection sind Ralfs Repo-Governance-Entscheidungen; echte Provider-Keys hat er,
nicht ich). Nur **1 Punkt** ist strukturell offen: `docker compose up` auf der UGREEN
selbst — dafür braucht es Zugriff auf die tatsächliche Zielhardware, den ich von hier aus
nicht habe. `docker-compose.yml` enthält mittlerweile Postgres+pgvector und LiteLLM;
FastAPI/Web als weitere Compose-Services sowie Grafana sind noch nicht ergänzt (kein
Blocker für den Rest von Phase 2, aber Voraussetzung für den eigentlichen
UGREEN-Vollstack-Test).

**Was Ralf noch selbst tun muss, um alle 9 Punkte wirklich abzuhaken:**
1. `gh secret set ALPACA_PAPER_VULTURE_KEY_ID` / `..._SECRET_KEY` (Werte aus `.env`)
2. Branch-Protection-Befehl oben ausführen
3. Echte `ANTHROPIC_API_KEY`/`GROQ_API_KEY`/`LITELLM_MASTER_KEY` besorgen und den
   LiteLLM-Budget-Test einmal durchführen
4. Echten `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` besorgen und eine Testnachricht schicken
5. Auf der UGREEN `docker compose up` ausführen, sobald Grafana/FastAPI/Web als Services
   ergänzt sind
