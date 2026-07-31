# F094 — OpenCode Zen als LLM-Route

**Status:** Staged — verdrahtet und verifiziert, kanonische Umschaltung offen
**Phase:** 5 (Härtung)
**Deployed:** 2026-07-31 (nur die nicht-kanonischen `-zen`-Routen)
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

### 3.1 Staging statt Umschaltung

Zen-Routen liegen unter eigenen Namen (`claude-sonnet-5-zen`,
`claude-haiku-4-5-zen`) neben den unveränderten Anthropic-Routen. `config/llm.yaml`
zeigt weiter auf `claude-sonnet-5` / `claude-haiku-4-5` → für ATLAS ändert sich
nichts. Umschalten = Namen tauschen.

Grund: Zens Workspace hat keine Zahlungsmethode. Eine kanonische Umschaltung würde
eine kaputte Route gegen eine andere kaputte tauschen.

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
| 7 | Echter Completion-Call | ❌ **`CreditsError: No payment method`** |
| 8 | `cost_usd` ≠ 0.0 im `cost_ledger` | ⏳ blockiert durch 7 |
| 9 | Prompt Caching wirksam | ⏳ blockiert durch 7 |
| 10 | Paper-Smoke-Test (ein Zyklus) | ⏳ blockiert durch 7 |

Nebenbefund: die Fehlermeldung aus Prüfung 7 war im Klartext lesbar — das ist der
F093-Fix (Response-Body an der Exception), der hier direkt seinen Zweck erfüllt hat.

## 5. Offene Schritte

1. **Ralf:** Zahlungsmethode im Zen-Workspace hinterlegen.
2. Prüfungen 8–10 nachziehen.
3. Namen in `config/litellm_proxy_config.yaml` tauschen, `docker compose restart
   litellm`.
4. ADR-0011 auf `accepted` setzen, Provider-Bruch im Wettbewerbsprotokoll vermerken.

## 6. Rollback

Namen zurücktauschen + `docker compose restart litellm` (~10 s). Die Datei ist
bind-gemountet, kein Image-Rebuild nötig. Die Anthropic-Direktrouten bleiben
dauerhaft konfiguriert und werden nicht entfernt — sie sind der Rückfallweg, falls
Zen (Cloudflare, Gateway-Ausfall) wegbricht.
