# F130 — Automatisierten Seitenzugriff abschalten (aktienfinder, Börsenmedien)

Status: implementiert, ATLAS ist stillgelegt (seit 17.10.2026)
Datum: 2026-11-02
Phase: Stilllegung nach Saison 1
Auslöser: aktienfinder.net hat Ralf mitgeteilt, dass der programmatische Zugriff auf
die Webseite nicht erlaubt ist.

## 1. Zieldefinition

Kein Job in der ausgelieferten Konfiguration darf aktienfinder.net oder
konto.boersenmedien.com automatisiert aufrufen. Das gilt auch dann, wenn der Stack
versehentlich wieder hochfährt, etwa durch ein `docker compose up -d` nach einem
Rebuild.

Betroffen sind:

- `ingestion-aktienfinder-blog` (05:30 ET, HTTP-Abruf der Artikellisten)
- `ingestion-aktienfinder-screener-discovery` (06:15 ET, Login und Screener-Raster per Playwright)
- `ingestion-aktienfinder` (07:00 ET, Login, Profil- und Dividendenseiten, Screenshots)
- `ingestion-publications-session-check` (montags, startet einen Browser gegen Börsenmedien)
- der Auto-Download der Hefte im `api`-Webhook (F078), ausgelöst über n8n

## 2. Kritische Betrachtung

- **Invarianten:** keine berührt. Risk-Gate, Orders und HITL bleiben unverändert.
- **Fairness (Invariante 10):** Die drei aktienfinder-Quellen fehlen allen Personas
  gleichermaßen. GUARDIAN und CONTRA verlieren damit ihre Kernquelle (Charter nennt
  aktienfinder.net). Für eine neue Saison muss das vorher geklärt werden, die Charter
  bleiben hier unverändert (kein `charter_version`-Bump, weil ATLAS nicht läuft).
- **Fail-closed:** Bei reddit und alpaca_* bedeutet ein fehlender `enabled`-Schalter
  „an". Bei den aktienfinder-Jobs bedeutet er „aus" (`_aktienfinder_enabled`). Eine
  ältere Konfiguration ohne Schalter startet das Scraping also nicht wieder.
- **Kosten:** keine.

## 3. Testdefinition (vor der Umsetzung)

In `tests/ingestion/test_scheduler.py`:

- Die ausgelieferte Konfiguration registriert keinen der vier Seitenzugriffs-Jobs.
- Jeder aktienfinder-Job wird nur mit `enabled: true` registriert.
- Fehlt der Schalter, bleibt jeder aktienfinder-Job aus.
- `publications.auto_download` ist in der ausgelieferten Konfiguration `false`.
- Die Tests des Session-Checks schalten den Job für ihren Fall ausdrücklich ein.

## 4. Implementierung

- `src/ingestion/scheduler.py`: Die drei aktienfinder-Jobs werden nur registriert, wenn
  `_aktienfinder_enabled(schedule[...])` wahr ist.
- `config/ingestion.yaml`: `enabled: false` für die drei aktienfinder-Jobs und für
  `publications_session_check`, `auto_download: false`.

## 5. Testdurchlauf

Lokal gegen Postgres 16 mit pgvector: `pytest tests/` mit 1288 bestandenen Tests,
Abdeckung 92 %. `ruff check`, `ruff format --check` und `mypy src` ohne Befund.

## 6. Livesetzung

Keine. ATLAS bleibt stillgelegt (`docker compose stop`, Stand 02.11.2026 geprüft: alle
sechs Container angehalten, seit 28.10. keine aktienfinder-Einträge im Scheduler-Log).
Die Änderung greift beim nächsten Image-Build. Wird der Stack wieder gestartet, sind
die Seitenzugriffe ab dann aus.

## 7. Rollback

In `config/ingestion.yaml` die betreffenden Schalter wieder auf `true` setzen und das
Image neu bauen. Nur nach Klärung mit aktienfinder bzw. Börsenmedien.
