# F097 — Prompt Caching tatsächlich senden

**Status:** Implemented
**Phase:** 5 (Härtung)
**Deployed:** 2026-08-01
**Abhängigkeiten:** `src/orchestrator/persona_analysis.py`
Berührt Invariante **#7** (Kosten-Caps).

## 1. Zieldefinition

CLAUDE.md: *„Prompt Caching für Charter/Regeln ist Pflicht."* Bei der Umsetzung von
F094 fiel auf, dass ATLAS **gar kein `cache_control` sendet** —
`prompt_caching: true` in `config/llm.yaml` wurde nirgends im Code ausgewertet.
F006 gibt das in seiner eigenen Tabelle zu: *„hier nur konfiguriert, nicht im
Python-Code erzwungen."*

## 2. Kritische Betrachtung — wo der Breakpoint hingehört

Der naheliegende Griff wäre, die Charter (System-Prompt) zu markieren. **Das wäre
ein stiller No-Op.** Anthropic cached einen Prefix erst ab **1024 Tokens**; live
gemessen:

```
VULTURE  chars: 2274  ~tokens: 568
GUARDIAN chars: 2354  ~tokens: 588
```

Die Charter liegt bei ~570 Tokens und damit unter der Schwelle — markiert man nur
sie, passiert nichts, und zwar ohne Fehlermeldung.

Der reale Hebel liegt in den **Folgerunden**: `_run_llm_with_tools` macht bis zu
`_MAX_TOOL_ROUNDS + 1 = 3` Calls je Versuch, und F065s Parse-Retries starten
bewusst aus einer **frischen Kopie derselben Messages** — der Prefix aus
Charter + erster User-Nachricht ist über alle diese Calls identisch. Live gemessen
über 3 Tage: **184 Calls auf ~48 Agent-Runs ≈ 3,8 Calls je Run**, avg. 9.819
Input-Tokens.

Der Breakpoint gehört deshalb ans **Ende der ersten User-Nachricht**: gecached wird
damit Charter + Research-Payload zusammen, also weit über 1024 Tokens.

### Rechnung

Aus F094 live gemessen: Cache-Write kostet 1,25×, Cache-Read 0,1×. Break-even ist
damit der **zweite** Call eines Runs; bei 3,8 Calls im Schnitt zahlt es sich aus.
Kein Risiko nach oben: schlimmstenfalls (Run mit nur einem Call) sind es 25 %
Aufschlag auf den Input dieses einen Calls.

## 3. Umsetzung

`_build_messages(..., prompt_caching: bool)`. Ist der Flag aus, entsteht **exakt**
die Form von vor F097 (plain string) — das ist der Rollback-Pfad, und ein Test
hält es fest. Ist er an, wird die User-Nachricht zu einem Content-Block mit
`cache_control: {"type": "ephemeral"}`.

Der Flag kommt aus `role.prompt_caching`, also aus `config/llm.yaml` — das dort seit
F006 stehende Feld bekommt damit erstmals Wirkung.

## 4. Tests

| Test | Sichert |
|---|---|
| `test_prompt_caching_marks_the_first_user_block_not_the_charter` | Breakpoint sitzt hinter der User-Nachricht, System bleibt schlichter Text (§2) |
| `test_prompt_caching_off_keeps_the_plain_string_shape` | Rollback ergibt die Vor-F097-Form |
| `test_prompt_caching_does_not_change_the_payload_text` | die Persona sieht denselben Prompt wie vorher |

Vier bestehende Payload-Tests lasen `content` als String und brachen. Sie prüfen
den **Inhalt**, nicht die Transportform — daher ein Helper `_user_text()`, der
beide Formen akzeptiert, statt die Tests auf die alte Form festzunageln.

**Ergebnis:** 788 passed (vorher 785), `ruff` und `mypy` sauber.

## 5. Live-Verifikation (2026-08-01)

**Mechanismus**, mit exakt der F097-Nachrichtenform (System als String, User als
Content-Block mit `cache_control`) gegen den produktiven Proxy:

```
Lauf 1: prompt=6516  write=6514  read=0     cost=0.016449
Lauf 2: prompt=6516  write=0     read=6514  cost=0.0014668   → 11x guenstiger
```

**Wirkung im echten Zyklus.** Ein vollstaendiger Zyklus, 0 Tracebacks, alle sechs
Personas plus beide Recherche-Rollen `SUCCEEDED`. Kosten je 1.000 Input-Tokens,
`claude-sonnet-5`/PERSONA, 3-Tage-Fenster:

```
   phase   | calls | tokens_in | usd_pro_1k_input
-----------+-------+-----------+------------------
 vor F097  |   154 |   1767988 |         0.002535
 nach F097 |    15 |    165480 |         0.001693
```

**33 % guenstiger.** (Blended: Zaehler ist die Gesamtkosten inkl. Output, Nenner nur
Input — als Vorher/Nachher-Vergleich bei vergleichbarer Last aussagekraeftig, nicht
als reiner Input-Preis zu lesen. Nur Folgerunden treffen den Cache, Output-Tokens
werden nie gecached.)

Hochgerechnet auf den gemessenen Verbrauch von ~1,58 USD/Tag (Sonnet/PERSONA) sind
das rund **0,5 USD/Tag** bzw. ~15 USD/Monat.

## 6. Rollback

`prompt_caching: false` je Rolle in `config/llm.yaml` + Rebuild (Config ist ins
Image gebacken). Die Message-Form fällt damit auf den Vor-F097-Zustand zurück.
