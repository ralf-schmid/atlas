# ADR-0011: OpenCode Zen als alternative LLM-Route (vorbereitet, nicht kanonisch)

* Status: proposed — technisch verdrahtet und verifiziert, Umschaltung blockiert
  durch fehlende Zahlungsmethode im Zen-Workspace
* Deciders: Ralf Schmid
* Datum: 2026-07-31
* Betrifft Invariante(n): **#6** (Secrets), **#7** (Kosten-Caps), **#10** (Fairness)
* Betrifft ARCHITECTURE.md **§3.3** (LLM-Routing)

## Kontext und Problemstellung

Seit 2026-07-30 06:00 UTC ist Ralfs Anthropic-Guthaben erschöpft. Jeder ATLAS-Zyklus
(Aktien + Krypto) scheitert am `persona_analysis`-LLM-Call, das System handelt nicht
(Befund und Diagnose-Fix: `docs/features/F093-transient-failure-hardening.md`).

Ralf möchte die LLM-Calls auf **OpenCode Zen** umstellen — ein Modell-Gateway, das
dieselben Anthropic-Modelle anbietet, die ATLAS heute nutzt. ARCHITECTURE.md §3.3
schreibt Anthropic als Provider fest; ein Provider-Wechsel ist damit
ADR-pflichtig.

## Betrachtete Optionen

1. **Anthropic-Guthaben aufladen** — kein Code, keine Änderung, sofort wirksam.
2. **OpenCode Zen als Route** — gleiche Modelle, laut Anbieter „pay per request with
   zero markups", eigener Guthabentopf.
3. **Groq-Slot hochziehen** — bereits konfiguriert (`claude-haiku-4-5-groq`), aber
   anderes Modell (Llama 3.3 70B). Würde den Wettbewerbsvergleich brechen
   (Invariante #10) und ist als Experiment-Slot für P7 reserviert. **Verworfen.**

Optionen 1 und 2 schließen sich nicht aus — Zen ist als zusätzliche Route gebaut,
nicht als Ersatz.

## Entscheidung

Zen-Routen werden **vorbereitet, aber nicht kanonisch geschaltet**: sie liegen in
`config/litellm_proxy_config.yaml` unter eigenen Namen (`claude-sonnet-5-zen`,
`claude-haiku-4-5-zen`). Die Rollen in `config/llm.yaml` zeigen unverändert auf
`claude-sonnet-5` / `claude-haiku-4-5`. Für ATLAS ändert sich damit nichts, bis die
Namen getauscht werden.

Begründung für das Staging: Zens Workspace hat keine Zahlungsmethode, jeder Call
endet in `CreditsError`. Eine kanonische Umschaltung würde eine kaputte Route gegen
eine andere kaputte Route tauschen und die Diagnose verschlechtern.

## Live verifizierte Fakten (31.07.2026)

| Frage | Ergebnis | Wie geprüft |
|---|---|---|
| Key gültig, Auth-Format | `x-api-key` (Anthropic-nativ), **kein** Bearer | Direkter Call gegen `/zen/v1/messages` |
| Modell-IDs | `claude-sonnet-5`, `claude-haiku-4-5` — **identisch** zu ATLAS' heutigen Namen | `GET /zen/v1/models` |
| Cloudflare-Bot-Schutz | `httpx` und `curl` kommen durch, Python-`urllib` bekommt 403/1010 | Aufruf aus dem `atlas-litellm-1`-Container |
| URL-Konstruktion | `api_base: …/zen` → LiteLLM hängt `/v1/messages` an | `litellm/main.py:2605`, Log-URL gegengeprüft |
| Ende-zu-Ende durch den Proxy | erreicht Zen, scheitert **nur** an `CreditsError` | Call über `atlas-scheduler-1` → Proxy → Zen |

Die Doku auf opencode.ai zeigt die Haiku-ID als `claude-haiku-4.5` (mit Punkt) — das
ist **falsch**, die API kennt nur `claude-haiku-4-5`. `GET /v1/models` ist die
verlässliche Quelle.

## Konsequenzen

### Positiv

* Modell-IDs identisch → **keine Änderung an `config/llm.yaml`**, kein Rebuild der
  App-Services. Umschalten ist ein Namenstausch + `docker compose restart litellm`
  (Bind-Mount, kein Image-Rebuild), Rollback ebenso, ~10 Sekunden.
* Prompt Caching (laut CLAUDE.md Pflicht) läuft nativ durch — LiteLLM reicht
  `cache_control` unverändert an den Anthropic-Spec-Endpunkt weiter.
* Zweite, unabhängige Bezugsquelle für dieselben Modelle.

### Negativ / Risiken

* **Kostenerfassung (Invariante #7, Ebene 2).** LiteLLM rechnet Kosten aus seiner
  eigenen Preistabelle, nicht aus Zens tatsächlicher Abrechnung. Ohne explizite
  Preise käme `x-litellm-response-cost` falsch oder leer zurück; `_parse_cost_header`
  fällt dann bewusst auf `0.0` zurück (Security-Audit P7) und `cost_ledger` würde
  still Nullen schreiben — die einzige aktive Kostenbremse (ADR-0010: Ebene 1 ist
  nicht scharf) wäre wirkungslos. **Gegenmaßnahme:** `model_info`-Preise explizit
  gesetzt. **Offen:** muss nach dem ersten echten Call gegen die Zen-Abrechnung
  verifiziert werden — Preise sind ein Stand vom 31.07.2026 und driften.
* **Fairness (Invariante #10).** Alle sechs Personas laufen über dieselbe Route, kein
  Persona bekommt einen Vorteil — die Invariante im engeren Sinn ist gewahrt. Der
  Vergleich über die 8 Wochen bekommt aber einen Provider-Bruch. Bei identischem
  Modell (Sonnet 5) ist das Risiko klein, aber nicht null: ein Gateway kann anders
  routen, andere Regionen oder Modell-Revisionen treffen. Kein `charter_version`-Bump
  nötig (die Charter ändert sich nicht), aber der Bruch gehört ins Wettbewerbsprotokoll.
* **Zusätzliche Abhängigkeit.** Zen sitzt hinter Cloudflare; ein Bot-Schutz-Update
  kann die Route ohne Vorwarnung schließen. Deshalb bleiben die Anthropic-Direktrouten
  konfiguriert.
* **Preisvergleich ist nicht belastbar.** Zen listet Sonnet 5 mit $2.00/$10.00 pro 1M.
  Ob das gegenüber Anthropic direkt günstiger ist, hängt vom Ablauf des
  Sonnet-5-Einführungspreises am 31.08.2026 ab (ADR-0008, +50 %). Vor dem Datum kein
  belastbarer Vorteil — der Wechsel ist heute eine Frage der Verfügbarkeit, nicht
  des Preises.

## Offene Punkte vor kanonischer Umschaltung

1. Zahlungsmethode im Zen-Workspace hinterlegen (nur Ralf).
2. Echter Call → prüfen, dass `cost_usd` ≠ 0.0 im `cost_ledger` landet.
3. Prüfen, dass Cache-Tokens gezählt werden (Prompt Caching wirksam).
4. Paper-Smoke-Test: ein vollständiger Zyklus über die Zen-Route.
5. Erst danach Namen tauschen, ADR-Status auf `accepted`.
