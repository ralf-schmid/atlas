# Security-Audit 2026-07-07 — offene Punkte (priorisiert zu bearbeiten)

Ergebnis eines vollständigen White-Box-Codereviews (Claude Code, 2026-07-07) über
die gesamte Codebasis (Stand nach F025). Die im Audit **behobenen** Findings sind
als `fix:`-Commits vom selben Tag dokumentiert; dieses Dokument hielt ursprünglich
die **nicht** behobenen Punkte als priorisierte TODOs fest.

**Update (10.07.2026, Dokumentations-Audit):** Nachträglich gegen den aktuellen
Code geprüft — P1–P5 sind inzwischen alle behoben (siehe Referenzen je Punkt),
blieben in diesem Dokument aber fälschlich als offene TODOs stehen. Nur noch P6
(teilweise) und P7 (teilweise) haben echte offene Punkte.

Kennzeichnung: **[SEC-AUDIT]** — bei Feature-Planung (Prozess ARCHITECTURE.md §10)
vorrangig einplanen.

## P1 — ✅ behoben: `check_stop_orders()` wird jetzt jeden Zyklus aufgerufen

War: `InternalLedgerAdapter.check_stop_orders()` lief für keine virtuelle Persona
(HYPE/CONTRA/CRYPTOR) — Stop-Losses hätten nie ausgelöst.

**Behoben (F026):** `_sweep_stop_orders` in `src/orchestrator/persona_analysis.py`
ruft `broker_adapter.check_stop_orders()` am Anfang jedes
`analyze_persona_cycle`-Laufs auf (No-Op für native Alpaca-Adapter, die brauchen
das nicht).

## P2 — ✅ behoben: Order-Ausführung ist jetzt crash-idempotent

War: ein Prozess-Crash zwischen `place_order()` und DB-Commit hätte bei einem
LangGraph-Replay dieselbe Order doppelt platziert.

**Behoben (F027):** `client_order_id = str(decision_id)` in
`src/broker/alpaca_paper.py` — Alpaca dedupliziert selbst, ein Replay erkennt den
Duplicate-Fehler und holt sich die bereits platzierte Order
(`_is_duplicate_client_order_id`).

## P3 — ✅ behoben: Budget-Check-Race bei parallelem `Send`-Fanout

War: `guarded_complete` prüfte Summe→Call→Insert nicht atomar; 6 parallele
Personas konnten den Tages-Cap um bis zu ~6 Calls überschießen.

**Behoben:** Postgres Session-Advisory-Lock (`_system_budget_lock`,
`src/llm/ledger.py`) um den Recheck+Insert nach dem LLM-Call (nicht um den Call
selbst — der bleibt parallel). Am 10.07.2026 um den analogen Persona-Cap-Recheck
ergänzt ([F055](features/F055-persona-budget-post-call-check.md) — der
System-Cap-Recheck allein fing einen einzelnen Call nicht ab, der eine Persona
für sich allein über ihr enges Tages-Cap hob).

## P4 — ✅ behoben: strukturiertes Logging + Scheduler-Fehler-Alert

War: `print()`-Logging, ein fehlgeschlagener Zyklus erzeugte keinen Telegram-Alert.

**Behoben (F029):** `src/logging_config.py` (JSON-Logging mit
`cycle_id`/`portfolio_id`-Korrelation), `_send_cycle_failure_alert` in
`src/orchestrator/scheduler.py` (2×-Fail-Eskalation, gleiches Muster wie
Container-Health). Am 10.07.2026 ergänzt: `httpx`-Logger auf `WARNING`, weil er
sonst den Telegram-Bot-Token im Klartext geloggt hätte
([F056](features/F056-httpx-token-log-leak.md)).

## P5 — ✅ behoben: HITL-Timeout-Sweep

War: nie beantwortete HITL-Anfragen blieben unbegrenzt `HITL_PENDING`
(fail-closed, kein Sicherheitsrisiko, aber Verfügbarkeits-Gap).

**Behoben (F030):** periodischer `hitl-timeout-sweep`-Job
(`sweep_expired_hitl_decisions`, `src/orchestrator/scheduler.py`), löst
abgelaufene Pending-Decisions per Timeout-Regel auf und resumed den Interrupt mit
"rejected". Analoges Muster am 10.07.2026 für liegengebliebene, am Broker
fehlgeschlagene `APPROVED`-Decisions ergänzt
([F050](features/F050-stop-loss-tick-rounding.md) §1,
`retry_stuck_decisions`).

## P6 — Dependency-Findings [SEC-AUDIT, teilweise offen]

- **Weiterhin offen:** `npm audit` (web/) meldet weiterhin ein verwundbares
  `postcss` < 8.5.10 über Next.js (moderate, GHSA-qx2v-qp2m-jg93), erneut
  geprüft 10.07.2026 — weiterhin kein Fix ohne Breaking-Change verfügbar
  (`npm audit fix --force` würde auf `next@9` downgraden). **TODO bleibt:**
  Next.js auf gepatchte Version heben, sobald verfügbar.
- **✅ Erledigt, anders als geplant:** `.github/dependabot.yml` überwacht sowohl
  `uv` (Python) als auch `npm` (`web/`) wöchentlich — deckt denselben Bedarf wie
  das ursprünglich vorgeschlagene manuelle `pip-audit`-CI-Schritt ab.

## P7 — Härtung, geringe Priorität [SEC-AUDIT, teilweise offen]

- **✅ Behoben:** Postgres-Passwort auf der UGREEN rotiert (`POSTGRES_PASSWORD`
  in der Box-`.env`, `ALTER ROLE` im laufenden Cluster) — siehe
  `docs/deployment.md` "Postgres-Passwort rotiert (07.07.2026)".
  `docker-compose.yml`s `${POSTGRES_PASSWORD:-atlas}`-Fallback ist bewusst nur
  ein Dev-Default, nicht das, was auf der Box tatsächlich läuft.
- **✅ Behoben:** "trades today" (`src/orchestrator/risk_inputs.py`,
  `_count_trades_today`) zählt jetzt den Handelstag in der Markt-Zeitzone
  (`America/New_York`), nicht mehr den UTC-Kalendertag.
- **✅ Behoben:** `_parse_cost_header` (`src/llm/client.py`) parst defensiv —
  ein fehlender/kaputter Kosten-Header loggt einen Fehler und fällt auf `0.0`
  zurück, statt den bereits bezahlten Call ganz zu verlieren.
- **Weiterhin offen:** Kosten-Semantik — CLAUDE.md/ARCHITECTURE.md definieren
  die Caps in EUR ("5 €/Tag systemweit, 1 €/Tag je Persona"), `config/llm.yaml`
  und `cost_ledger` rechnen aber durchgängig in USD (`system_daily_usd`,
  `persona_daily_usd`, LiteLLMs `x-litellm-response-cost`-Header ist USD).
  Keine Wechselkurs-Umrechnung im Code. **TODO bleibt:** entweder die Caps
  explizit als USD-Zahlen dokumentieren (Realität) oder eine echte
  EUR-Umrechnung einbauen — Ralfs Entscheidung, da es die tatsächliche
  Kosten-Obergrenze verändert.
- **Akzeptiert, kein TODO:** API bleibt auth-los (F007-Design,
  Single-User-LAN) — akzeptabel, solange die Bindung an `ATLAS_BIND_IP`
  aktiv ist und kein Port-Forwarding auf 8000/3001 existiert (unverändert
  seit 07.07.2026).
