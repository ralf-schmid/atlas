# F128 — Research-Auswahl: Rotation statt Alphabet, ISIN→Ticker, BTC-Dominanz als eine Zeile

Status: implementiert, noch nicht live
Datum: 2026-10-17
Phase: 6 (Vorbereitung Saison 2, [ADR-0020](../adr/0020-gewinner-entscheidung-und-live-gang.md) Option B)
Auslöser: Ralfs Go vom 17.10.2026 für die F120-Fixes

## 1. Zieldefinition

Behebt die drei Ursachen U1–U3 aus [F120](F120-guardian-cryptor-inaktivitaet.md),
die ohne eigenen ADR auskommen. Mit dem Wettbewerbsende ist der Grund weggefallen,
sie nicht anzufassen (F120 §5).

| # | F120-Befund | Fix |
|---|---|---|
| U1 | Innerhalb eines `source_type`-Buckets bleibt bei identischem `published_at` die Heap-Reihenfolge stehen, also alphabetisch. Jeder Zyklus zeigt dieselben ~8 Titel. | Zweitkriterium `research_item.id` (UUID4, je Zyklus neu). Damit gibt es je Zyklus eine neue, zufällige und trotzdem deterministische Reihenfolge, und über die Zyklen kommt das ganze Universum dran. |
| U2 | aktienfinder-Snapshots tragen nur die ISIN. Für eine ISIN gibt es keinen Kurs, also wird jeder Kauf als `insufficient_price_history` verworfen. | Die Synthese setzt `instruments` auf den Ticker aus `aktienfinder.ticker_by_isin` (F067) und nennt beide im Text. Zusätzlich übersetzt der Entscheidungspfad eine zugeordnete ISIN vor der Kurs-Abfrage in den Ticker. |
| U3 | `btc_dominance` liefert je Zyklus ~12 nahezu identische Zeilen und belegt ~23 % des Prompt-Budgets. | Eine Zeile je Zyklus: letzter Wert, Veränderung seit der ersten Messung im Fenster, Anzahl der Messungen. |

**Done heißt:** Alle drei Fixes sind getestet und live, und im ersten Zyklus danach
lassen sich die erwarteten Effekte stichprobenhaft nachweisen (§6).

**Non-Scope:**
- U1 Punkt 2 aus F120 §5, also ein **persona-spezifischer Universums-Filter**.
  Er berührt Invariante #10 unmittelbar und braucht vorher einen ADR, siehe
  [ADR-0021](../adr/0021-persona-universums-filter.md) (`proposed`).
- **Volatilitätsadaptives Sizing** (ADR-0018 D.5). Es berührt Invariante #1 und
  die Positionsgröße, ist also ein Geld-Thema mit eigenem ADR.
- Munich Re (`DE0008430026`) hat keinen Ticker-Eintrag (F067: kein liquider
  Alpaca-Handelsplatz) und bleibt deshalb unkaufbar. Das ist korrekt so.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, gestärkt | Alle drei Regeln sind für alle Personas identisch. Die Rotation hängt nur an den IDs des **gemeinsamen** Zyklus-Pools, nicht an der Persona: Alle sechs sehen im selben Zyklus denselben Ausschnitt. Der Zustand vorher war formal fair, traf aber die Personas je nach Lage ihres Universums im Alphabet unterschiedlich hart. |
| #4 Stop-Loss | nein | Ein Kauf auf eine ISIN wird nur dann zum Kauf auf den Ticker, wenn der Ticker eine Kursreihe hat. Ohne Kurs bleibt es bei `insufficient_price_history`. |
| #1 Risk-Gate | nein | Kein Risk-Parameter wird berührt. Das Gate prüft den Ticker wie jeden anderen. |
| #3 Lineage | nein | `input_research_ids` bleibt unverändert. Die ISIN bleibt in `source_ref` und im Text der Research-Zeile sichtbar. |
| #9 Untrusted Content | nein | Es kommt kein Fremdtext hinzu. |
| Charter | nein | Kein `charter_version`-Bump: Es ändert sich, was im Pool-Ausschnitt landet, nicht der Charter. |

**Kosten:** U3 setzt ~6 Slots für andere Items frei. Die Prompt-Größe bleibt
gleich (Cap 30), es entstehen also keine Mehrkosten.

**Grenze von U1 für CRYPTOR (ehrlich):** Die Rotation verteilt die ~6–8
Indikator-Slots zufällig über ~380 Symbole. CRYPTORs zehn Paare erscheinen damit
im Schnitt in etwa jedem fünften Zyklus statt, wie bisher, nur AAVE/USD in jedem.
Das ist fairer, aber nicht genug, damit CRYPTOR sein Charter tatsächlich spielen
kann. Der eigentliche Hebel dafür ist der Universums-Filter (ADR-0021). Bis dahin
bleibt `search_research_pool` (F045) CRYPTORs Weg zu seinen Paaren.

**Vergleichbarkeit:** Saison 1 ist abgeschlossen und bleibt reproduzierbar (F121).
Saison 2 startet mit diesen Regeln, ein Mischbestand innerhalb einer Saison
entsteht also nicht.

## 3. Testdefinition (vor der Umsetzung)

`tests/orchestrator/test_persona_analysis.py`

1. Ein Bucket mit vielen Items und identischem `published_at`: Die Auswahl richtet
   sich nach der ID, nicht nach der Einfüge- oder Symbolreihenfolge.
2. Die Auswahl ist deterministisch. Zweimal aufgerufen und mit umgekehrter
   Eingabereihenfolge liefert sie dasselbe Ergebnis (der Companion-Lookup aus F101
   verlässt sich darauf).
3. `published_at` bleibt das erste Kriterium: Ein neueres Item schlägt ein älteres
   unabhängig von der ID.
4. Ein Kauf auf eine zugeordnete ISIN (`US0378331005`) mit vorhandener
   AAPL-Kursreihe wird als Kauf auf `AAPL` persistiert, nicht als
   `insufficient_price_history`.
5. Ein Kauf auf eine **nicht** zugeordnete ISIN bleibt
   `insufficient_price_history` (Regressionsschutz).

`tests/orchestrator/test_research_synthesis.py`

6. Ein aktienfinder-Snapshot mit zugeordneter ISIN trägt `instruments=["AAPL"]`,
   der Text nennt Ticker und ISIN, `source_ref` behält die ISIN.
7. Ein Snapshot mit nicht zugeordneter ISIN behält die ISIN als Instrument.
8. Mehrere BTC-Dominanz-Snapshots im Fenster ergeben **genau eine** Zeile mit dem
   letzten Wert, der Veränderung gegenüber dem ersten Wert und der Anzahl der
   Messungen. `published_at` ist der Zeitpunkt der letzten Messung.
9. Die bestehenden Tests (eine Messung im Fenster, keine Messung außerhalb)
   bleiben grün.

`tests/orchestrator/test_symbol_universe.py`

10. `load_ticker_by_isin` liest die Zuordnung aus der Config, und
    `resolve_stock_seed_watchlist` nutzt dieselbe Quelle.

## 4. Implementierung

- `src/orchestrator/persona_analysis.py`: `_select_prompt_items` sortiert je
  Bucket nach `(published_at desc, id asc)`. In `_resolve_decision` wird eine
  ISIN aus `ticker_by_isin` vor dem Aktions-Dispatch in den Ticker übersetzt.
- `src/orchestrator/research_synthesis.py`: aktienfinder-Snapshot mit
  Ticker-Mapping, BTC-Dominanz als eine Zeile je Zyklus.
- `src/orchestrator/symbol_universe.py`: `load_ticker_by_isin` als einzige
  Lesestelle der Zuordnung.

## 5. Testdurchlauf

Lokal am 17.10.2026 gegen Postgres 16 + pgvector (dieselbe Alembic-Migration wie
in CI): Die neuen Tests 1, 2, 4, 6 und 8 waren vor der Umsetzung rot, die
Regressionsschutz-Tests 3, 5 und 7 schon vorher grün.

Danach:
- `ruff check .` und `ruff format --check .` sauber
- `mypy src` ohne Befund
- `pytest tests/ --cov=src`: **1280 passed**, Coverage 92,04 % (Gate 90 %)

Maßgeblich ist CI auf dem PR.

## 6. Livesetzung (Ralf, auf der Box)

1. Deploy wie gewohnt: rsync, `docker compose build api web scheduler telegram-bot`,
   `up -d`. Keine Migration, keine neue Env-Var, keine Änderung an
   `docker-compose.yml`, also auch keine am `ugreen-Box`-Repo.
2. Nachweis im ersten Zyklus danach:
   - `SELECT count(*) FROM research_item WHERE source_type='btc_dominance' AND cycle_id=<neuester Zyklus>;` → genau 1
   - Agent Trace zweier aufeinanderfolgender Zyklen: Die `technical_indicator`-Items
     im Prompt unterscheiden sich und beginnen nicht mehr bei `AADX, AAOI, AAPL …`.
   - `SELECT instruments FROM research_item WHERE source_type='aktienfinder_snapshot' ORDER BY published_at DESC LIMIT 6;`
     → Ticker statt ISIN (außer Munich Re)

## 7. Rollback

Commit-Revert und Rebuild. Kein Config-Flag: Alle drei Änderungen sind reine
Auswahl- und Darstellungslogik ohne Datenmigration. Ein Revert stellt das alte
Verhalten vollständig wieder her.
