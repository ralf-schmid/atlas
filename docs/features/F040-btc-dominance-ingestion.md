# F040 — BTC-Dominanz-Ingestion (CoinGecko)

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

CRYPTORs erster Live-Zyklus: *"ohne BTC-Dominanz-Daten [...] fehlt die
Grundlage für eine Trend-Following-Entscheidung"*. CRYPTORs Charter nennt
"BTC-Dominanz als Regime-Filter" explizit als Signal — dafür gibt es im
System keine Quelle. CoinGecko bietet dieses Signal kostenlos, ohne
Authentifizierung, über `/api/v3/global`.

**Scope:** neue Ingestion-Quelle (Fetch + Persistenz + Research-Synthese) für
BTC-Dominanz und Gesamt-Marktkapitalisierung. **Non-Scope:** Sentiment/News
(siehe [F039](F039-reddit-ingestion.md), separates Feature).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Ein gemeinsamer Sync-Pfad, im selben `research_item`-Pool wie jede andere Quelle — keine Persona bekommt exklusiven Zugriff. |
| #6 Secrets nie im Repo | nein | Kein Auth nötig, kein Secret. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Reiner Datenabruf, keine Berechnung — die Persona interpretiert die bereits gemessene Dominanz-Zahl. |

**Design-Entscheidungen:**
- **Kein Unique-Constraint/Upsert**, anders als jede andere Ingestion-Quelle:
  jeder geplante Abruf ist ein legitimer neuer Zeitreihen-Punkt, kein
  "Re-Delivery" derselben Tatsache — es gibt nichts, worüber ein Konflikt
  entstehen könnte. Bewusste, im Modell-Docstring festgehaltene Abweichung vom
  sonstigen Muster.
- **Eigenständiges Feature statt Teil von F039** (Reddit): unterschiedliches
  Risikoprofil — CoinGecko braucht kein Auth und kein Rate-Limit-Bewusstsein,
  Reddit (F039) beides.
- **Stündliches Intervall** (kein Zeitzonenbezug nötig, anders als die
  aktienbezogenen Jobs) — passend zu CRYPTORs eigener 6h-Zykluskadenz.

**Kosten:** keine. **Fairness:** unverändert.

## 3. Testdefinition

`tests/ingestion/test_coingecko_global.py`:
1. `parse_global_response` extrahiert BTC-Dominanz und Gesamt-Marktkapitalisierung
   aus einer CoinGecko-förmigen Fixture.
2. `sync_btc_dominance_snapshot` fügt eine Zeile ein.
3. Zwei Aufrufe mit identischen Werten erzeugen zwei Zeilen (kein Upsert —
   Beleg für die bewusste Abweichung oben).
4. `run_coingecko_sync` liest die Config, ruft den (gemockten) HTTP-Endpunkt
   auf, persistiert.

`tests/orchestrator/test_research_synthesis.py`: neue Quelle gefenstert wie
die ursprünglichen 5 (innerhalb/außerhalb des Zyklus-Fensters).

`tests/ingestion/test_scheduler.py`: 5. Job registriert, Non-Fatal-Alert-Vertrag
wie die anderen 4.

## 4. Implementierung

- `src/db/models.py`: `BtcDominanceSnapshot` (neu, kein Unique-Constraint).
- `alembic/versions/ce9754a967cb_add_btc_dominance_snapshot.py` (neu).
- `src/ingestion/coingecko_global.py` (neu): `HttpCoinGeckoProvider`,
  `parse_global_response`, `sync_btc_dominance_snapshot`, `run_coingecko_sync`.
- `src/ingestion/scheduler.py`: `_coingecko_job` + Registrierung
  (stündliches Intervall).
- `src/orchestrator/research_synthesis.py`: 7. Quelle
  `_research_items_from_btc_dominance_snapshots`, `source_type="btc_dominance"`.
- `config/ingestion.yaml`: neue `coingecko:`-Sektion + `schedule.coingecko`.
- Kein Docker-Compose-/Env-Var-Bedarf (kein Auth).

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 421 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Migration verifiziert: upgrade → downgrade → upgrade zyklisch getestet.
- Deployment: rsync + `docker compose build api scheduler` + `up -d` +
  `alembic upgrade head`.
- Verifikation nach Deploy: `btc_dominance_snapshot` bekommt nach der ersten
  Stunde neue Zeilen.
- **Rollback-Pfad:** `ingestion-coingecko`-Job-Registrierung entfernen +
  `alembic downgrade -1` (nur diese eine Tabelle betroffen).
