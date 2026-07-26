# F091 — LiteLLM-Proxy-Key-Budgets (Kosten-Cap Ebene 1)

**Status:** Schnitt (26.07.2026), Umsetzung ausstehend
**Phase:** 5 (Härtung, nicht startkritisch — Wettbewerb läuft seit F090)
**Abhängigkeiten:** [ADR-0008](../adr/0008-raise-daily-cost-cap-to-10-usd.md)
(Cap-Werte 10/240), F019 (Ebene-2-Enforcement, `src/llm/ledger.py`).
Berührt Invariante **#7** (Kosten-Caps doppelt durchgesetzt) und **#6**
(Secrets nur via Environment/Docker Secrets).

## 1. Zieldefinition

Invariante #7 verlangt Kosten-Caps **doppelt durchgesetzt**: „LiteLLM-Budgets
(je Key) **und** Orchestrator-Zähler auf `cost_ledger`". Aktuell existiert nur
Ebene 2 (Orchestrator-Zähler, `guarded_complete`). Ebene 1 (proxy-seitige
Budgets) ist nie gebaut worden — der LiteLLM-Proxy läuft mit einem einzigen
Master-Key ohne DB-Backend, kann also keine Budgets halten. F091 baut Ebene 1:
ein **unabhängiger** proxy-seitiger Hard-Stop, der greift, selbst wenn der
Orchestrator-Zähler umgangen wird oder fehlerhaft ist (Defense-in-Depth).

## 2. Kontext / Ist-Zustand

- **Proxy:** `config/litellm_proxy_config.yaml` hat nur `model_list` +
  `general_settings.master_key`. Der `litellm`-Service (`docker-compose.yml`) hat
  **kein `DATABASE_URL`** → keine virtuellen Keys, keine Budgets (LiteLLM braucht
  ein Postgres-Backend/Prisma für Key-Management, siehe docs.litellm.ai/docs/proxy/virtual_keys).
- **Client:** `LiteLLMClient` (`src/llm/client.py`) trägt **einen** `api_key`
  und setzt ihn als `Authorization: Bearer` — überall der `LITELLM_MASTER_KEY`
  (4 Instanziierungsstellen: `run_scheduler`/`run_cycle`/`resume_cycle`/
  `run_telegram_bot`). Kein Code erzeugt/wählt Rollen-Keys.
- **Rolle & Persona sind am Call-Zeitpunkt bekannt:** `guarded_complete`
  (`src/llm/ledger.py`) bekommt `role: RoleConfig` (mit `shared`-Flag) + optional
  `persona_id`. Die Rollen (`config/llm.yaml`): `market_research`, `news_research`,
  `review` = **shared** (persona-übergreifend); `persona_analysis`, `trading` =
  **nicht shared** (je Persona). Das ist exakt die Granularität, die Ebene-1-Keys
  brauchen — die Verdrahtung kann dieselbe Rolle/Persona-Info nutzen.
- **Kostenzuordnung macht Ebene 2 bereits** (`cost_ledger.scope` SYSTEM/PERSONA +
  `persona_id`). Ebene 1 dupliziert die Zuordnung nicht — ihr einziger Zweck ist
  der unabhängige Hard-Stop.
- **Caps (ADR-0008):** System 10 USD/Tag, je Persona 1 USD/Tag, Monat 240 USD
  (Soft-Cap). UTC-Kalendertag-Grenze in Ebene 2 (`_day_bounds`).

## 3. Design-Entscheidung (Empfehlung, im Detail bei Umsetzung zu verifizieren)

**A. DB-Backend für den Proxy.** `DATABASE_URL` an den `litellm`-Service; die
bestehende `atlas-postgres-1` mit **eigener Datenbank `litellm`** nutzen (LiteLLM
legt seine `LiteLLM_*`-Tabellen via Prisma selbst an — von unserem Alembic-Schema
getrennt halten). Infra-Änderung → `docker-compose.yml` **und** die uGreen-Box-Doku
(`TRUENAS_HOMELAB.md`, Stack `atlas`) nachziehen (CLAUDE.md-Regel).

**B. Budgets über LiteLLM-Teams, nicht rohe Per-Key-Beträge.** Die Ebene-2-Caps
sind zwei Töpfe (System-Gesamt + je Persona); Ebene 1 spiegelt sie:
- ein **globales** Proxy-Budget (`general_settings`/Master) = **10 USD/Tag**
  (System-Backstop, deckt alle Calls);
- ein **Team je Persona** mit `max_budget = 1 USD/Tag` — die nicht-shared Keys
  dieser Persona (`persona_analysis`, `trading`) hängen an diesem Team und teilen
  sich den Topf (sonst hätte eine Persona faktisch 2 USD/Tag über zwei Keys).
- shared-Rollen-Keys (`market_research`/`news_research`/`review`) laufen nur gegen
  das globale System-Budget (kein Persona-Team), da ihr Verbrauch systemweit zählt.

**C. Virtuelle Keys je Rolle×Persona (nicht-shared) bzw. je Rolle (shared)** —
~15 Keys (`persona_analysis`×6, `trading`×6, +3 shared). „Je Key" ist die
wörtliche Invarianten-Formulierung und gibt harte Isolation + Kostenzuordnung.
Erzeugt durch ein **Provisioning-Skript** (`scripts/provision_litellm_keys.py`)
über die Proxy-Admin-API (`/team/new`, `/key/generate` mit `max_budget`,
`budget_duration`), idempotent über deterministische `key_alias`
(`{role}` bzw. `{role}:{persona}`).

**D. Client-Verdrahtung hinter Config-Flag.** `LiteLLMClient` wählt den Key nach
(Rolle, Persona) statt fix Master. Key-Werte sind Secrets (Invariante #6) → als
Environment/Docker-Secrets in die Box-`.env`, gelesen über eine Registry
(`config/llm.yaml`-Rollen × Persona → env-Var-Name). Ein Flag
(`llm.yaml: proxy_key_budgets_enabled`) schaltet zwischen Master-Key (heutiges
Verhalten, Fallback) und Rollen-Keys — so ist der Rollback ein Config-Flip.

## 4. Scope

- `docker-compose.yml`: `DATABASE_URL` + ggf. `STORE_MODEL_IN_DB`/Prisma-Flags am
  `litellm`-Service; neue DB `litellm` (Init in `postgres`-Container).
- `config/litellm_proxy_config.yaml`: `general_settings` für DB + globales Budget.
- `scripts/provision_litellm_keys.py`: idempotentes Anlegen der Teams + Keys.
- `src/llm/client.py` / eine kleine Key-Registry: (Rolle, Persona) → Key, hinter
  dem `proxy_key_budgets_enabled`-Flag; Fallback Master-Key.
- `config/llm.yaml`: Flag + Budget-Referenzwerte (Single Source mit Ebene 2).
- Tests (§5).

**Non-Scope:** keine Änderung an Ebene 2 (`ledger.py`/`cost_guard.py` bleiben wie
sind — beide Ebenen laufen unabhängig). Keine neuen Rollen/Personas. Kein
LLM-Anteil. Keine Änderung der Cap-Werte (die stehen, ADR-0008).

## 5. Testdefinition (VOR Umsetzung)

Der Proxy ist ein externer Dienst → Zweiteilung wie beim Alpaca-Adapter
(Unit gegen Mock, ein `integration`-Test gegen den echten Proxy):

1. **Key-Registry-Auswahl (Unit):** `(role=persona_analysis, persona=VULTURE)` →
   der VULTURE-persona_analysis-Key; shared Rolle → der Rollen-Key; unbekannte
   Kombination → klarer Fehler.
2. **Flag aus → Master-Key (Unit):** bei `proxy_key_budgets_enabled=false`
   nutzt der Client unverändert den Master-Key (Fallback-/Rollback-Pfad).
3. **Provisioning idempotent (Unit gegen Mock-Admin-API):** zweiter Lauf legt
   keine Duplikate an (deterministische `key_alias`), Budgets/Team-Zuordnung
   stimmen mit `config/llm.yaml` überein.
4. **Budget-Durchsetzung am echten Proxy (`integration`, opt-in):** ein Key mit
   winzigem `max_budget` → nach Überschreitung antwortet der Proxy mit dem
   LiteLLM-Budget-Fehler (nicht 200). Belegt, dass Ebene 1 unabhängig von Ebene 2
   stoppt.
5. **Zwei-Ebenen-Konsistenz:** Persona-Team-Budget (1 USD) und Ebene-2-Persona-Cap
   (1 USD) referenzieren denselben Wert aus `config/llm.yaml` (kein Drift).
6. **Reset-Grenze:** `budget_duration` des Proxys vs. Ebene-2-UTC-Kalendertag —
   Test/Spike, dass beide dieselbe Tagesgrenze meinen (LiteLLM `budget_duration`
   resettet rollierend ab Erstellung, nicht kalendarisch → **offener Punkt**, ggf.
   `budget_reset_at`/tägliches Re-Provisioning nötig).

## 6. Kritische Betrachtung

- **Invariante #7:** danach erstmals wirklich doppelt durchgesetzt — Ebene 1 stoppt
  proxy-seitig auch, wenn ein Bug Ebene 2 umgeht.
- **Invariante #6 (Secrets):** die ~15 Key-Werte sind Secrets → nur via
  Environment/Docker-Secrets, nie im Repo; gitleaks bleibt scharf. Der Provisioning-
  Output (Key-Werte) darf nie in Logs.
- **Fairness (#10):** Per-Persona-Teams mit identischem 1-USD-Budget → kein
  Kostenvorteil einer Persona; shared-Rollen bleiben systemweit.
- **Regressionsrisiko:** die Verdrahtung sitzt im Geld-/LLM-Pfad. Deshalb Config-Flag
  mit Master-Key-Fallback — bei Problemen sofort zurückschaltbar, ohne Redeploy der
  Logik (nur Flag + Restart).
- **Kosten:** 0 LLM; minimaler DB-Overhead im Proxy.
- **Betrieb:** ein weiterer zustandsbehafteter Teil (Proxy-DB). Backup/Recreate der
  `litellm`-DB bedenken (Keys neu provisionierbar via Skript → kein harter
  Datenverlust, nur Re-Provisioning).

## 7. Rollback-Pfad

Config-Flag `proxy_key_budgets_enabled=false` → Client nutzt wieder den Master-Key,
Ebene 2 allein aktiv (heutiger, funktionierender Zustand). Der Proxy-DB-Teil bleibt
liegen (schadet nicht). Vollständiger Rückbau: `DATABASE_URL` am `litellm`-Service
entfernen + Flag aus. Kein DB-Migrationsrisiko auf unserer Seite (LiteLLM verwaltet
sein Schema getrennt).

## 8. Offene Punkte (Ralf / bei Umsetzung)

1. **`budget_duration`-Semantik** (rollierend vs. UTC-Kalendertag) — kurzer Spike
   am echten Proxy, bevor die Key-Budgets scharf gehen; ggf. tägliches
   Re-Provisioning oder `budget_reset_at`.
2. **Key-Storage:** ~15 Werte als einzelne `.env`-Vars vs. eine gemountete
   Secret-Datei (Docker Secret). Entscheidung mit Ralf (Ops-Präferenz).
3. **Priorität/Timing:** Härtung, nicht startkritisch — kann nach dem
   Wettbewerbsstart in Ruhe gebaut werden (Ebene 2 kontrolliert die Kosten bereits).
4. **Provisioning-Auslösung:** manuell (wie `reset_competition`) oder als
   Deploy-Schritt — plus Umgang mit der Master-Key-Rotation, falls nötig.
