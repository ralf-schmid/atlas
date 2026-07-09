# F044 — Research-Pool-Signalqualität (EDGAR-Filter + Zeitschriften-Volltext an Agenten)

Status: umgesetzt
Datum: 2026-07-09
Phase: 5

## 1. Zieldefinition

VULTUREs Rückmeldung nach dem ersten Live-Zyklus: der Research-Pool bestehe
"fast ausschließlich aus generischem EDGAR-Rauschen (Form 3/4/144 ohne
Kontext, 424B/FWP-Strukturprodukt-Filings großer Banken, N-CSRS-Fondsberichte)
sowie aus unstrukturierten Zeitschriften-Fragmenten [...] teils nur
Seitenzahlen/Symbole ohne Fließtext" — ohne ein prüfbares Signal bleibt VULTURE
abwartend. Ralfs Auftrag: zwei bereits eingelesene Zeitschriften-Ausgaben
liefern sollen keine Fragmente mehr sein, und die vorhandenen EDGAR-Daten
sollen tatsächlich nutzbar werden — kurz: was brauchen die Agenten, um
handlungsfähig zu sein.

**Scope:** zwei unabhängige, bereits vorhandene Datenquellen besser nutzen —
kein neuer Ingestion-Pfad. **Non-Scope:** Form-4/8-K-Volltext-Parsing (Kauf vs.
Verkauf, Stückzahl, Preis aus der eigentlichen Filing-XML) — das bräuchte einen
neuen Fetch+Parse-Schritt gegen die einzelnen Filing-Dokumente und eine
CIK→Ticker-Zuordnung; als Folge-Feature vorgemerkt, siehe §6.

## 2. Kritische Betrachtung — Root-Cause

Zwei unabhängige Bugs in bereits gebauten Pipelines, keine fehlende Rohdaten:

1. **`PublicationArticle.text` (Ø 1616 Zeichen, live geprüft:
   `der_aktionaer` 2026-07-07 = 212, 2026-07-08 = 203 Artikel, beide bereits in
   der DB) wurde nie in den Research-Pool übernommen.**
   `_research_items_from_publication_articles`
   (`src/orchestrator/research_synthesis.py`) baute `summary` nur aus
   Publikation/Seite/Titel — genau das "nur Seitenzahlen/Symbole" Bild, das
   VULTURE beschreibt. Der Fließtext existierte, wurde aber nie
   weitergereicht.
2. **`ResearchItem.raw` erreichte die Persona-LLM-Aufrufe nie.**
   `_build_messages` (`src/orchestrator/persona_analysis.py`) sendete nur
   `id`/`source_type`/`published_at`/`age_days`/`summary`/`instruments` —
   selbst wenn `raw` angereichert würde, hätte keine Persona es je gesehen.
3. **EDGAR-Feed war komplett ungefiltert** (`type=` leer in
   `config/ingestion.yaml`) — die komplette SEC-Firehose aller Filer, nicht nur
   der für VULTURE relevanten Formulare. Live gemessen (Box-DB,
   09.07.2026): 1257 Filings gesamt, davon nur 451 (36 %) in
   `{8-K, 3, 4, 4/A, 144}`; Rest dominiert von 424B2 (186), 13F-HR (89, große
   Institutionelle), D/D-A (134, Reg-D-Meldungen), N-CSRS/N-PX/497*
   (~110, Fonds-Pflichtberichte) — genau das von VULTURE benannte Rauschen.

| Invariante | Berührt? | Umgang |
|---|---|---|
| Zeitschriften-Volltexte nicht in UI/Repo (CLAUDE.md) | ja, direkt geprüft | `summary` bleibt unverändert Metadaten-only (bestehender Test `test_publication_article_summary_excludes_full_text` bleibt grün). Der Volltext-Auszug landet ausschließlich in `raw`; `src/api/routes.py` `ResearchRefOut` selektiert `raw` nicht — die API/UI-Grenze bleibt der einzige Ort, an dem der Volltext abgeschnitten wird (wie schon im `PublicationArticle`-Docstring vorgesehen: "Full article text is stored here for agent consumption only"). |
| #10 Fairness (kein Informationsvorsprung) | nein | Beide Änderungen wirken auf den gemeinsamen Research-Pool (`research_item`), nicht persona-spezifisch — alle sechs Personas sehen dieselben angereicherten Items. |
| #9 Untrusted Content | nein | Zeitschriftentext war schon vorher als Datenblock (nicht System-Prompt) an Personas mit Order-Rechten vorgesehen; nur der Transportweg (`raw` statt gar nicht) ändert sich. |
| #7 Kosten-Caps | ja, Kostenrisiko | Ein Magazin-Batch (~200 Artikel) kann in einem Zyklus-Fenster landen. Ungekürzt wären das ~200 × 1600 Zeichen ≈ 80–100k Tokens *pro Persona* on top — bei 6 Personas ein realistisches Risiko, die Tages-Caps (1 €/Persona, 5 €/System) in einem einzigen Zyklus zu sprengen. Deshalb `_ARTICLE_EXCERPT_MAX_CHARS = 600` (deterministisches Trunkieren, kein LLM-Call) statt Volltext. `guarded_complete`/`cost_ledger` bleiben die harte Grenze (Invariante #7), das Trunkieren ist nur die Kosten-*Vermeidung*, kein Ersatz dafür. |

**Design-Entscheidungen:**
- **Kein LLM-Zusammenfassungsschritt.** `research_synthesis.py`s bestehendes
  Designprinzip ("Deliberately no LLM calls") bleibt bestehen — die Erweiterung
  ist ein deterministischer String-Cut, keine neue Kostenquelle, kein neuer
  Fairness-Kanal (alle Artikel gleich behandelt).
- **EDGAR-Filterliste = exakt VULTUREs Charter-Signale** (`8-K`,
  `Insider-Käufe` → Form 3/4/4-A/144) plus `SC 13D`/`SC 13G`
  (Beteiligungsmeldungen, gleiche Kategorie "wer kauft/verkauft groß").
  Bewusst keine unternehmensspezifische Filterung (z. B. nur Watchlist-CIKs) —
  das würde eine CIK→Ticker-Zuordnung brauchen, die es noch nicht gibt (§6),
  und liefe der "shared pool, keine Persona-exklusive Quelle"-Invariante
  zuwider, wenn sie falsch implementiert würde.
- **Ein HTTP-GET je Formular-Typ statt ein gefilterter Request** — SECs
  `getcurrent`-Endpoint matcht `type=` nur exakt, keine OR-Verknüpfung über
  einen Request. 7 Typen × alle 30 Min ist gegenüber vorher (1 Request) mehr
  Last, aber weiterhin trivial (siehe `docs/deployment.md`, SEC verlangt nur
  einen validen `User-Agent`, keine Rate-Limit-Sonderregel unterhalb
  aggressiver Polling-Frequenzen).
- **Rückwärtskompatibel:** fehlt `edgar.form_types` in der Config, bleibt das
  alte Einzel-Request-Verhalten unverändert (zwei bestehende Tests laufen
  ungeändert weiter).

**Kosten:** siehe Trunkierung oben — kein unbegrenztes Risiko, aber ein
gemessener zusätzlicher Kosten-Posten (die tatsächliche Token-Zahl zeigt sich
erst im nächsten Live-Zyklus, siehe `cost_ledger`, `docs/deployment.md`
Nachtrag folgt).

## 3. Testdefinition (vor Implementierung geschrieben)

- `tests/orchestrator/test_research_synthesis.py`:
  - `test_publication_article_raw_carries_text_excerpt_for_agents` — `raw["text_excerpt"]` enthält den Artikeltext.
  - `test_publication_article_raw_excerpt_is_truncated_for_long_articles` — > 600 Zeichen werden gekürzt, Suffix `…`.
  - bestehender `test_publication_article_summary_excludes_full_text` bleibt unverändert grün (Volltext bleibt aus `summary` draußen).
- `tests/orchestrator/test_persona_analysis.py`:
  - `test_llm_payload_carries_raw_field_per_research_item` — end-to-end über `analyze_persona_cycle`: `raw` erscheint im tatsächlich an LiteLLM gesendeten JSON-Payload.
- `tests/ingestion/test_edgar_rss.py`:
  - `test_http_edgar_feed_provider_appends_form_type_to_url` — `&type=<urlencoded>` wird angehängt.
  - `test_run_current_filings_sync_fetches_one_request_per_configured_form_type` — ein Request je konfiguriertem Typ, Dedup über `accession_number`.
  - `test_run_current_filings_sync_without_form_types_makes_a_single_unfiltered_request` — Rückwärtskompatibilität ohne `form_types`.

## 4. Implementierung

- `src/orchestrator/research_synthesis.py`: `_excerpt()`-Helfer +
  `_ARTICLE_EXCERPT_MAX_CHARS = 600`; `_research_items_from_publication_articles`
  setzt `raw["text_excerpt"]`.
- `src/orchestrator/persona_analysis.py`: `_build_messages` sendet `item.raw`
  zusätzlich zu `summary`/`instruments`/`age_days` im `research_payload`.
- `src/ingestion/edgar_rss.py`: `HttpEdgarFeedProvider.fetch_current_filings`
  nimmt optionalen `form_type`-Parameter (`&type=` URL-encoded via
  `urllib.parse.quote_plus`); `run_current_filings_sync` liest
  `edgar.form_types` aus der Config, macht bei gesetzter Liste einen Request
  je Typ (`_fetch_filtered_filings`, dedupliziert nach `accession_number`),
  sonst wie bisher einen einzigen ungefilterten Request.
- `config/ingestion.yaml`: `edgar.feed_url` ohne `type=`-Parameter,
  `edgar.form_types: [8-K, 3, 4, 4/A, 144, SC 13D, SC 13G]` neu.
- Kein Alembic-Migrations-Bedarf (keine Schema-Änderung, nur JSONB-Inhalt von
  `research_item.raw`).

## 5. Test & Rollout

- `uv run pytest` (voller Lauf, `DATABASE_URL` gegen lokalen Test-Postgres):
  456 passed. `ruff check`/`format --check`, `mypy` (`src/ingestion/edgar_rss.py`,
  `src/orchestrator/research_synthesis.py`, `src/orchestrator/persona_analysis.py`):
  clean.
- Live-Diagnose vor der Umsetzung (Box-DB, per SSH):
  `select publication, issue_date, count(*), avg(length(text))` bestätigte
  212/203 Artikel mit Ø 1616 Zeichen Volltext bereits vorhanden;
  `select form_type, count(*) from edgar_filing` bestätigte die
  Rauschverteilung (1257 gesamt, 451 im neuen Filter).
- Deployment: nur die vier geänderten Dateien (`config/ingestion.yaml`,
  `src/ingestion/edgar_rss.py`, `src/orchestrator/research_synthesis.py`,
  `src/orchestrator/persona_analysis.py`) — kein voller `rsync --delete`
  (Auto-Mode-Klassifikator lehnt das für punktuelle Fixes ab, siehe
  `docs/deployment.md` Reddit-Eintrag 09.07.2026), `docker compose build api
  scheduler` + `up -d`.
- **Rollback-Pfad:** reiner Code-/Config-Revert (kein Schema-Change). Für
  EDGAR allein reicht auch, `form_types` aus `config/ingestion.yaml` zu
  entfernen — fällt automatisch auf den alten ungefilterten Single-Request
  zurück.

## 6. Follow-up (nicht in diesem Feature)

- **Form-4/8-K-Inhalts-Parsing:** die eigentliche Filing-XML (Transaktions-Code
  P/S, Stückzahl, Preis) liefert erst ein echtes Kauf/Verkauf-Signal statt nur
  "ein Insider hat etwas gemeldet". Braucht einen neuen Fetch-Schritt gegen die
  Filing-Primärdokumente + CIK→Ticker-Zuordnung (z. B. SECs
  `company_tickers.json`) — eigenes Feature-Dokument, da neuer externer Aufruf
  + neues Datenmodell.
