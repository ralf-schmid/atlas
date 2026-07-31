# F094 — OpenCode Zen als LLM-Route

**Status:** Implemented — kanonisch geschaltet
**Phase:** 5 (Härtung)
**Deployed:** 2026-07-31
**Abhängigkeiten:** `config/litellm_proxy_config.yaml`, `docker-compose.yml`,
`.env.example`
**ADR:** [ADR-0011](../adr/0011-opencode-zen-as-llm-route.md)
Berührt Invarianten **#6** (Secrets), **#7** (Kosten-Caps), **#10** (Fairness).

## 1. Zieldefinition

ATLAS soll seine LLM-Calls über OpenCode Zen beziehen können statt ausschließlich
direkt über Anthropic — ausgelöst durch das seit 30.07.2026 erschöpfte
Anthropic-Guthaben, das den kompletten Wettbewerb angehalten hat.

Randbedingung: **kein Eingriff in Anwendungscode.** Die Rollen-Konfiguration
(`config/llm.yaml`) und `src/llm/` bleiben unberührt; der Wechsel findet
ausschließlich im Proxy-Routing statt.

## 2. Kritische Betrachtung (vor Umsetzung)

- **Invariante #7:** LiteLLM leitet Kosten aus seiner Preistabelle ab, nicht aus
  Zens Abrechnung. Ohne Gegenmaßnahme schreibt `cost_ledger` Nullen (siehe
  `_parse_cost_header`, bewusster `0.0`-Fallback) und Ebene 2 der Kostenbremse —
  laut ADR-0010 die *einzige* aktive Ebene — wäre wirkungslos.
  → `model_info`-Preise explizit gesetzt.
- **Invariante #10:** alle Personas teilen dieselbe Route, kein Vorteil für eine
  einzelne. Der Provider-Bruch mitten im 8-Wochen-Vergleich ist trotzdem
  dokumentationspflichtig → ADR-0011.
- **Invariante #6:** Key ausschließlich als Env-Var, Dummy in `.env.example`,
  nie im Repo. `.env` wird nie synct.
- **Prompt Caching** ist laut CLAUDE.md Pflicht — musste vor Umsetzung geklärt
  sein, nicht danach.

## 3. Design

### 3.1 Umschaltung über Namen, mit erhaltener Rückfallroute

Die kanonischen Namen (`claude-sonnet-5`, `claude-haiku-4-5`), auf die
`config/llm.yaml` zeigt, routen auf Zen. Die Anthropic-Direktrouten bleiben unter
`-anthropic` konfiguriert — Rollback ist ein Namenstausch plus Proxy-Restart.

Zwischenschritt: bis die Zahlungsmethode hinterlegt war, liefen die Zen-Routen unter
eigenen `-zen`-Namen. Das hat die gesamte Verifikation getragen, ohne den laufenden
Betrieb anzufassen.

### 3.2 Routing-Details (am installierten LiteLLM verifiziert, nicht aus der Doku)

| Punkt | Wert | Begründung |
|---|---|---|
| `api_base` | `https://opencode.ai/zen` — **ohne** `/v1` | LiteLLM hängt `/v1/messages` selbst an (`litellm/main.py:2605`); mit `/v1` würde `/v1/v1/messages` daraus |
| Auth | `x-api-key` (Default) | Live gegen den Endpunkt geprüft. Für Bearer gäbe es `use_bearer_for_custom_base: true` — nicht nötig |
| Modell-IDs | `claude-sonnet-5`, `claude-haiku-4-5` | Aus `GET /zen/v1/models`. Die Web-Doku zeigt `claude-haiku-4.5` mit Punkt — **falsch**, die API lehnt das ab |
| Preise | explizit in `model_info` | siehe §2 |

### 3.3 Env-Var

`OPENCODE_API_KEY` (Ralfs Benennung übernommen). Muss an **zwei** Stellen stehen:
`.env` auf der Box **und** im `environment:`-Block des `litellm`-Service in
`docker-compose.yml` — Compose reicht nur explizit gelistete Vars durch.
Default `${OPENCODE_API_KEY:-}`, damit ein leerer Wert den Proxy nicht bricht,
solange die Zen-Routen nicht kanonisch sind.

## 4. Verifikation (31.07.2026, live)

| # | Prüfung | Ergebnis |
|---|---|---|
| 1 | Key gültig, Auth-Format | ✅ `x-api-key` |
| 2 | Modell-IDs | ✅ aus `/v1/models`, identisch zu ATLAS' Namen |
| 3 | Cloudflare-Bot-Schutz vs. `httpx` | ✅ durchgekommen (`urllib` wird mit 403/1010 geblockt, `httpx`/`curl` nicht) — aus dem `atlas-litellm-1`-Container geprüft, also mit genau dem Client, der es später tut |
| 4 | URL-Konstruktion | ✅ `https://opencode.ai/zen/v1/messages`, kein doppeltes `/v1` |
| 5 | Ende-zu-Ende Scheduler → Proxy → Zen | ✅ erreicht Zen |
| 6 | Bestehende Routen unbeschädigt | ✅ `/models` listet alle 5 Einträge, Proxy `healthy`, keine Config-Fehler |
| 7 | Echter Completion-Call | ✅ beide Modelle HTTP 200 |
| 8 | Kostenerfassung exakt | ✅ Haiku 14 in/4 out → `3.4e-05`, Sonnet 15/4 → `7e-05` — cent-genau die `model_info`-Preise |
| 9 | Prompt Caching wirksam | ✅ Lauf 1 `cache_write=7484` / $0.018776, Lauf 2 `cache_read=7484` / $0.0015628 (12× günstiger) — LiteLLM wendet die 1,25×/0,1×-Multiplikatoren korrekt an |
| 10 | Paper-Smoke-Test (ein Zyklus) | ✅ siehe §4.1 |

### 4.1 Paper-Smoke-Test (`scripts/run_cycle.py`, 31.07.2026)

Ein vollständiger Zyklus über die Zen-Route, 0 Tracebacks:

```
   name   |      agent       |  status   |  usd
----------+------------------+-----------+--------
 CHARTIST | persona_analysis | SUCCEEDED | 0.0490
 CONTRA   | persona_analysis | SUCCEEDED | 0.0483
 CRYPTOR  | persona_analysis | SUCCEEDED | 0.0461
 GUARDIAN | persona_analysis | SUCCEEDED | 0.0531
 HYPE     | persona_analysis | SUCCEEDED | 0.0671
 VULTURE  | persona_analysis | SUCCEEDED | 0.0676

   name   |   action    |  status  | instrument | research_refs
----------+-------------+----------+------------+---------------
 CHARTIST | REJECT_IDEA | RECORDED | AAPL       |             1
 CONTRA   | REJECT_IDEA | RECORDED | AAOI       |             1
 CRYPTOR  | HOLD        | RECORDED | PORTFOLIO  |             4
 GUARDIAN | HOLD        | RECORDED | PORTFOLIO  |             3
 HYPE     | REJECT_IDEA | RECORDED | AAPL       |             3
 VULTURE  | HOLD        | RECORDED | PORTFOLIO  |             4
```

Alle sechs Personas erfolgreich, jede Decision mit `input_research_ids`
(Invariante #3). **Einschränkung:** keine Persona hat BUY/SELL entschieden, also
0 Orders — der Order-Pfad (Risk-Gate → Broker → Stop-Loss) wurde von diesem Zyklus
**nicht** durchlaufen. Das ist ein legitimes Zyklus-Ergebnis, aber kein Nachweis für
den Order-Pfad über die neue Route; der kommt erst mit dem ersten echten Trade.

Nebenbefund: die `CreditsError`-Meldung aus der Vor-Verifikation war im Klartext
lesbar — das ist der F093-Fix (Response-Body an der Exception), der hier direkt
seinen Zweck erfüllt hat.

## 5. Offene Punkte (nicht Teil dieses Features)

1. **`cost_ledger.provider` sagt weiterhin `anthropic`.** Das Feld kommt aus
   `config/llm.yaml` und beschreibt die Modellfamilie — die Modelle *sind*
   Anthropic-Modelle, aber das Geld fließt jetzt an OpenCode. Für ein System, dessen
   Zweck Nachvollziehbarkeit ist, ist das eine Ungenauigkeit in der Buchführung.
   Korrektur wäre ein Config-Feld plus Image-Rebuild (config ist gebacken) und
   berührt die Kostenzuordnung — bewusst nicht nebenbei erledigt.
2. **Prompt Caching wird nicht gesendet.** `prompt_caching: true` in
   `config/llm.yaml` wird nirgends im Code ausgewertet (F006 §Tabelle sagt das
   selbst). Zen *kann* es (Prüfung 9), ATLAS nutzt es nicht — auf keinem Provider,
   auch vorher nicht. Vorbestehende Lücke gegenüber CLAUDE.md, eigenes Feature.
3. **Order-Pfad über die neue Route ungeprüft** (siehe §4.1).
4. **Provider-Bruch ins Wettbewerbsprotokoll** eintragen.
5. **`model_info`-Preise bei Zen-Preisänderungen nachziehen**, sonst driftet
   `cost_ledger` lautlos.
6. **`docker-compose.yml` geändert** → `TRUENAS_HOMELAB.md` im `ugreen-Box`-Repo
   nachziehen (CLAUDE.md).

## 6. Rollback

Namen zurücktauschen + `docker compose restart litellm` (~10 s). Die Datei ist
bind-gemountet, kein Image-Rebuild nötig. Die Anthropic-Direktrouten bleiben
dauerhaft konfiguriert und werden nicht entfernt — sie sind der Rückfallweg, falls
Zen (Cloudflare, Gateway-Ausfall) wegbricht.
