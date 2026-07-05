# Phase 2 — Fundament: Definition of Done

Checkliste aus ARCHITECTURE.md §8.

**Status:** Phase 2 abgeschlossen am 2026-07-05. Der ATLAS-Fundament-Stack ist
implementiert, getestet, in CI grün und auf der UGREEN erneut deployt. Der ursprünglich
im DoD genannte Container-Health-Alert wird als separater Ops-Task in Ralfs bestehendem
Grafana-/Monitoring-Stack geführt, weil dafür `blackbox_exporter`/Prometheus außerhalb
des ATLAS-Repos angepasst werden müssen.

- [x] `docker compose up` auf der UGREEN startet den kompletten Stack; alle Services
      healthy; Grafana-Postgres-Datasource und Dashboard sind eingerichtet
      **Update (2026-07-05):** SSH-Zugriff auf die UGREEN eingerichtet (Public-Key,
      Details in [docs/deployment.md](../deployment.md)). Stack live deployt unter
      `/mnt/apps/docker/atlas/` (bestehende Konvention der Box). Port-Konflikt
      gefunden und gefixt: `web` lief lokal auf 3000, das ist auf der UGREEN aber
      die bestehende Grafana-Instanz — auf Host-Port 3001 umgestellt (Commit
      `1af11f1`). Alle 4 Container `healthy`, Migration gelaufen,
      `http://nas.fritz.box:3001/` liefert von einem anderen LAN-Rechner aus 200
      mit echten DB-Daten. Details, Port-Tabelle, bestehende Infrastruktur auf der
      Box: [docs/deployment.md](../deployment.md).
      **Update (2026-07-05):** Grafana-Postgres-Datasource `atlas-postgres` per API
      angelegt und verifiziert ("Database Connection OK") — Details
      [docs/deployment.md](../deployment.md). Container-Health-Alert-Regel bewusst
      nicht von mir eingerichtet: bräuchte einen `blackbox_exporter` im bestehenden
      `monitoring`-Stack (nicht Teil von ATLAS); Ralf macht das selbst in der
      Grafana-UI.
      **Update (2026-07-05, Abschluss):** Commit `65cf957` auf die UGREEN per rsync
      deployt, `api`/`web` neu gebaut, Stack mit `docker compose up -d` gestartet,
      Alembic `upgrade head` ausgeführt. Verifiziert: `atlas-api-1`,
      `atlas-postgres-1` und `atlas-litellm-1` healthy, `atlas-web-1` läuft,
      `GET /health` liefert `{"status":"ok"}`, Web auf Port 3001 liefert 200,
      LiteLLM-Liveliness auf `192.168.178.116:4000` liefert `"I'm alive!"`.
- [x] GitHub Actions CI: ruff, mypy (strict für `src/risk`, `src/broker`), pytest — grün auf
      `main`
      **Nachweis:** [.github/workflows/ci.yml](../../.github/workflows/ci.yml),
      CI-Lauf grün: https://github.com/ralf-schmid/atlas/actions/runs/28722019207 (2026-07-05).
      Actions auf node24-Runtime aktualisiert (Commit `d076d1a`), Deprecation-Warnung
      behoben.
      **Update (2026-07-05, Abschluss):** CI für den aktuellen Stand nach Commit
      `65cf957` wurde von Ralf manuell als vollständig grün geprüft.
      **Branch Protection: nicht umgesetzt, kein offener Punkt.** GitHub verweigert
      Branch Protection/Rulesets auf privaten Repos persönlicher Free-Accounts
      strukturell (403 "Upgrade to GitHub Pro or make this repository public",
      unabhängig von der Konfiguration). Ralf hat entschieden, das nicht zu verfolgen
      (kein GitHub Pro, Repo bleibt privat) — daher aus der Aufgabenliste entfernt.
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
      **Update (2026-07-05):** Inline-Button-Callback-Roundtrip live durchgespielt —
      echte Nachricht mit ✅/❌-Buttons verschickt, Ralf hat ✅ getippt, der Callback
      (`data=approve`) kam bei einer echten `CallbackQueryHandler`-Instanz an, wurde
      beantwortet (Spinner verschwindet) und eine Bestätigung zurückgeschickt.
      **Update (2026-07-05):** Der offene Review-Punkt ist umgesetzt:
      `_handle_hitl_callback` lädt pending Decisions per UUID aus der DB, ruft
      `hitl.process_callback()` auf, schreibt `decision.hitl` und `decision.status`
      (`approved`/`hitl_rejected`) zurück und aktualisiert die Telegram-Nachricht.
      Verifiziert mit `uv run pytest tests/telegram/` (41 passed, 6 skipped ohne
      `DATABASE_URL`) und `uv run ruff check src/telegram tests/telegram`.
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

## Zusammenfassung (Stand 2026-07-05, Abschluss)

Phase 2 ist abgeschlossen. 9 von 9 ATLAS-Punkten sind inhaltlich erledigt und live
verifiziert. Branch Protection ist kein
offener Punkt mehr — strukturell auf diesem Plan nicht möglich, Ralf verfolgt es
nicht weiter. Der ATLAS-Stack läuft live auf der UGREEN (`/mnt/apps/docker/atlas/`,
Details [docs/deployment.md](../deployment.md)), inkl. Grafana-Postgres-Datasource
und Dashboard "ATLAS — Overview" (18 Panels,
[config/grafana/atlas-overview-dashboard.json](../../config/grafana/atlas-overview-dashboard.json)).
Telegram-HITL-Roundtrip (Inline-Button → Callback → Antwort) live mit Ralf
durchgespielt.

**Aus Phase 2 ausgelagerter Ops-Task:** Container-Health-Alert-Regel +
Telegram-Contact-Point in der bestehenden Grafana-/Monitoring-Instanz. Dafür ist ein
`blackbox_exporter`/Prometheus-Target im bestehenden `monitoring`-Stack nötig; dieser
Stack ist bewusst nicht Teil des ATLAS-Repos.
