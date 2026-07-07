# Security-Audit 2026-07-07 — offene Punkte (priorisiert zu bearbeiten)

Ergebnis eines vollständigen White-Box-Codereviews (Claude Code, 2026-07-07) über
die gesamte Codebasis (Stand nach F025). Die im Audit **behobenen** Findings sind
als `fix:`-Commits vom selben Tag dokumentiert; dieses Dokument hält die **nicht**
behobenen Punkte als priorisierte TODOs für den nächsten Entwicklungszyklus fest.

Kennzeichnung: **[SEC-AUDIT]** — bei Feature-Planung (Prozess ARCHITECTURE.md §10)
vorrangig einplanen. Punkte P1–P2 berühren Sicherheits-Invarianten bzw. Geldpfade
und wurden bewusst NICHT automatisch gefixt (CLAUDE.md: „Keine stillen Annahmen
bei Geld-Themen"), weil sie Handelsverhalten ändern.

## P1 — `check_stop_orders()` wird nirgends aufgerufen (Invariante #4) [SEC-AUDIT]

`InternalLedgerAdapter.check_stop_orders()` (src/broker/internal_ledger.py) muss
laut F002 §2 „once per orchestrator cycle" für jede virtuelle Persona laufen —
kein Code-Pfad ruft es auf. Konsequenz: Für HYPE, CONTRA, CRYPTOR triggern
Stop-Losses **nie**; die Pending-Stops liegen tot im JSON-Ledger. Für die
nativen Personas (Alpaca-Bracket-Order) besteht das Problem nicht.

- **TODO:** Als eigenes Feature (FNNN, Testdefinition vor Umsetzung) den
  Stop-Sweep in den Zyklus einbauen — z. B. am Anfang von `analyze_persona_cycle`
  bzw. im `persona_analysis`-Knoten, nur für `internal_ledger`-Adapter.
- **Achtung:** Löst reale (virtuelle) Verkäufe aus → Paper-Smoke-Test Pflicht.

## P2 — Order-Ausführung nicht crash-idempotent [SEC-AUDIT]

Stirbt der Prozess zwischen `broker_adapter.place_order()` und dem DB-Commit
(src/orchestrator/trading.py → Commit erst im Graph-Knoten), platziert ein
LangGraph-Replay dieselbe Order erneut (Doppelkauf).

- **TODO:** Alpacas `client_order_id` mit der `decision_id` belegen — der Broker
  dedupliziert dann selbst. Für den InternalLedgerAdapter analog eine
  Decision-ID-Sperre im LedgerState.
- Betrifft `place_order`-Signatur (`decision_id` wird aktuell per `del` verworfen).

## P3 — Budget-Check-Race bei parallelem `Send`-Fanout [SEC-AUDIT]

`guarded_complete` (src/llm/ledger.py) prüft Summe→Call→Insert nicht atomar;
6 parallele Personas können den Tages-Cap um bis zu ~6 Calls überschießen.
Zweite Ebene (LiteLLM-Key-Budgets) fängt das teilweise ab.

- **TODO:** Entweder `SELECT ... FOR UPDATE`/Advisory-Lock um Check+Insert oder
  bewusste Akzeptanz dokumentieren (ADR), da Überschuss ≤ 6 × Einzelcall-Kosten.

## P4 — Kein strukturiertes Logging, Scheduler-Fehler ohne Alert [SEC-AUDIT]

CLAUDE.md fordert JSON-Logging mit `cycle_id`/`portfolio_id`-Korrelation.
Ist-Zustand: `print()` in `_run_cycle_job` (src/orchestrator/scheduler.py);
ein fehlgeschlagener Zyklus erzeugt keinen Telegram-Alert und ist nur auf
stdout sichtbar.

- **TODO:** Logging-Grundgerüst (structlog o. ä.) + Telegram-Alert bei
  Zyklus-Fehlschlag (2×-Fail-Eskalation analog Container-Health).

## P5 — HITL-Timeout-Sweep fehlt (dokumentierter F022-Gap) [SEC-AUDIT]

Nie beantwortete HITL-Anfragen bleiben unbegrenzt `HITL_PENDING` (fail-closed,
kein Sicherheitsrisiko, aber Verfügbarkeits-Gap; F022 §1 Non-Scope).

- **TODO:** Periodischer Sweep (Scheduler-Job), der abgelaufene Pending-Decisions
  per Timeout-Regel (`decided_by="timeout"` → Reject) auflöst und den Interrupt
  mit "rejected" resumed.

## P6 — Dependency-Findings [SEC-AUDIT]

- `npm audit` (web/): Next.js bündelt ein verwundbares `postcss` < 8.5.10
  (moderate, GHSA-qx2v-qp2m-jg93). **TODO:** Next.js auf gepatchte Version heben,
  sobald verfügbar. **Kein** `npm audit fix --force` (würde auf next@9 downgraden).
- **TODO:** `pip-audit`/Dependabot für den Python-Stack in CI ergänzen.

## P7 — Härtung, geringe Priorität [SEC-AUDIT]

- **Postgres-Default-Passwort** `atlas` (docker-compose.yml): auf der UGREEN
  `POSTGRES_PASSWORD` in `.env` setzen + `ALTER ROLE` im laufenden Cluster.
- **Kosten-Semantik:** Caps sind in EUR definiert (5 €/Tag …), `cost_ledger`
  zählt USD; „trades today" (src/orchestrator/risk_inputs.py) zählt den UTC-Tag,
  nicht den ET-Handelstag. Entscheidung dokumentieren oder angleichen.
- **LiteLLM-Kosten-Header:** `float(response.headers.get(...))` in
  src/llm/client.py wirft bei defektem Header nach bereits bezahltem Call —
  defensiv parsen, Fehlwert als Incident loggen statt Ledger-Eintrag verlieren.
- **API bleibt auth-los** (F007-Design, Single-User-LAN): akzeptiert, solange
  Bindung an `ATLAS_BIND_IP` (Fix vom 2026-07-07) aktiv ist und kein
  Port-Forwarding auf 8000/3001 existiert.
