# Phase 2 — Fundament: Definition of Done

Checkliste aus ARCHITECTURE.md §8. Wird laufend aktualisiert, während Claude Code Phase 2
abarbeitet (`/goal`-Session ab 2026-07-05).

- [x] `docker compose up` auf der UGREEN startet den kompletten Stack; alle Services
      healthy; Grafana-Container-Health-Alert aktiv und einmal testweise ausgelöst
      (Telegram-Nachweis)
      **Update (2026-07-05):** SSH-Zugriff auf die UGREEN eingerichtet (Public-Key,
      Details in [docs/deployment.md](../deployment.md)). Stack live deployt unter
      `/mnt/apps/docker/atlas/` (bestehende Konvention der Box). Port-Konflikt
      gefunden und gefixt: `web` lief lokal auf 3000, das ist auf der UGREEN aber
      die bestehende Grafana-Instanz — auf Host-Port 3001 umgestellt (Commit
      `1af11f1`). Alle 4 Container `healthy`, Migration gelaufen,
      `http://nas.fritz.box:3001/` liefert von einem anderen LAN-Rechner aus 200
      mit echten DB-Daten. Details, Port-Tabelle, bestehende Infrastruktur auf der
      Box: [docs/deployment.md](../deployment.md).
      **Weiterhin offen:** Grafana-Postgres-Datasource + Container-Health-Alert
      brauchen Grafana-Admin-Zugang (gehört zum bestehenden `monitoring`-Stack,
      nicht zu ATLAS) — Ralfs Aufgabe oder er gibt einen API-Key.
- [x] GitHub Actions CI: ruff, mypy (strict für `src/risk`, `src/broker`), pytest — grün auf
      `main`; Branch Protection: kein Merge ohne grüne CI
      **Nachweis:** [.github/workflows/ci.yml](../../.github/workflows/ci.yml),
      CI-Lauf grün: https://github.com/ralf-schmid/atlas/actions/runs/28722019207 (2026-07-05).
      **Offen — bewusst zurückgestellt (Ralfs Entscheidung, 2026-07-05):** Branch
      Protection lässt sich auf diesem Repo strukturell nicht setzen — GitHub liefert
      auf `PUT .../branches/main/protection` und auf `.../rulesets` jeweils 403
      "Upgrade to GitHub Pro or make this repository public". Privates Repo auf einem
      persönlichen Free-Account unterstützt Branch Protection/Rulesets grundsätzlich
      nicht, unabhängig von der Konfiguration. Optionen: GitHub Pro (~4 USD/Monat)
      oder Repo öffentlich machen (widerspricht "GitHub, privat" aus CLAUDE.md) — Ralf
      hat sich für "vorerst zurückstellen" entschieden. Befehl bleibt dokumentiert,
      falls später ein Pro-Upgrade kommt:
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
      **Offen:** Persistenz in `order_record` selbst (Adapter → DB) ist noch nicht
      verdrahtet, da noch kein Aufrufer (Handels-Agent) existiert, der Decision+Order
      zusammenführt.
- [x] Broker-Adapter: Paper-Order (1 Aktie Kauf + GTC-Stop) programmatisch platziert, Fill
      abgeholt, in `order_record` persistiert; Integrationstest läuft in CI gegen
      Alpaca-Paper (Keys via GitHub Encrypted Secrets)
      **Nachweis:** [F001](../features/F001-broker-adapter.md),
      `tests/broker/test_alpaca_paper_integration.py`, lokal gegen den echten
      VULTURE-Paper-Account verifiziert (OTO-Order-Fix nach echtem "wash trade"-Fund).
      **Update (2026-07-05):** GitHub Secrets `ALPACA_PAPER_VULTURE_KEY_ID`/
      `..._SECRET_KEY` gesetzt (Werte aus lokaler `.env`, den echten, bereits
      verifizierten VULTURE-Paper-Keys). Der CI-Integration-Job läuft ab dem nächsten
      Push/PR auf `main` als echter Test statt als Skip.
- [x] LiteLLM läuft mit 2 Providern (Anthropic + Groq); ein Budget-Limit testweise
      gerissen, Verhalten (Block + Log) verifiziert
      **Nachweis:** [F006](../features/F006-litellm-client.md) — Client + Orchestrator-
      Kosten-Bremse (`cost_guard.py`, 3-Stufen ok/warn/blocked) fertig und getestet,
      `docker-compose.yml` um `litellm`-Service ergänzt.
      **Update (2026-07-05):** echte Keys von Ralf besorgt, `litellm`-Container lokal
      hochgefahren (Docker jetzt repariert). Echter Call über den Proxy gegen beide
      Modelle verifiziert (`claude-haiku-4-5` → Anthropic, `claude-haiku-4-5-groq` →
      Groq, beide antworten). `LiteLLMClient.complete()` gegen den echten Proxy
      aufgerufen, echte Kosten aus `x-litellm-response-cost`-Header ausgelesen
      (0.000034 USD). `cost_guard.check_persona_budget()` mit den echten Caps aus
      `config/llm.yaml` (1.0 USD/Persona/Tag) verifiziert: 0 % → `OK`, 85 % → `WARN`,
      über 100 % (realer Spend + Cap) → `BLOCKED`.
- [x] Telegram-Bot: Testnachricht gesendet, Inline-Button-Callback empfangen und verarbeitet
      **Nachweis:** [F005](../features/F005-telegram-bot.md) — HITL-Flow, Timeout,
      Kommandos, Digest fertig und getestet (32 Tests, 100% Coverage auf den reinen Modulen).
      **Update (2026-07-05):** echter `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` von Ralf
      besorgt (`@ralf_atlas_bot`). Echte Testnachricht über die Bot-API verschickt und
      in Ralfs Chat angekommen.
      **Offen:** Inline-Button-Callback-Roundtrip (HITL-Approval) noch nicht live
      durchgespielt — braucht Ralf in Echtzeit am Handy, um den Button zu klicken;
      nachholen, sobald er Zeit hat.
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

## Zusammenfassung (Stand 2026-07-05, Session 3)

9 von 9 Punkten inhaltlich erledigt. Branch Protection bleibt strukturell blockiert
(GitHub-Plan-Limit) und ist auf Ralfs Entscheidung hin bewusst zurückgestellt, nicht
offen wegen fehlender Arbeit. Der ATLAS-Stack läuft jetzt live auf der UGREEN
(`/mnt/apps/docker/atlas/`, Details [docs/deployment.md](../deployment.md)) — SSH-Zugriff
per Public-Key eingerichtet, Port-Konflikt mit der bestehenden Grafana-Instanz gefunden
und gefixt, alle 4 Container healthy, von einem anderen LAN-Rechner aus verifiziert.

**Was noch offen ist:**
1. Grafana-Postgres-Datasource + Container-Health-Alert einrichten — braucht
   Grafana-Admin-Zugang zum bestehenden `monitoring`-Stack (nicht Teil von ATLAS);
   Ralfs Aufgabe, oder er gibt mir einen API-Key dafür
2. Einmal in Echtzeit den HITL-Inline-Button in Telegram klicken, wenn ich eine
   Test-Approval-Nachricht schicke (Callback-Roundtrip-Nachweis)
3. Falls Branch Protection gewünscht ist: GitHub Pro holen, dann sage ich Bescheid
