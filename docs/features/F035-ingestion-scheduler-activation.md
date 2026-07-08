# F035 — Ingestion-Scheduler-Aktivierung

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

Ralfs Auswertung des ersten Live-Zyklus (Decision Journal, siehe
[F034](F034-persona-detail-page.md)): alle 6 Personas lehnten korrekt jeden
Trade ab, aber VULTURE explizit mit der Begründung "warte auf verwertbare
EDGAR-Filings" — obwohl F009 (EDGAR), F010 (VULTURE-Screener) und F008
(Markt-Bar-Sync) seit Phase 3/4 fertig implementiert und getestet sind. Direkte
Prüfung: alle drei Entry-Points (`run_current_filings_sync`,
`run_daily_screener`, `run_daily_sync`) tragen wortgleich den Docstring-Satz
"Not wired into a scheduler yet (P4/ops follow-up)" — sie liefen bisher
ausschließlich in Tests, nie in Produktion.

**Scope:** die drei bestehenden `run_*`-Entry-Points in den bereits laufenden
Scheduler-Prozess einhängen (kein zweiter Service), plus die in F008 §2 schon
angekündigte dynamische Watchlist (offene Positionen + Screener-Kandidaten)
für den Markt-Bar-Sync. **Non-Scope:** aktienfinder (F037, braucht zusätzlich
einen Playwright-Binary-Fix und eine Kandidatenliste — eigenes Feature),
technische Indikatoren (F036, baut auf den hier gelieferten frischen
`market_bar`-Daten auf).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Ein Sync-Pfad, ein gemeinsamer Datensatz (`edgar_filing`/`screener_result`/`market_bar`) — unverändert gegenüber F008/F009/F010, nur jetzt tatsächlich mit Daten gefüllt. Die dynamische Watchlist ist reiner DB-Read (Positionen + Screener), kein Broker-Live-Call, keine Persona bevorzugt. |
| #6 Secrets nie im Repo | ja | `EDGAR_USER_AGENT` (existiert schon in `.env.example`) wird `docker-compose.yml`s `scheduler`-Service-Environment ergänzt — Wert kommt weiterhin ausschließlich aus der Box-`.env`. |
| Ein-Scheduler-Prozess | ja | Neue Jobs laufen auf derselben `BackgroundScheduler`-Instanz wie die Zyklen (`src/orchestrator/scheduler.py::build_scheduler`) — kein zweiter Compose-Service, keine zweite Healthcheck-/Alert-Kette. |

**Design-Entscheidungen:**
- **Eigener, nicht geteilter Non-Fatal-Job-Vertrag:** `src/ingestion/scheduler.py`
  bekommt seinen eigenen `_consecutive_failures`-Zähler + Telegram-Alert-Pfad,
  statt den aus `src/orchestrator/scheduler.py` zu refaktorieren. Grund: die
  F029-Tests (`tests/orchestrator/test_scheduler.py`) greifen direkt auf
  `_consecutive_failures` und `_run_cycle_job`s exakten Log-Aufruf zu — ein
  gemeinsamer Helper hätte dieses gut getestete, laufende Modul anfassen
  müssen für ca. 15 Zeilen gesparte Duplikation. Bewusste Abweichung von der
  ursprünglichen Plan-Skizze, nach Lektüre der bestehenden Tests.
- **Dynamische Watchlist per neuem `resolve_symbol_universe`-Helper**
  (`src/orchestrator/symbol_universe.py`): Vereinigung aus statischer
  Seed-Liste, den *aktuell* offenen Positionen (letzter `position_snapshot` je
  Portfolio — nicht jedes je gehaltene Instrument, das würde nur wachsen) und
  den Symbolen des letzten `screener_result`-Laufs. Wird auch von F036
  (Indikatoren) wiederverwendet.
- **`run_daily_sync` bekommt einen optionalen `watchlist_override`-Parameter**
  (Default `None` = bestehendes Verhalten, liest die statische YAML-Liste) —
  minimal-invasive, rückwärtskompatible Erweiterung statt einer neuen
  Parallel-Funktion.
- **Zeiten:** VULTURE-Screener 06:00, Markt-Bar-Sync 06:30 (America/New_York,
  vor dem ersten Aktien-Zyklus C1 09:00 ET), EDGAR alle 30 Minuten (kein
  Börsenbezug nötig) — in `config/ingestion.yaml`s neuem `schedule:`-Block,
  analog zur bestehenden `config/cycles.yaml`-Konvention.

**Kosten:** keine LLM-Calls. **Fairness:** unverändert, siehe oben.

## 3. Testdefinition

`tests/ingestion/test_scheduler.py`:
1. `register_ingestion_jobs` registriert genau die 3 erwarteten Job-IDs.
2. Screener-/Markt-Bar-Jobs laufen in `America/New_York`.
3. Ein einzelner Fehlschlag alarmiert nicht.
4. Der zweite Fehlschlag in Folge löst genau einen Telegram-Alert mit
   Job-Label aus.
5. Ein Erfolg nach einem Fehlschlag setzt den Zähler zurück.

`tests/orchestrator/test_symbol_universe.py`:
1. Leere DB → nur die Seed-Watchlist.
2. Aktuell offene Position wird aufgenommen.
3. Eine veraltete Position (älterer Snapshot desselben Portfolios) wird nicht
   aufgenommen, nur die jeweils letzte.
4. Nur die Symbole des *letzten* Screener-Laufs werden aufgenommen.
5. Dubletten über mehrere Quellen werden dedupliziert.

## 4. Implementierung

- `src/ingestion/scheduler.py` (neu): `register_ingestion_jobs`.
- `src/orchestrator/symbol_universe.py` (neu): `resolve_symbol_universe`.
- `src/ingestion/market_data_sync.py`: `run_daily_sync` bekommt
  `watchlist_override`; Docstring korrigiert.
- `src/ingestion/edgar_rss.py`, `src/ingestion/vulture_screener.py`:
  "Not wired..."-Docstrings korrigiert.
- `scripts/run_scheduler.py`: ruft `register_ingestion_jobs` nach
  `build_scheduler` auf.
- `config/ingestion.yaml`: neuer `schedule:`-Block.
- `docker-compose.yml`: `scheduler`-Service bekommt `EDGAR_USER_AGENT`.
- Kein Alembic-Migrations-Bedarf.

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 392 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Deployment: rsync + `docker compose build api scheduler` + `up -d`.
- Verifikation nach Deploy: SQL-Check, dass `edgar_filing`, `screener_result`,
  `market_bar` nach dem ersten geplanten Lauf tatsächlich neue Zeilen mit
  aktuellem `synced_at` bekommen (nicht nur beim nächsten manuellen Testlauf).
- **Rollback-Pfad:** `register_ingestion_jobs`-Aufruf in `run_scheduler.py`
  entfernen (ein Zeilen-Revert) — die drei `run_*`-Funktionen selbst bleiben
  unverändert aufrufbar für manuelle Läufe.
