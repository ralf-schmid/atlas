# F006 — LiteLLM-Client + Kosten-Guard (Orchestrator-Bremse)

Status: in Umsetzung
Datum: 2026-07-05
Phase: 2

## 1. Zieldefinition

`config/llm.yaml` (Routing: welche Agent-Rolle nutzt welches Modell/welchen Provider,
Budgets) + `src/llm/client.py` (dünner Client gegen den LiteLLM-Proxy, OpenAI-kompatibel,
liest Token-/Kosten-Infos aus der Response) + `src/llm/cost_guard.py` (die
**Orchestrator-seitige** Bremse aus §6.3 — unabhängig von LiteLLMs eigenem
Budget-Enforcement, "zwei unabhängige Bremsen"). Plus `litellm`-Service in
`docker-compose.yml`.

**Nicht Teil dieses Features:** ein echter End-to-End-Test mit den tatsächlichen
Anthropic-/Groq-API-Keys (DoD-Punkt "LiteLLM läuft mit 2 Providern... ein Budget-Limit
testweise gerissen") — dafür fehlen mir reale Provider-Keys, das ist Ralfs Aktion (siehe
`docs/dod/phase-2.md`). Auch nicht Teil: die eigentlichen Agenten, die den Client aufrufen
(existieren noch nicht).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #7 Kosten-Caps doppelt durchgesetzt | ja | `cost_guard.py` ist die Orchestrator-Bremse (liest `cost_ledger`-Tagessumme), unabhängig vom LiteLLM-eigenen Budget (das hier nur als Config vorgesehen, nicht selbst Code ist — LiteLLM ist ein separater Proxy-Prozess). Zwei unabhängige Mechanismen, wie gefordert. |
| Prompt Caching Pflicht (§3.3) | ja | `config/llm.yaml` markiert `prompt_caching: true` je Rolle — Durchsetzung selbst ist LiteLLM-/Anthropic-seitig (Cache-Control-Header), hier nur konfiguriert, nicht im Python-Code erzwungen. |
| Keine lokalen LLMs im Trading-Pfad | ja | `config/llm.yaml` referenziert ausschließlich Anthropic/Groq-Modelle für Agent-Rollen; kein `ollama`/lokaler Provider-Eintrag. |
| 100%-Cap: bereits platzierte Orders/Stops bleiben unberührt | ja | `cost_guard` blockiert nur **neue LLM-Aufrufe** (`check_system_budget`/`check_persona_budget` geben `blocked=True` zurück) — hat keinerlei Verbindung zum Broker-Layer, kann also strukturell keine Order/Stop stornieren. |
| Fairness | ja | Gleicher Client-Code für alle Personas; Budgets pro Rolle × Persona sind Config, nicht Code. |

**Design-Entscheidungen:**
- **Kostenquelle:** LiteLLM-Proxy liefert die Kosten pro Request im Response-Header
  `x-litellm-response-cost` (LiteLLM-Doku) — `client.py` liest diesen Header, rechnet nicht
  selbst Preise pro Modell/Token aus (das wäre Preistabellen-Pflege im eigenen Code,
  fehleranfällig und dupliziert LiteLLMs eigene Preisdaten).
- **Caps aus CLAUDE.md §Entscheidungsstand 1:** 5 €/Tag System, 1 €/Tag/Persona,
  120 €/Monat Soft-Cap (Warnung ab 80 %). Als Parameter-Defaults in `cost_guard.py`,
  nicht hart codiert ohne Konfigurierbarkeit.

**Kosten:** Diese Client-Schicht selbst verursacht keine Kosten (reines HTTP-Wrapper +
reine Kosten-Grenzwert-Funktionen). **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/llm/`), LiteLLM-HTTP-Aufruf gemockt, keine Netzwerkzugriffe:

1. `client.complete()` sendet die erwartete OpenAI-kompatible Chat-Completion-Anfrage
   (Model, Messages) an den konfigurierten LiteLLM-Base-URL.
2. `client.complete()` extrahiert `tokens_in`/`tokens_out` aus der Response und `cost_usd`
   aus dem `x-litellm-response-cost`-Header.
3. `check_system_budget`: unter 80 % → `ok`; zwischen 80–100 % → `warn`; ≥ 100 % → `blocked`.
4. `check_persona_budget`: dieselbe Drei-Stufen-Logik, eigener Cap (1 €).
5. `check_monthly_soft_cap`: unter 80 % → `ok`; ab 80 % → `warn` (kein `blocked`, ist
   Soft-Cap laut Spec).
6. Grenzfälle exakt an den Schwellen (80,0 %, 100,0 %) → korrekt eingeordnet (nicht
   "eine Seite zu früh/spät").
7. Config-Loading: `config/llm.yaml` lädt ohne Fehler, enthält alle in §5.1 genannten
   Agent-Rollen.

## 4. Implementierung

`src/llm/client.py`, `src/llm/cost_guard.py`, `src/llm/config.py`, `config/llm.yaml`,
`docker-compose.yml` (litellm-Service).

## 5. Testdurchlauf

`uv run pytest tests/llm/ --cov=src/llm --cov-branch` → 15/15 grün, **100% Line- und
Branch-Coverage**. `uv run ruff check` und `uv run mypy src/llm` → beide sauber.

`docker-compose.yml` um einen `litellm`-Service ergänzt (`ghcr.io/berriai/litellm`,
`config/litellm_proxy_config.yaml` gemountet, Health-Check auf `/health/liveliness`).
`.env.example` um `ANTHROPIC_API_KEY`/`GROQ_API_KEY`/`LITELLM_MASTER_KEY`
(Dummy-Werte) ergänzt.

Nicht ausgeführt: `docker compose up litellm` selbst (Docker auf dieser Maschine defekt,
siehe frühere Session) und der echte Budget-Test mit realen Provider-Keys — beides Ralfs
Aktion, siehe `docs/dod/phase-2.md`.

## 6. Rollback-Pfad

Additives Feature, keine Seiteneffekte (kein Agent ruft das bisher auf). Rollback =
Commit zurücknehmen.
