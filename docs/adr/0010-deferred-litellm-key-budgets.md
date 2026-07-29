# ADR-0010: Akzeptiertes Risiko — LiteLLM-Proxy-Key-Budgets (Ebene 1) nicht aktiv

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-29
* Betrifft Invariante(n): **#7** (Kosten-Caps doppelt durchgesetzt)

## Kontext und Problemstellung

Invariante #7 fordert Kosten-Caps **doppelt durchgesetzt**: Ebene 1 (LiteLLM-Proxy-Budgets)
**und** Ebene 2 (Orchestrator-Zähler auf `cost_ledger`). F091
(`docs/features/F091-litellm-proxy-key-budgets.md`) spezifiziert Ebene 1, wurde aber nie
implementiert — Stand "Schnitt" seit 26.07.2026.

Aktiv ist nur Ebene 2: `LiteLLMClient.guarded_complete` (`src/llm/ledger.py`) schreibt
vor jedem LLM-Call in `cost_ledger` und stoppt bei 80 % Warnung / 100 % Hart-Stopp.
Dieser Mechanismus läuft im selben Prozess wie die Agents und teilt denselven Code-Pfad.

**Akzeptiertes Risiko:** Ein Bug in `guarded_complete` (falscher Scope, vergessener Call,
Logikfehler in `_day_bounds`) oder eine Code-Änderung, die den Guard umgeht, hebelt die
einzige Kostengrenze aus — kein unabhängiger Hard-Stop greift. Der Wettbewerb könnte
ungedrosselt LLM-Kosten produzieren, bis das Monatsbudget überschritten ist oder der
Betreiber eingreift.

## Entscheidungstreiber

1. **Phase-4-Liefertermin:** F091 ist Phase 5 (Härtung), nicht startkritisch — der
   Wettbewerb läuft seit F090 (07.07.2026) mit Ebene 2 allein ohne Kostenunfall.
2. **Ebene 2 ist getestet:** Kein Fehler in `guarded_complete` seit Inbetriebnahme;
   tägliche LLM-Kosten stabil unter 1 USD/Persona.
3. **Implementierungsaufwand:** F091 erfordert ~15 virtuelle Keys, eine Key-Registry im
   Client, Config-Flag, und den `budget_duration`-Spike (rollierend vs. kalendarisch) —
   kein trivialer Aufwand für ein reines Defense-in-Depth.
4. **Betriebsrisiko der Umsetzung:** Die Client-Verdrahtung sitzt im Geldpfad. Ein
   Fehler bei der Key-Auswahl (falscher Key → falscher Kosten-Topf, falsches Budget)
   wäre kritischer als der fehlende zweite Layer.
5. **Rollback-Komplexität:** F091 hat einen sauberen Rollback (Config-Flag), aber der
   Zustand der Proxy-DB müsste bei Rückbau ebenfalls bereinigt werden.

## Betrachtete Optionen

* **A: Sofort umsetzen (Phase-4-Verzug)** — F091 vor Wettbewerbsstart implementieren.
* **B: Akzeptieren und in Phase 5 umsetzen** — Invariante #7 bleibt formal verletzt,
  aber dokumentiert. Umsetzung als Härtungs-Schritt nach dem Wettbewerbsstart.
* **C: Ganz streichen** — Invariante #7 auf "einfach" zurückstufen und Abhängigkeit von
  Ebene 2 allein akzeptieren.

## Entscheidung

Gewählt: **B**, weil der Wettbewerb seit einem Monat stabil mit Ebene 2 allein läuft,
die offenen Implementierungsfragen (`budget_duration`, Key-Storage-Design) Zeit brauchen,
und ein Umsetzungsfehler im Geldpfad riskanter wäre als der fehlende zweite Layer.

Invariante #7 gilt als **formal verletzt** bis zur Umsetzung in Phase 5.

### Konsequenzen

* Gut, weil Phase 4 termingerecht abgeschlossen werden kann.
* Gut, weil Ebene 2 in Produktion seit Wochen stabil ist — das Risiko ist abstrakt
  (Bug in `guarded_complete`), nicht akut.
* **Schlecht, weil Defense-in-Depth fehlt:** ein einzelner Bug oder eine vergessene
  `guarded_complete`-Umstellung kann das gesamte Monatsbudget überschießen.
* **Schlecht, weil Invariante #7 formal verletzt ist** — bei Audit fällt das auf.

## Pro/Contra der Optionen

### A: Sofort umsetzen

* Gut, weil Invariante #7 erfüllt wäre.
* Schlecht, weil mindestens 2-3 Tage Entwicklungszeit + Integrationstest + Deployment
  — und der Wettbewerb läuft bereits.
* Schlecht, weil das `budget_duration`-Problem (rollierend vs. kalendarisch) einen Spike
  erfordert, dessen Ergebnis offen ist (u.U. tägliches Re-Provisioning = weiterer
  Betriebsaufwand).

### B: Akzeptieren, später umsetzen (gewählt)

* Gut, weil keine Verzögerung und kein Regressionsrisiko im Geldpfad.
* Gut, weil F091 in Ruhe durchdacht und getestet werden kann.
* Schlecht, weil Invariante #7 verletzt bleibt.

### C: Ganz streichen

* Gut, weil kein Aufwand.
* Schlecht, weil Invariante #7 dauerhaft aufgegeben würde und das System kein
  Defense-in-Depth bei Kosten hätte.

## Wie beheben (Fix-Pfad)

Die Umsetzung von F091 erfolgt nach F094/Phase-5-Abschluss. Arbeitspakete:

1. **`docker-compose.yml`:** `DATABASE_URL=postgresql://atlas:${ATLAS_DB_PASSWORD}@postgres:5432/litellm`
   an den `litellm`-Service. DB `litellm` existiert bereits (heute angelegt).
2. **`config/litellm_proxy_config.yaml`:** `general_settings` um `database_url` und
   `max_budget` (globales Proxy-Budget 10 USD/Tag) ergänzen.
3. **`scripts/provision_litellm_keys.py`:** Idempotentes Anlegen von 6 Teams (1 je
   Persona, je 1 USD/Tag) + ~15 virtuellen Keys (pro Rolle×Persona bzw. shared) über
   die Proxy-Admin-API (`/team/new`, `/key/generate`). Key-Werte in `.env` persistieren.
4. **`src/llm/client.py`:** Key-Registry: `(role, persona_id) → api_key` hinter
   Config-Flag `proxy_key_budgets_enabled`; bei `false` Fallback auf Master-Key.
5. **`config/llm.yaml`:** Flag + Budget-Referenzwerte als Single Source (muss mit
   `ledger.py`-Cap konsistent sein).
6. **Tests:** Unit-Tests für Key-Registry + Flag-Verhalten; Integrationstest gegen
   echten Proxy mit Mini-Budget (Budget-Durchsetzung verifizieren).
7. **`budget_duration`-Spike:** Prüfen, ob LiteLLM `budget_duration` rollierend oder
   kalendarisch resettet — ggf. tägliches Re-Provisioning per Cron-Job im Scheduler.

Der gesamte Fix ist über das Config-Flag rücksetzbar (Rollback-Pfad F091 §7).
