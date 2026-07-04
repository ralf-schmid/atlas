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
      **Status:** noch nicht begonnen.
- [ ] Telegram-Bot: Testnachricht gesendet, Inline-Button-Callback empfangen und verarbeitet
      **Status:** noch nicht begonnen.
- [ ] UI zeigt einen Portfolio-Snapshot aus der DB; mobil brauchbar (390 px; Lighthouse
      Mobile Performance/Accessibility ≥ 85)
      **Status:** noch nicht begonnen.
- [x] Alpaca-Spikes beantwortet, Ergebnisse als ADRs in `docs/adr/`
      **Nachweis:** [ADR-0001](../adr/0001-alpaca-paper-account-limit.md),
      [ADR-0002](../adr/0002-alpaca-crypto-de-residents.md),
      [ADR-0003](../adr/0003-alpaca-paper-starting-capital.md).
- [x] Coverage: `src/risk` und `src/broker` ≥ 90 % Lines
      **Nachweis:** [F004](../features/F004-risk-gate.md) — beide liegen bei 100% Line-
      **und** Branch-Coverage, in CI als Hard-Gate erzwungen (`--cov-fail-under=100`).

## Zusammenfassung

5 von 9 Punkten erledigt (bzw. mit klar benannten Restpunkten, die Ralfs Aktion brauchen:
GitHub Secrets, Branch Protection, UGREEN-Deployment). 4 Punkte noch offen: Docker-Vollstack,
LiteLLM, Telegram-Bot, FastAPI/UI — daran wird als Nächstes gearbeitet.
