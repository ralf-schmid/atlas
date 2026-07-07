# F032 — Scheduler-Aktivierung

Status: umgesetzt
Datum: 2026-07-07
Phase: 4/5-Übergang

## 1. Zieldefinition

F025 (Zyklen-Scheduling) baute `scripts/run_scheduler.py` als Einstiegspunkt,
aber bewusst nicht als laufenden Prozess (F025 §1/§6: "Aktivierung erfordert
Ralfs ausdrückliches Go"). Ralf hat dieses Go am 2026-07-07 explizit gegeben
("starte den scheduler"). Dieses Feature verdrahtet den Scheduler als
Docker-Compose-Service, damit er dauerhaft auf der UGREEN läuft.

**Scope:** Neuer `scheduler`-Service in `docker-compose.yml`, ein
Config-Fix (LiteLLM-Base-URL-Override für Container-Netzwerk), Deployment.
**Nicht Scope:** Änderungen an der Orchestrator-/Zyklus-Logik selbst — die ist
seit F016–F025 fertig und live verifiziert (siehe `docs/dod/phase-4.md`).

## 2. Kritische Betrachtung

**Warum ein eigener Service statt den `api`-Container mitzunutzen:** Trennung
der Lebenszyklen — ein API-Neustart (z. B. Deploy eines UI-Fixes) darf einen
laufenden Orchestrator-Zyklus nicht unterbrechen, und umgekehrt darf ein
Scheduler-Crash die API nicht mitreißen. Beide teilen sich nur das Image
(`Dockerfile.api`, jetzt inkl. `scripts/`), nicht den Prozess.

**Der LiteLLM-Base-URL-Fix:** `config/llm.yaml` setzt `http://localhost:4000` —
korrekt für host-laufende manuelle Skripte (`scripts/run_cycle.py`, portweitergeleitet),
aber ein Container erreicht den `litellm`-Service darüber nicht (eigenes
Netzwerk-Namespace). Neuer optionaler Env-Override `LITELLM_BASE_URL` in
`load_llm_config()` (Env gewinnt vor YAML-Wert) — die YAML-Datei bleibt für den
Host-Fall unverändert, der Container setzt den Override selbst.

**Sicherheitsnetze, die bereits aktiv sind (nicht Teil dieses Features, aber
Voraussetzung für die Aktivierung):**
- HITL an (`config/hitl.yaml`: `paper: true`) — jeder `buy` pausiert bis zur
  Telegram-Freigabe.
- HITL-Timeout-Sweep (F030, heute gebaut) — eine nie beantwortete Anfrage hängt
  jetzt nicht mehr unbegrenzt.
- Scheduler-Fehler-Alert (F029, heute gebaut) — 2 aufeinanderfolgende
  Zyklus-Fehlschläge lösen einen Telegram-Alert aus.
- Kosten-Caps doppelt durchgesetzt (LiteLLM-Key-Budgets + `cost_ledger`,
  Budget-Race seit F028 geschlossen).
- Alle nötigen Credentials auf der Box vorab verifiziert vorhanden (Alpaca ×3
  Personas + Marktdaten, LiteLLM-Master-Key, Telegram).

**Kein `ports`-Eintrag für `scheduler`:** dient nur dem internen Scheduler-Loop,
keine HTTP-Schnittstelle.

## 3. Testdefinition (vor Umsetzung)

`tests/llm/test_config.py`:
1. `load_llm_config()` liefert ohne gesetzten Env-Var weiterhin den YAML-Wert
   (`http://localhost:4000`) — Regression für den Host-Fall.
2. Mit `LITELLM_BASE_URL` gesetzt überschreibt der Env-Wert den YAML-Wert.

Kein weiterer Testbedarf — die Zyklus-/Scheduler-Logik selbst ist durch F025/F029/F030
bereits abgedeckt; dieses Feature ist reine Infrastruktur-Verdrahtung.

## 4. Implementierung

`src/llm/config.py` (`LITELLM_BASE_URL`-Override), `Dockerfile.api`
(`COPY scripts ./scripts`), `docker-compose.yml` (neuer `scheduler`-Service).

## 5. Testdurchlauf

`uv run pytest tests/ --cov=src --cov-fail-under=90 -q` → 367 passed (365 + 2
neu). `uv run mypy src` → sauber. `uv run ruff check`/`ruff format --check` →
sauber. `docker-compose.yml` per `yaml.safe_load` strukturell validiert (lokal
kein laufender Docker-Daemon — echter Image-Build erst auf der Box, wie bei
`api`/`web` üblich).

**Kein lokaler Container-Start:** ein lokaler Start des `scheduler`-Containers
mit echten Credentials hätte von Ralfs Mac aus einen zweiten, parallel
laufenden Scheduler mit echten Order-/LLM-Calls gestartet — bewusst
unterlassen, Verifikation erfolgt direkt auf der Box nach dem Deploy.

## 6. Rollback-Pfad

**Sofort:** `sudo docker compose stop scheduler` auf der Box — hält den
Scheduler an, ohne postgres/litellm/api/web anzutasten (Container-Grenzen
sauber getrennt, siehe §2). Für einen vollständigen Rückbau:
`sudo docker compose rm -f scheduler` + Commit zurücknehmen (kein
Schema-Change, kein Datenverlust — bereits gelaufene Zyklen/Decisions bleiben
in der DB).
