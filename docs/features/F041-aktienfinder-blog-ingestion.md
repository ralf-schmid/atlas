# F041 — aktienfinder.net-Blog/Analysen als tägliche Wissensbasis

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

Ralfs Beobachtung: aktienfinder.net bietet über die bisherige, ISIN-basierte
Snapshot-Ingestion (F012/F037) hinaus noch mehr, was die Personas brauchen
könnten — mehrere Börsenbriefe/Analysen/Empfehlungen im Blog
(`/blog/`, `/blog/aktienanalyse/`, `/blog/kaufenswerte-aktien/`) sowie
zusätzliche Kennzahlen-Kriterien (Dividendenertrag, Dividendenwachstum,
Gewinnwachstum, Stabilität, Cashflow, Kursziel) über das Aktienfinder-Tool
selbst. Zwei Teilaufgaben:

1. **Blog/Analysen/Empfehlungen** einmal täglich abfragen, in die DB als
   Datengrundlage für die Personas bereitstellen.
2. **Erweiterte Kriterien-Suche** über den bestehenden, eingeloggten
   Aktienfinder-Snapshot-Pfad (F012/F037).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Zeitschriften-/aktienfinder-Volltexte nicht in UI/Repo | ja | Nur Titel/Datum/Kategorie/Tags/Premium-Flag der öffentlichen Archiv-Listings werden gespeichert — nie der Premium-Artikeltext selbst (der bräuchte ohnehin einen Login, den dieser Pfad bewusst nicht nutzt). Identisches Muster zu `publication_article` (F011). |
| #10 Fairness | ja | Ein gemeinsamer Sync-Pfad, im selben `research_item`-Pool wie jede andere Quelle. |
| #9 Untrusted Content | ja | Artikeltitel sind Fremdtext — landen nur als getaggtes `summary`-Feld, nie als freier Prompt-Text. |
| Keine neue Abhängigkeit ohne Not | ja | Regex-Parser statt BeautifulSoup/lxml — die Elementor-generierte Archiv-Struktur ist regulär genug (siehe unten), passt zum bestehenden Repo-Stil (`publications_pipeline.py`s Font-Heuristik ist ebenfalls Hand-Parsing statt einer PDF-Layout-Bibliothek). |

**Design-Entscheidungen — Teil 1 (Blog/Analysen):**
- **Nur öffentliche Archiv-Listings, kein Login, kein Playwright.** Live
  geprüft (`curl` gegen alle 3 URLs): die Listing-Seiten sind ohne
  Anmeldung erreichbar und zeigen Titel/Datum/Kategorie/Tags/Premium-Flag
  vollständig — nur der Volltext einzelner Premium-Artikel braucht ein Login.
  Das deckt genau das ab, was laut Invariante ohnehin gespeichert werden darf.
- **Regex- statt BeautifulSoup-Parser:** die Seiten sind
  Elementor-generiert (WordPress-Page-Builder) mit sehr regulärer Struktur
  (`<article class="... post-NNNNN ... category-XXX tag-YYY ...">`) — ein
  gezielter Regex-Parser reicht, live gegen alle 3 echten Seiten verifiziert
  (siehe Test & Rollout).
- **Nur Seite 1 je Listing-URL**, keine Pagination-Crawls — für einen
  täglichen Inkrement-Sync ausreichend (neue Artikel erscheinen zuerst auf
  Seite 1), kein Backfill nötig.
- **Dedupe über die 3 Listing-URLs hinweg per WordPress-`post_id`:** `/blog/`
  ist eine Obermenge der beiden spezifischeren Archive — derselbe Artikel
  taucht ggf. mehrfach auf, wird aber nur einmal gespeichert.
- **Keine eigene Kategorisierung/Instrument-Zuordnung im Code:** `tags`
  (z. B. `tag-general-mills`) werden roh mitgespeichert, aber nicht als
  validiertes `instruments`-Feld interpretiert — das wäre Rätselraten
  (Tag-Slug → Ticker ist nicht immer eindeutig), die Persona liest Titel +
  Tags selbst.

**Design-Entscheidungen — Teil 2 (erweiterte Kriterien):**
- `extract_snapshot`/`field_selectors` (F012) sind bereits vollständig
  config-getrieben — neue Kriterien brauchen **keinen Code-Change**, nur neue
  Einträge in `config/ingestion.yaml`s `aktienfinder.field_selectors`.
  `price_target` (Kursziel) nutzt dasselbe robuste has-text-Label-Muster wie
  `price`/`isin`/`dividend_yield`.
- **Cashflow/Gewinn-Stabilität sind NICHT live verifiziert** — diese Session
  hat keinen Zugriff auf Ralfs aktienfinder-Login (bewusst, siehe
  Auto-Mode-Klassifikator-Entscheidung weiter oben in dieser Konversation).
  Bewusst has-text statt `:nth-match` gewählt: ein falsches Label liefert
  sicher `None` (bestehender Contract, siehe `test_extract_snapshot_yields_none_for_missing_selector`),
  nie einen falsch zugeordneten Wert. **Ralf: bitte einmal eingeloggt
  prüfen/korrigieren** (Selektoren in `config/ingestion.yaml`).

**Kosten:** keine LLM-Calls, keine neue Abhängigkeit. **Fairness:**
unverändert.

## 3. Testdefinition

`tests/ingestion/test_aktienfinder_blog.py` (5 Tests):
1. `parse_listing_html` extrahiert Titel/URL/Kategorie/Tags/Premium-Flag/Datum
   korrekt aus einer echten (verkürzten) Fixture.
2. Leere/artikellose Seite → leere Liste.
3. `sync_aktienfinder_blog_posts` idempotent über `post_id`.
4. `run_aktienfinder_blog_sync` dedupliziert Artikel, die auf mehreren
   überlappenden Listing-URLs erscheinen.

`tests/orchestrator/test_research_synthesis.py`: neue Quelle gefenstert wie
Reddit/BTC-Dominanz (neu eintreffende Rohtatsache, nicht wie die
Indikatoren).

`tests/ingestion/test_scheduler.py`: 7. Job registriert, gleicher
Non-Fatal-Alert-Vertrag.

## 4. Implementierung

- `src/db/models.py`: `AktienfinderBlogPost` (neu, Upsert über `post_id`).
- `alembic/versions/4a5af5b72b93_add_aktienfinder_blog_post.py` (neu).
- `src/ingestion/aktienfinder_blog.py` (neu): `HttpBlogListingProvider`,
  `parse_listing_html`, `sync_aktienfinder_blog_posts`,
  `run_aktienfinder_blog_sync`.
- `src/ingestion/scheduler.py`: `_aktienfinder_blog_job` + Registrierung
  (täglich 05:30 America/New_York, vor den anderen aktienbezogenen Jobs).
- `src/orchestrator/research_synthesis.py`: 9. Quelle
  `_research_items_from_aktienfinder_blog_posts`, `source_type="aktienfinder_blog"`.
- `config/ingestion.yaml`: neue `aktienfinder_blog:`-Sektion + `schedule.aktienfinder_blog`;
  `aktienfinder.field_selectors` um `price_target`/`cashflow`/
  `quality_score_earnings_stability` erweitert (letztere zwei unverifiziert,
  siehe oben).

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 441 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Migration verifiziert: upgrade → downgrade → upgrade zyklisch getestet.
- **Parser live gegen alle 3 echten Seiten verifiziert** (nicht nur gegen die
  Test-Fixture) — `curl` + `parse_listing_html` gegen
  `aktienfinder.net/blog/`, `/blog/aktienanalyse/`, `/blog/kaufenswerte-aktien/`:
  12/12/40 Artikel korrekt extrahiert, inkl. korrektem Premium-Flag
  (z. B. "Top 50 Dividenden-Aktien" korrekt als frei/nicht-Premium erkannt)
  und korrektem Datums-Parsing über mehrere Monate.
- Deployment: rsync + `docker compose build api scheduler` + `up -d` +
  `alembic upgrade head`.
- Verifikation nach Deploy: manueller Lauf gegen die echten, öffentlichen
  URLs → echte Zeilen in `aktienfinder_blog_post`.
- **Rollback-Pfad:** `ingestion-aktienfinder-blog`-Job-Registrierung entfernen
  + `alembic downgrade -1` (nur diese eine Tabelle betroffen).

**Nachtrag 09.07.2026 (Live-Verifikation mit echten Zugangsdaten, siehe F043):**
Die 3 unverifizierten Platzhalter (`price_target`/`cashflow`/
`quality_score_earnings_stability`) existieren **nicht** als einfache Felder
auf der Profil-Seite — die Live-Prüfung ergab, dass diese Kriterien nur im
separaten Aktienfinder-Screener-Tool als Tabellenspalten existieren. Die 3
Platzhalter wurden aus `field_selectors` entfernt; die Kriterien sind jetzt
über einen neuen, eigenen Extraktionspfad (`screener_fields`,
`extract_screener_row`) abgedeckt — siehe
`docs/features/F043-aktienfinder-screener-criteria.md`.
