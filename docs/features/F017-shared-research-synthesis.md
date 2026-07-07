# F017 — Shared-Research-Synthese

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Ersetzt F016s Platzhalter-`research_item` durch echte Synthese: die Orchestrator-
`shared_research`-Node liest die neuen Zeilen aus den fünf Ingestion-Tabellen
(F009 EDGAR, F010 Screener, F011 Publikationen, F012 aktienfinder, F014 Musterdepot)
seit dem letzten Zyklus derselben `market_session` und schreibt sie als
`research_item`-Zeilen in den gemeinsamen Research-Pool — die Datengrundlage, auf der
der (spätere) Persona-Analyse-Agent aufbaut.

**Scope:** deterministische, LLM-freie Synthese (Text-Templates aus bereits
strukturierten Feldern, keine "Zusammenfassung" im Sinne einer LLM-generierten
Interpretation) für die 5 genannten Quellen, inkrementell seit dem letzten Zyklus
gleicher `market_session`.

**Non-Scope:** **`market_bar` (Kursdaten) bewusst ausgeschlossen** — rohe OHLCV-Bars
sind Basis-Marktdaten für spätere technische-Indikator-Berechnung (ARCHITECTURE.md
§3.5.3), kein "Recherche-Fund" im Sinne dieser Tabelle (kein Titel/keine
Zusammenfassung, die für einen Persona-Analyse-Prompt sinnvoll wäre) — sie werden
weiterhin direkt aus `market_bar` gelesen, nicht dupliziert in `research_item`. Keine
LLM-Zusammenfassung (kommt mit dem Persona-Analyse-Agenten, der zusätzlich zur
strukturierten Synthese hier auch freien Kontext bekommt). Keine Deduplizierung über
mehrere `market_session`-Läufe hinweg hinaus (siehe Design-Entscheidungen).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #9 Untrusted Content | ja | Fremdtext (Publikations-Volltext, Musterdepot-`raw_text`) wird **nicht** 1:1 in `research_item` übernommen — nur bereits geparste, strukturierte Felder (Titel, Aktion/Instrument/Menge/Preis) fließen in `summary`/`raw`. Reduziert Prompt-Injection-Fläche zusätzlich zur allgemeinen Regel (Agenten mit Schreibrechten sehen das ohnehin nie direkt). |
| #10 Fairness | ja | Eine Synthese-Funktion pro Quelle, ein gemeinsamer Research-Pool — keine Persona bekommt eine gefilterte Teilmenge; `list_active_portfolios`/Persona-Zuordnung bleibt in F016 unverändert nachgelagert. |
| CLAUDE.md: keine Zeitschriften-/aktienfinder-Volltexte in UI/Repo | ja | `publication_article.text` (voller Artikeltext) und `musterdepot_transaction.raw_text` bleiben ausschließlich in ihren eigenen Tabellen — `research_item.summary` bekommt nur Titel/Kurzangaben, keinen vollen Fließtext. `aktienfinder_snapshot.fields` sind bereits strukturierte Einzelwerte (kein Volltext), unverändert übernehmbar. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Diese Synthese ist reiner Code (String-Templates aus bereits vorhandenen Werten), kein LLM-Call. |
| Idempotenz/Inkrementalität | ja | Fenster `(vorheriger Cycle.started_at, aktueller Cycle.started_at]` je `market_session` — jede Ingestion-Zeile wird genau vom Zyklus aufgenommen, in dessen Fenster ihr `synced_at` fällt (siehe Design-Entscheidungen zu Grenzfällen). |

**Design-Entscheidungen:**
- **Fenstergrenze ist `synced_at` (wann *unser* System die Zeile erhalten hat), nicht
  das Quell-Datum** (`filed_at`/`screened_at`/`issue_date`/`snapshot_date`/
  `received_at`): ein EDGAR-Filing kann Tage alt sein, aber erst jetzt bei uns
  ankommen (Ingestion-Lag) — über das Quell-Datum zu fenstern würde es dauerhaft
  unsichtbar machen, falls es älter als das vorherige Zyklusfenster ist. `synced_at`
  ist über alle sechs Ingestion-Tabellen hinweg einheitlich vorhanden (F008–F014),
  daher als Dedup-Schlüssel verwendet; das Quell-Datum wandert weiterhin unverändert
  in `research_item.published_at` (fachlich korrektes "wann geschah es").
- **Fenster je `market_session`:** die vorherige `Cycle`-Zeile wird gefiltert nach
  `market_session == aktueller Wert` — Aktien- und Crypto-Zyklen laufen auf getrennten
  Zeitplänen (ARCHITECTURE.md §5.2), ein Aktien-Zyklus soll nicht das Fenster eines
  zwischenzeitlich gelaufenen Crypto-Zyklus erben (und umgekehrt).
- **Bootstrap-Fallback 7 Tage**, wenn es noch keinen vorherigen Zyklus derselben
  `market_session` gibt (erster Lauf überhaupt) — bewusst begrenzt statt "seit
  Anbeginn", um bei künftig größeren Ingestion-Historien keinen unbegrenzten
  Backfill in einem einzigen Zyklus auszulösen. Reine Konvention, per Konstante
  änderbar, keine Konfigurierbarkeit für diese erste Version nötig.
- **Kein Cross-Cycle-Dedup über eine zusätzliche Spalte/Migration:** das Zeitfenster
  ist by construction überlappungsfrei (`(prev.started_at, curr.started_at]`), daher
  keine Notwendigkeit, einzelne Quellzeilen zusätzlich als "bereits verarbeitet" zu
  markieren — hält das Schema unverändert (keine neue Alembic-Migration nötig).
- **Fünf kleine, unabhängig testbare `_research_items_from_<source>`-Funktionen**
  statt einer monolithischen Funktion — gleiches Muster wie die restlichen
  Ingestion-Module, einzeln testbar, `synthesize_research_items` orchestriert nur.
- **`instruments`-Feld:** Ticker/Symbol wo vorhanden (Screener, aktienfinder — ISIN),
  WKN bei Musterdepot (kein Ticker im Modell), leer bei EDGAR (kein
  Symbol/Ticker-Feld in `edgar_filing`, nur `cik`/`company_name`) und bei
  Publikationen (Artikel sind i.d.R. nicht an ein einzelnes Instrument gebunden).

**Kosten:** keine LLM-Calls. **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_research_synthesis.py` (real gegen die lokale Test-Postgres,
`session`-Fixture mit Rollback):
1. Je eine Zeile in allen 5 Quelltabellen mit `synced_at` innerhalb des Testfensters
   → `synthesize_research_items` erzeugt genau 5 `research_item`-Zeilen, korrekt nach
   `source_type` unterscheidbar.
2. Eine Zeile mit `synced_at` **vor** dem Fensterbeginn wird **nicht** übernommen.
3. Eine Zeile mit `synced_at` **nach** dem Fensterende (nach `cycle.started_at`) wird
   **nicht** übernommen.
4. EDGAR-Filing → `research_item.published_at == filed_at`,
   `summary` enthält `form_type` und `company_name`, `instruments == []`.
5. `ScreenerResult` → `instruments == [symbol]`.
6. `PublicationArticle` → `summary` enthält den Titel, **nicht** den vollen
   `text`-Inhalt.
7. `MusterdepotTransaction` → `summary` enthält Aktion/Instrument/Menge/Preis,
   `raw` enthält **nicht** `raw_text`.
8. Ohne vorherigen Cycle derselben `market_session` → Bootstrap-Fenster (7 Tage vor
   `cycle.started_at`) wird verwendet.
9. Vorheriger Cycle einer **anderen** `market_session` wird ignoriert (Bootstrap statt
   dessen Fenster).

## 4. Implementierung

`src/orchestrator/research_synthesis.py`: `synthesize_research_items(session, cycle)`
+ die 5 `_research_items_from_*`-Helper + `_resolve_window_start`.
`src/orchestrator/graph.py`: `_shared_research_node` ruft jetzt
`synthesize_research_items` statt `create_bootstrap_research_item`;
`CycleState.research_item_id: str | None` → `CycleState.research_item_ids: list[str]`
(mehrere Items pro Zyklus statt einem Platzhalter). `create_bootstrap_research_item`
bleibt ungenutzt im Modul stehen? Nein — entfernt, da durch die echte Synthese ersetzt
(kein toter Code, siehe Rollback-Pfad für die Historie in F016).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_research_synthesis.py -q` → 9 passed.
`uv run pytest tests/orchestrator -q -m 'not integration'` → 19 passed.
`uv run pytest tests/orchestrator -q -m integration` → 1 passed (F016s Graph-Test,
jetzt mit einem echten `EdgarFiling`, das in genau 1 `research_item` synthetisiert
wird). `uv run pytest -q -m 'not integration'` (Gesamtsuite) → 271 passed, 3
deselected. `uv run ruff check`/`ruff format --check` → sauber.
`uv run mypy src/orchestrator` → sauber.

**Live-Verifikation (2026-07-07):** `run_current_filings_sync` (F009) gegen den
echten `sec.gov`-Feed ausgeführt → 49 echte Filings synchronisiert. Danach
`scripts/run_cycle.py` gegen die lokale Postgres-Instanz ausgeführt (kein vorheriger
Cycle derselben `market_session` → Bootstrap-7-Tage-Fenster greift, erfasst alle 49):
Ergebnis 49 `research_item`-Zeilen, alle `source_type="edgar_filing"`, Beispiel:
`"4-Filing von Wheeler Ashlee: 4 - Wheeler Ashlee (0002067624) (Reporting)"` mit
`published_at` = echtem `filed_at`-Zeitstempel. Weiterhin 6 `agent_run`-Zeilen (Fanout
über alle 6 Personas unverändert intakt neben der echten Synthese).

## 6. Rollback-Pfad

Additives/ersetzendes Feature ohne Schema-Änderung. Rollback = Commit zurücknehmen —
`graph.py` fällt dann auf F016s vorherigen Stand zurück (`create_bootstrap_research_item`
via `git revert`), keine Migration nötig.
