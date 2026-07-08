# F039 — Reddit-Ingestion (CRYPTOR)

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

CRYPTORs erster Live-Zyklus: *"reine Schlagzeilen ohne verwertbaren Kontext
[...] ohne belastbares News-Sentiment"* — es gibt im System keine
Krypto-spezifische Nachrichten-/Sentiment-Quelle. Ralf hat sich für Reddit als
zusätzliche, frei verfügbare Quelle entschieden, über die offizielle OAuth-API
(nicht Scraping) — dafür registriert Ralf einmalig eine Reddit-"script"-App.

**Scope:** neue Ingestion-Quelle (OAuth2-App-only-Fetch + Persistenz +
Research-Synthese) für Posts aus konfigurierten Krypto-Subreddits.
**Non-Scope:** jede Form von Sentiment-Berechnung im Code (siehe
Design-Entscheidungen) — nur rohe Fakten.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Ein gemeinsamer Sync-Pfad, im selben `research_item`-Pool wie jede andere Quelle. |
| #9 Untrusted Content | ja | Reddit-Post-Titel sind Fremdtext (potenziell feindlich/Prompt-Injection) — landen nur als `summary`-Feld im getaggten `research_item`-Datenblock, nie als freier System-Prompt-Text (identisches Muster zu Zeitschriften-Artikeln). |
| #6 Secrets nie im Repo | ja | `REDDIT_CLIENT_ID`/`_SECRET`/`_USER_AGENT` nur aus Environment, Dummy-Werte in `.env.example`. |
| Finanzkennzahlen/Bewertungen nicht vom Code vorwegnehmen | ja | Keine Sentiment-Berechnung in der Ingestion — nur Titel/Score/Kommentarzahl, die Persona bewertet selbst (wie bei jeder anderen Quelle). |

**Design-Entscheidungen:**
- **OAuth2 `client_credentials` (App-only), kein `praw`:** `httpx` ist bereits
  Abhängigkeit, kann den Token-Request + authentifizierte GETs direkt — kein
  neues Package, kein persönliches Reddit-Konto/Login nötig (nur eine
  "script"-App-Registrierung, rein lesender Zugriff auf öffentliche Daten).
- **Keine Sentiment-Berechnung, bewusst:** weder ein Keyword-Scorer noch ein
  Klassifikator im Code — nur Titel/Score/Kommentarzahl werden persistiert,
  identisch zum bestehenden Muster bei Zeitschriften-Artikeln (rohe,
  strukturierte Fakten rein, Interpretation bleibt bei der Persona).
- **Token-Caching in-process** (kein Redis/DB-Persistenz) — bei stündlicher
  Sync-Kadenz und ~1h-Token-TTL ausreichend einfach, mit
  Sicherheitsmarge (60s) vor tatsächlichem Ablauf.
- **Gefenstert wie die ursprünglichen 5 Quellen** (nicht wie F036/Indikatoren):
  ein Reddit-Post ist eine neu eintreffende Rohtatsache, kein abgeleiteter
  Wert.
- **Feste, konfigurierte Subreddit-Liste** (`config/ingestion.yaml`, initial
  r/CryptoCurrency, r/Bitcoin, r/ethereum) statt dynamischer Auswahl — Ralf
  kann sie jederzeit anpassen.

**Kosten:** keine LLM-Calls. **Fairness:** unverändert.

## 3. Testdefinition

`tests/ingestion/test_reddit_sentiment.py` (7 Tests):
1. `parse_listing_response` bildet Reddits JSON-Listing korrekt auf `Post`
   ab.
2. `sync_reddit_posts` idempotent über `post_id` (leer, Insert,
   Wiederholung ohne Duplikate).
3. Token wird innerhalb der TTL wiederverwendet (ein Token-Request für zwei
   Subreddit-Abrufe).
4. Token wird nach Ablauf neu geholt (zwei Token-Requests bei `expires_in=0`).
5. `run_reddit_sync` liest Config + Env, ruft den (gemockten) OAuth-Flow auf,
   persistiert.
6. Fehlende Env-Var wirft einen klaren `ValueError`.

`tests/orchestrator/test_research_synthesis.py`: neue Quelle gefenstert wie
die ursprünglichen 5; explizite Prüfung, dass `raw` **kein** Sentiment-Feld
enthält.

`tests/ingestion/test_scheduler.py`: 6. Job registriert, gleicher
Non-Fatal-Alert-Vertrag wie die anderen 5.

## 4. Implementierung

- `src/db/models.py`: `RedditPost` (neu, Upsert über `post_id`).
- `alembic/versions/c59e1bad9f32_add_reddit_post.py` (neu).
- `src/ingestion/reddit_sentiment.py` (neu): `HttpRedditProvider` (Token-Cache
  + Listing-Fetch), `parse_listing_response`, `sync_reddit_posts`,
  `run_reddit_sync`.
- `src/ingestion/scheduler.py`: `_reddit_job` + Registrierung (stündliches
  Intervall).
- `src/orchestrator/research_synthesis.py`: 8. Quelle
  `_research_items_from_reddit_posts`, `source_type="reddit_post"`.
- `config/ingestion.yaml`: neue `reddit:`-Sektion + `schedule.reddit`.
- `.env.example`: `REDDIT_CLIENT_ID`/`_SECRET`/`_USER_AGENT` (Dummy-Werte).
- `docker-compose.yml`: `scheduler`-Service bekommt die 3 Reddit-Env-Vars.

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 431 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Migration verifiziert: upgrade → downgrade → upgrade zyklisch getestet.
- **Voraussetzung vor Produktions-Deploy:** Ralf registriert eine Reddit-
  "script"-App unter reddit.com/prefs/apps, trägt Client-ID/-Secret + einen
  aussagekräftigen User-Agent-String in die Box-`.env` ein. Bis dahin läuft
  der Job mit Dummy-Werten und schlägt fehl (non-fatal, wie jeder andere
  Ingestion-Job) — kein Blocker für die anderen F035-F040-Features.
- Deployment: rsync + `docker compose build api scheduler` + `up -d` +
  `alembic upgrade head`.
- Verifikation nach Deploy (nach Ralfs Credential-Eintrag): `reddit_post`
  bekommt neue Zeilen; CRYPTOR zitiert sie in einer folgenden Decision.
- **Rollback-Pfad:** `ingestion-reddit`-Job-Registrierung entfernen +
  `alembic downgrade -1` (nur diese eine Tabelle betroffen).
