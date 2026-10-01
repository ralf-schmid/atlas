# F126 — Obergrenze für den market_research-Prompt

Status: implementiert
Datum: 2026-10-01
Phase: Betriebshärtung (ergänzt F047, F095)
Auslöser: Ralf, nach dem ersten Zyklus nach dem LLM-Guthaben-Ausfall 22.09.–01.10.2026

## 1. Zieldefinition

`_run_market_research` schickt **alle** `market_research`-Items eines Zyklus in einen
einzigen LLM-Call. Das Synthese-Fenster (F047) schließt erst mit einem Zyklus, der
eine Decision erzeugt hat — nach einem LLM-Ausfall wächst der Pool also mit jedem
Zyklus weiter. Live 01.10.2026, C4: 8889 Items, Prompt 424 899 Tokens gegen ein
Limit von 200 000 → `ContextWindowExceededError`, keine Marktübersicht.

Normalbetrieb zum Vergleich (C4, 01.–22.09.): 386–466 Items, ~21k Tokens.

**Done heißt:** Der Prompt hat eine harte Obergrenze in Items, per Config
einstellbar; im Normalbetrieb ändert sich nichts.

## 2. Kritische Betrachtung

- **Was im Stau steckt:** fast ausschließlich Wiederholungen. C4 01.10.:
  `market_mover` 6507 Items für 302 Symbole, `screener_result` 1781 für 372;
  `technical_indicator` konstant 384 (pro Zyklus berechnet, nicht gefenstert).
- **Auswahl neueste zuerst** (wie `select_news_items`, F095): die Indikatoren tragen
  den Zeitstempel des Zyklus und sind immer die neuesten — sie bleiben vollständig
  erhalten. Abgeschnitten werden alte Mover-/Screener-Snapshots, deren Information
  ohnehin in den neueren steckt.
- **Fairness (Invariante #10):** unverändert — die Übersicht ist ein Shared-Pool-
  Item für alle Personas.
- **Kosten:** sinken im Stau-Fall; im Normalbetrieb identisch.
- **Verworfen:** Deduplizierung je `(source_type, source_ref)`. Inhaltlich eleganter,
  ändert aber auch den Normalbetrieb (Mover-Verläufe zwischen zwei Zyklen) und
  garantiert allein keine Obergrenze.

## 3. Entscheidungen

- `config/llm.yaml` → `research_agents.market_max_items_per_cycle: 1000`
  (~2× Normalbetrieb, ~48k Tokens bei ~48 Tokens/Item — weit unter 200k).
- Fehlt der Schlüssel, gilt derselbe Default (1000), nicht „unbegrenzt".
- Wird gekappt, loggt der Agent `market_research input capped` (WARNING) mit
  `available`/`used`.

## 4. Tests

- `test_select_market_items_takes_only_market_research_items`
- `test_select_market_items_keeps_the_newest_and_respects_the_limit` (inkl. Item
  ohne `published_at` → zuletzt)
- `test_market_research_prompt_is_capped` — 5 Items, Cap 2, nur die zwei neuesten im
  Prompt
- `tests/llm/test_config.py::test_market_research_cap_is_read_from_the_config`

## 5. Livesetzung

Normaler Deploy (`config/` ist ins Image gebacken → Rebuild). Nachweis: der
Krypto-Zyklus trägt bis zu seinem ersten Zyklus mit Decision noch den Stau; im
Log erscheint dann `market_research input capped` statt eines 400ers, und es
entsteht ein `market_overview`-Item.

## 6. Rollback

`market_max_items_per_cycle` hochsetzen (oder Code-Revert) + Rebuild.
