# F108 — Market-News-Sync: Ersatz für den abgeschalteten Yahoo-`rssindex`-Feed

Status: umgesetzt (Deploy offen, siehe §5)
Datum: 2026-10-06
Auslöser: Telegram-Alert „Market-News-Sync mehrfach fehlgeschlagen"

## 1. Zieldefinition

Der Scheduler-Job `ingestion-market-news` (F058) schlägt jeden Lauf fehl. Ursache,
reproduziert am 2026-10-06: `https://finance.yahoo.com/news/rssindex` antwortet mit
**HTTP 404** (Yahoo-„sad panda"-Fehlerseite) → `raise_for_status()` →
`httpx.HTTPStatusError`. Auch die naheliegenden Varianten (`/rss/topstories`,
`/news/rss`, `/rss/`, `/topic/stock-market-news/rss`) liefern 404.

**Ziel:** Job läuft wieder, `market_news_headline` füllt sich wieder.

**Scope:** `feed_url` in `config/ingestion.yaml`, Parser in
`src/ingestion/yahoo_finance_news.py`. **Non-Scope:** Schema, Scheduler, Synthese.

## 2. Kritische Betrachtung

- **Ersatzquelle:** `https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC`
  — derselbe Anbieter, öffentlich, ohne Login, liefert ~19 aktuelle Markt-Headlines
  (Yahoo-eigene Marktberichte, CNN, Motley Fool, …). Inhaltlich enger als die
  früheren Top-Stories (weniger Analysten-Rating-Meldungen); die analystenlastigen
  Meldungen kommen inzwischen zusätzlich über Alpaca-News (F105).
- **Formatunterschiede:** `pubDate` im RFC-822-Format statt ISO 8601, kein
  `<source>`-Element. Parser akzeptiert jetzt beide Datumsformate; fehlt `<source>`,
  wird der Host des Links (ohne `www.`) als Quelle gespeichert statt pauschal
  „Yahoo Finance" (sauberere Lineage).
- **Invarianten:** #9 unverändert (`defusedxml`, Daten nur in den Pool). #10: die
  Index-Symbole sind allgemeine Marktnachrichten, keine Persona bekommt eine
  exklusive Quelle. Keine Kosten (kein LLM-Call).
- **Idempotenz:** `guid` ist im neuen Feed eine UUID — weiterhin stabil je Artikel,
  Upsert auf `guid` bleibt korrekt.

## 3. Testdefinition

- Neu: `test_parse_rss_feed_handles_rfc822_dates_and_missing_source` (RFC-822-Datum
  → naive UTC, Quelle aus Link-Host).
- Bestehende Tests (ISO-Datum, `<source>` vorhanden, HTTP-Fehler, Upsert/Idempotenz)
  bleiben unverändert grün.

## 4. Implementierung

- `config/ingestion.yaml`: `market_news.feed_url` umgestellt.
- `src/ingestion/yahoo_finance_news.py`: `_parse_pub_date` mit RFC-822-Fallback
  (`email.utils.parsedate_to_datetime`), Quelle aus Link-Host als Fallback.

## 5. Testdurchlauf / Livesetzung

Lokal (ohne Postgres): Parser- und Provider-Tests direkt ausgeführt → grün; Abruf
des echten neuen Feeds über `HttpYahooFinanceFeedProvider` → 19 Headlines korrekt
geparst. `ruff check`, `ruff format --check`, `mypy src/ingestion` → sauber. Die
DB-gestützten Tests laufen in CI.

**Deploy offen:** rsync + `docker compose build scheduler` + `up -d scheduler` auf
der Box; danach im Scheduler-Log prüfen, dass `Market-News-Sync` ohne Fehler läuft
und `market_news_headline` neue Zeilen bekommt.

## 6. Rollback-Pfad

Commit revert. Notfalls Job ganz stilllegen: Registrierung in `scheduler.py`
auskommentieren — der alte Feed ist tot, ein Revert allein bringt den Fehler zurück.
