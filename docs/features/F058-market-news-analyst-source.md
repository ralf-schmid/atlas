# F058 — Market-News/Analysten-Quelle (Yahoo-Finance-RSS statt reuters.com)

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Ralfs Auftrag: `https://www.reuters.com/markets/us/` als weitere
Analystenquelle einbauen. Vor der Umsetzung geprüft (CLAUDE.md: "Keine
stillen Annahmen... fragen statt raten" gilt sinngemäß auch für
Zugriffsrechte auf Drittinhalte): reuters.com blockt automatisierten Zugriff
aktiv —

- `robots.txt`: `User-agent: *` → `Disallow: /` (nur eine feste Namensliste
  bekannter Suchmaschinen-/Partner-Bots ist erlaubt, ein selbstgebauter
  ATLAS-Scraper steht nicht drauf).
- Ein direkter Abruf von `/markets/us/` liefert **HTTP 401** (CloudFront-
  Bot-Schutz) — kein reines Konventions-Signal, sondern ein aktiver Block.

Ralf gefragt (Auswahl-Optionen: alternative offene Quelle / manueller
PDF-Fallback wie F011 / trotzdem scrapen / zurückstellen) — Entscheidung:
**alternative Quelle mit offenem Zugriff**, gleiches Muster wie
EDGAR/CoinGecko (offiziell erlaubt, kein Login). Gefunden: Yahoo Finance's
öffentliches Top-Stories-RSS (`https://finance.yahoo.com/news/rssindex`) —
per `robots.txt` erlaubt, kein Login, liefert echte Reuters-Artikel
(`source`-Feld) **plus** echte Analysten-Kursziel-/Rating-Meldungen (Argus
Research "Analyst Report: ...", "Evercore ISI Raises its Price Target on
...", "RBC Capital Raises its Price Target on ...") — inhaltlich näher an
"Analystenquelle" als reine Marktnachrichten.

**Nicht geprüft/eingebaut:** MarketWatch (gleicher Block wie Reuters,
`Disallow: /` für alle Bots) und CNBCs alte RSS-URLs (404, vermutlich
abgeschaltet).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #9 Untrusted Content / Prompt Injection | ja | Gleiche Behandlung wie alle anderen Ingestion-Quellen: `title`/`source`/`url` landen nur als getaggter `research_item.summary`/`raw`-Datenblock, nie in einem System-Prompt mit Schreibrechten (siehe `_build_messages`, unverändert). |
| CLAUDE.md "Zeitschriften-/aktienfinder-Volltexte... nur Metadaten" | ja, analog angewendet | Nur `title`/`url`/`source` werden gespeichert — die RSS-Elemente selbst enthalten ohnehin keinen Artikelvolltext, kein zusätzlicher Abruf der verlinkten Seite. |
| Fairness | nein | Landet im gemeinsamen Research-Pool wie jede andere Quelle — kein Persona-exklusiver Zugriff. |
| Rechtlich/ToS | ja, Kern der Entscheidung | Kein `robots.txt`-Verstoß, kein Umgehen von Bot-Schutz — im Gegensatz zum ursprünglich genannten reuters.com/markets/us/. |

**Kosten:** keine (kostenloser, öffentlicher Feed).

## 3. Testdefinition

`tests/ingestion/test_yahoo_finance_news.py` (Muster: `test_edgar_rss.py`):
RSS-Parsing extrahiert Headlines korrekt, überspringt Items ohne
`guid`/`pubDate`; `HttpYahooFinanceFeedProvider` sendet den User-Agent-Header
und wirft bei HTTP-Fehlern; Upsert idempotent (Re-Sync erzeugt keine
Duplikate); `run_market_news_sync` liest die Config.
`tests/ingestion/test_scheduler.py`: neuer Job `ingestion-market-news`
registriert, alertet nach 2 Fehlschlägen in Folge (gleiches Muster wie alle
anderen Ingestion-Jobs). `tests/orchestrator/test_research_synthesis.py`:
Headline landet als `research_item` mit `source_type="market_news"` innerhalb
des Zyklus-Fensters, wird außerhalb des Fensters korrekt ausgeschlossen.

## 4. Implementierung

- `src/db/models.py`: neues `MarketNewsHeadline` (`market_news_headline`,
  Unique auf `guid`).
- `alembic/versions/4708e243f853_add_market_news_headline.py`: Migration.
- `src/ingestion/yahoo_finance_news.py` (neu): RSS-Fetch (`httpx` + `Mozilla/
  5.0`-User-Agent) + `defusedxml`-Parsing (Invariante #9, XXE-sicher wie
  `edgar_rss.py`) + idempotenter Upsert.
- `src/orchestrator/research_synthesis.py`: neue
  `_research_items_from_market_news_headlines`, in
  `synthesize_research_items` verdrahtet.
- `src/ingestion/scheduler.py`: neuer `ingestion-market-news`-Job (30-Minuten-
  Intervall, gleicher Non-Fatal-Alert-Vertrag wie alle anderen Jobs).
- `config/ingestion.yaml`: neue `market_news`-Sektion (`feed_url`) +
  `schedule.market_news.interval_minutes: 30`.

## 5. Testdurchlauf

`uv run pytest tests/ingestion/test_yahoo_finance_news.py
tests/ingestion/test_scheduler.py tests/orchestrator/test_research_synthesis.py
-q` → 43 passed (8 + 11 + 24). `uv run pytest -q -m 'not integration'` → 502
passed, 10 deselected. `uv run pytest -q -m integration` → 8 passed, 2
skipped (unverändert). `uv run ruff check`/`ruff format --check` → sauber.
`uv run mypy src/ingestion src/orchestrator src/db` → sauber. Migration
lokal gegen echtes Postgres verifiziert (`alembic upgrade head` →
`4708e243f853`, sauber angewendet nach vorherigem `4a5af5b72b93`).

**Live-Verifikation ausstehend:** manueller Sync-Lauf gegen den echten Feed
nach Deploy auf der Box, siehe `docs/deployment.md`.

## 6. Rollback-Pfad

`sudo docker compose` — kein eigener Service, nur ein Scheduler-Job im
bestehenden `scheduler`-Container. Job entfernen: `config/ingestion.yaml`
`market_news`-Sektion + Registrierung in `scheduler.py` zurücknehmen (Commit
revert). Schema: `alembic downgrade -1` (oder Commit-Revert, Tabelle ist rein
additiv, keine Fremdschlüssel von anderen Tabellen darauf).
