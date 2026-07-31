# ADR-0011: OpenCode Zen als LLM-Route statt Anthropic direkt

* Status: accepted — kanonisch geschaltet am 31.07.2026
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

**Option 2.** Die kanonischen Modellnamen (`claude-sonnet-5`, `claude-haiku-4-5`),
auf die `config/llm.yaml` zeigt, routen seit dem 31.07.2026 auf OpenCode Zen. Die
Anthropic-Direktrouten bleiben unter `-anthropic`-Namen dauerhaft konfiguriert; ein
Rückfall ist ein Namenstausch plus Proxy-Restart, keine Recherche.

Zwischenschritt (dokumentiert, weil er die Verifikation getragen hat): die
Zen-Routen liefen zunächst unter eigenen `-zen`-Namen, solange Zens Workspace keine
Zahlungsmethode hatte. Eine sofortige Umschaltung hätte damals nur eine kaputte
Route gegen eine andere getauscht.

## Live verifizierte Fakten (31.07.2026)

| Frage | Ergebnis | Wie geprüft |
|---|---|---|
| Key gültig, Auth-Format | `x-api-key` (Anthropic-nativ), **kein** Bearer | Direkter Call gegen `/zen/v1/messages` |
| Modell-IDs | `claude-sonnet-5`, `claude-haiku-4-5` — **identisch** zu ATLAS' heutigen Namen | `GET /zen/v1/models` |
| Cloudflare-Bot-Schutz | `httpx` und `curl` kommen durch, Python-`urllib` bekommt 403/1010 | Aufruf aus dem `atlas-litellm-1`-Container |
| URL-Konstruktion | `api_base: …/zen` → LiteLLM hängt `/v1/messages` an | `litellm/main.py:2605`, Log-URL gegengeprüft |
| Ende-zu-Ende durch den Proxy | funktioniert | Call über `atlas-scheduler-1` → Proxy → Zen |
| Kostenerfassung | `x-litellm-response-cost` gesetzt und **auf den Cent korrekt** | Haiku 14 in/4 out → `3.4e-05`; Sonnet 15/4 → `7e-05` — exakt die `model_info`-Preise |
| Prompt Caching | funktioniert, inkl. korrekter Cache-Multiplikatoren | 2 Läufe mit `cache_control`: Lauf 1 `cache_write=7484` / $0.018776, Lauf 2 `cache_read=7484` / $0.0015628 (12× günstiger) |

Die Doku auf opencode.ai zeigt die Haiku-ID als `claude-haiku-4.5` (mit Punkt) — das
ist **falsch**, die API kennt nur `claude-haiku-4-5`. `GET /v1/models` ist die
verlässliche Quelle.

## Konsequenzen

### Positiv

* Modell-IDs identisch → **keine Änderung an `config/llm.yaml`**, kein Rebuild der
  App-Services. Umschalten ist ein Namenstausch + `docker compose restart litellm`
  (Bind-Mount, kein Image-Rebuild), Rollback ebenso, ~10 Sekunden.
* Prompt Caching läuft nativ durch — LiteLLM reicht `cache_control` unverändert an
  den Anthropic-Spec-Endpunkt weiter, Zen bucht Write/Read korrekt ab. **Achtung:**
  ATLAS *sendet* heute gar kein `cache_control` — `prompt_caching` in
  `config/llm.yaml` ist ein Flag ohne Auswirkung (F006 sagt das selbst). Das ist eine
  vorbestehende Lücke gegenüber CLAUDE.md, kein Zen-Thema, und durch diesen Wechsel
  weder besser noch schlechter geworden.
* Zweite, unabhängige Bezugsquelle für dieselben Modelle.

### Negativ / Risiken

* **Kostenerfassung (Invariante #7, Ebene 2).** LiteLLM rechnet Kosten aus seiner
  eigenen Preistabelle, nicht aus Zens tatsächlicher Abrechnung. Ohne explizite
  Preise käme `x-litellm-response-cost` falsch oder leer zurück; `_parse_cost_header`
  fällt dann bewusst auf `0.0` zurück (Security-Audit P7) und `cost_ledger` würde
  still Nullen schreiben — die einzige aktive Kostenbremse (ADR-0010: Ebene 1 ist
  nicht scharf) wäre wirkungslos. **Gegenmaßnahme:** `model_info`-Preise explizit
  gesetzt und live gegengerechnet (siehe Tabelle oben). **Rest-Risiko:** die Preise
  sind ein Stand vom 31.07.2026. Ändert Zen die Liste, driftet `cost_ledger`
  lautlos — die Werte gehören bei jeder Preisänderung nachgezogen.
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

## Offene Punkte

1. **Provider-Bruch ins Wettbewerbsprotokoll** eintragen (31.07.2026, Zyklus-Ebene).
2. **`model_info`-Preise bei jeder Zen-Preisänderung nachziehen** — sonst driftet
   `cost_ledger` lautlos.
3. **Prompt Caching tatsächlich senden** — heute ist es nur ein Config-Flag. Eigenes
   Feature, nicht Teil von F094.
4. **Nach dem 31.08.2026 neu bewerten:** erst mit dem Ablauf des
   Sonnet-5-Einführungspreises (ADR-0008) wird der Preisvergleich aussagekräftig.
