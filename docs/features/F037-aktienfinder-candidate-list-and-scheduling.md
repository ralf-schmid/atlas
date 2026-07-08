# F037 — aktienfinder-Kandidatenliste + Playwright-Aktivierung

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

GUARDIANs erster Live-Zyklus: keine Fair-Value-/Qualitäts-Daten im Pool,
obwohl "genau die vermissten Informationen über aktienfinder erreichbar"
sind (Ralfs Beobachtung). Zwei Ursachen bestätigt: (1) `run_daily_grab_live`
(F012) lief nie automatisiert, nur einmal manuell verifiziert; (2) selbst
geschedult hätte es keine Ziel-ISINs — es gibt keine Konfiguration, welche
Aktien für aktienfinder überhaupt abgefragt werden sollen. Zusätzlich entdeckt:
`Dockerfile.api` installiert das Python-Package `playwright`, nie die
Browser-Binary — Playwright-Code würde in Produktion sofort crashen.

**Scope:** statische, Ralf-gepflegte ISIN-Kandidatenliste, ein
Konfigurations-Wrapper der sie an `run_daily_grab_live` (F012) delegiert,
Einhängen in den Ingestion-Scheduler (F035), Playwright-Binary-Fix im
Dockerfile. **Non-Scope:** ein echter Fundamental-Screener (siehe
Design-Entscheidungen).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Ein Sync-Pfad, ein gemeinsamer `aktienfinder_snapshot`-Datensatz, unverändert gegenüber F012 — nur jetzt tatsächlich befüllt. |
| #6 Secrets nie im Repo | ja | `AKTIENFINDER_USERNAME`/`_PASSWORD`/`_SCREENSHOT_DIR` (existieren schon in `.env.example`) werden `docker-compose.yml`s `scheduler`-Service ergänzt. |

**Design-Entscheidungen:**
- **MVP: statische ISIN-Liste statt echtem Fundamental-Screener.** Ein
  dynamischer Screener (Dividendenkontinuität, >10 Jahre Gewinnhistorie,
  flächendeckend) bräuchte einen kostenpflichtigen Fundamentaldaten-Anbieter —
  unverhältnismäßig zum Ziel "GUARDIAN bekommt überhaupt Daten". Stattdessen:
  `config/ingestion.yaml`s `aktienfinder.candidate_isins` (6 bekannte
  Qualitätswerte als Startpunkt), von Ralf manuell gepflegt. **Kein Mechanismus
  erweitert diese Liste automatisch** — bewusst, siehe Rollout-Hinweis unten.
  Falls Ralf später Zugriff auf einen Fundamentaldaten-Anbieter hat, ist das
  der Auslöser, diese Entscheidung zu revidieren.
- **`run_daily_grab_configured`** (neuer, dünner Wrapper) lädt
  `candidate_isins` und delegiert an das bereits fertige
  `run_daily_grab_live(session, isins, snapshot_date)` — keine Änderung an der
  eigentlichen Grabbing-Logik.
- **Playwright-Fix vor dem `USER`-Wechsel im Dockerfile** (`--with-deps`
  braucht Root für apt-Installationen der Systemabhängigkeiten). Vergrößert das
  Image spürbar (Chromium + Linux-Abhängigkeiten) — akzeptierter Preis, es gibt
  keine Alternative, solange Playwright-basierte Ingestion läuft.
- **Scheduling um 07:00 America/New_York** (nach Screener 06:00 und
  Markt-Bar-Sync 06:30, vor dem ersten Aktien-Zyklus 09:00 ET).

**Kosten:** keine LLM-Calls. **Fairness:** unverändert.

## 3. Testdefinition

`tests/ingestion/test_aktienfinder_grabbing.py`:
1. `run_daily_grab_configured` liest `candidate_isins` aus der Config und
   ruft `run_daily_grab_live` mit genau dieser Liste + dem `snapshot_date` auf.

`tests/ingestion/test_scheduler.py`:
1. `register_ingestion_jobs` registriert jetzt 4 statt 3 Jobs (inkl.
   `ingestion-aktienfinder`).
2. Ein Fehlschlag zweimal in Folge alarmiert mit dem Job-Label
   "aktienfinder-Snapshot" (gleicher Non-Fatal-Vertrag wie die anderen 3
   Jobs, F035).

Der Dockerfile-Fix selbst ist nicht pytest-testbar — Verifikation ist ein
manueller Build-Schritt (siehe Test & Rollout).

## 4. Implementierung

- `config/ingestion.yaml`: `aktienfinder.candidate_isins` (6 ISINs),
  `schedule.aktienfinder.time: "07:00"`.
- `src/ingestion/aktienfinder_grabbing.py`: `run_daily_grab_configured`.
- `src/ingestion/scheduler.py`: `_aktienfinder_job` + Registrierung.
- `Dockerfile.api`: `RUN uv run playwright install --with-deps chromium` vor
  dem `USER`-Wechsel.
- `docker-compose.yml`: `scheduler`-Service bekommt
  `AKTIENFINDER_USERNAME`/`_PASSWORD`/`_SCREENSHOT_DIR` + einen
  Screenshot-Volume-Mount (`./data/ingest/aktienfinder/screenshots`, analog
  zum bestehenden Publications-Volume).
- Kein Alembic-Migrations-Bedarf.

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 410 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Deployment: rsync + `docker compose build api scheduler` + `up -d` — Build-Log
  muss den `playwright install`-Schritt zeigen (Chromium-Download).
- Verifikation nach Deploy: `aktienfinder_snapshot` bekommt nach dem ersten
  geplanten Lauf (07:00 ET) neue Zeilen für die 6 konfigurierten ISINs.
- **Ops-Hinweis:** `candidate_isins` wird von nichts automatisch erweitert —
  Ralf sollte die Liste gelegentlich überprüfen/ergänzen.
- **Rollback-Pfad:** `ingestion-aktienfinder`-Job-Registrierung aus
  `register_ingestion_jobs` entfernen (Zeilen-Revert). Der Playwright-Fix im
  Dockerfile sollte bestehen bleiben, auch falls der Job deaktiviert wird (kein
  Nachteil, nur zusätzliche Image-Größe).
