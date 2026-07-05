# Phase 3 — Ingestion: Definition of Done

Checkliste aus ARCHITECTURE.md §8.

**Status:** in Arbeit, nicht abgeschlossen. Alle sechs Ingestion-Bausteine (F008–F012)
sind implementiert, unit-getestet und idempotent — aber mehrere DoD-Punkte verlangen
ausdrücklich einen **laufenden Live-Betrieb** (5 Handelstage unterbrechungsfrei, echte
Zugangsdaten, ein Scheduler) und lassen sich daher nicht aus dem Editor heraus
abhaken. Diese Punkte bleiben bewusst offen, bis der entsprechende Live-Nachweis
vorliegt — kein Punkt wird ohne echten Nachweis auf `[x]` gesetzt.

- [ ] PDF-Fallback: manuell abgelegte Ausgabe wird binnen 5 Min erkannt, geparst,
      segmentiert → `staging.publication_article` mit Titel/Ausgabe/Seite je Artikel
      **Teilweise:** [F011](../features/F011-publications-pdf-fallback.md) —
      Parsing/Segmentierung/Persistenz fertig und gegen synthetische Test-PDFs
      verifiziert (10 Tests grün). **Offen:** kein Nachweis gegen eine echte
      Zeitschriften-PDF (Layout von Euro am Sonntag/Börse Online/Der Aktionär
      ungeprüft); kein laufender Poller/Watcher, der "binnen 5 Min" tatsächlich
      erfüllt — `scan_ingest_directory` existiert, ist aber nirgends geplant.
- [ ] n8n-IMAP-Trigger erkennt die Benachrichtigungs-Mail und stößt die Pipeline an
      **Offen:** nicht begonnen. Braucht Ralfs Mail-Zugangsdaten/IMAP-Konfiguration
      auf der UGREEN — wird nicht ohne Rückfrage angelegt (siehe Memory-Regel "keine
      neuen Zugangsdaten ohne Rückfrage").
- [ ] aktienfinder-Grabbing liefert für 10 Testtitel strukturierte Snapshots +
      Beleg-Screenshot, täglich per Schedule
      **Teilweise:** [F012](../features/F012-aktienfinder-grabbing.md) —
      Extraktions-/Persistenz-Kernpfad fertig und gegen eine Fake-Page verifiziert (6
      Tests grün). **Offen:** keine echte Playwright-Session/Login (braucht Ralfs
      aktienfinder.de-Zugangsdaten), echte CSS-Selektoren unbekannt (Platzhalter in
      `config/ingestion.yaml`), daher kein Nachweis mit 10 echten Testtiteln.
- [ ] EDGAR-RSS + Marktdaten-Sync laufen 5 Tage unterbrechungsfrei
      (Grafana-Freshness-Panel als Nachweis)
      **Teilweise:** [F008](../features/F008-marktdaten-sync.md)/
      [F009](../features/F009-edgar-rss.md) — Sync-Logik fertig, idempotent,
      unit-getestet (16 Tests grün). **Offen:** kein Scheduler deployt (P4/Ops-Task),
      damit kein 5-Tage-Dauerlauf und kein Grafana-Freshness-Panel möglich. Zusätzlich
      fehlt `EDGAR_USER_AGENT` mit Ralfs echten Kontaktdaten für den Live-Poll gegen
      sec.gov.
- [ ] VULTURE-Screener liefert täglich eine Kandidatenliste mit definierten Feldern
      **Teilweise:** [F010](../features/F010-vulture-screener.md) — Screener-Logik
      fertig, idempotent, unit-getestet (8 Tests grün). **Offen:** kein Scheduler,
      damit noch kein täglicher Live-Lauf gegen das echte Alpaca-Universum.
- [x] Alle Ingestion-Jobs idempotent — doppelte Trigger erzeugen keine Duplikate
      (Unique Constraints, im Test nachgewiesen)
      **Nachweis:** je ein expliziter Re-Run-Test pro Job gegen echtes (lokales)
      Postgres: `test_sync_market_bars_upserts_on_rerun_without_duplicates` (F008),
      `test_sync_edgar_filings_is_idempotent_on_rerun` (F009),
      `test_sync_screener_results_inserts_and_is_idempotent_on_rerun` (F010),
      `test_sync_publication_articles_is_idempotent_on_rerun` +
      `test_process_pdf_fallback_file_end_to_end` (F011),
      `test_sync_aktienfinder_snapshots_is_idempotent_on_rerun` (F012). Jede der fünf
      neuen Tabellen (`market_bar`, `edgar_filing`, `screener_result`,
      `publication_article`, `aktienfinder_snapshot`) trägt den entsprechenden
      `UniqueConstraint`, durchgesetzt per `ON CONFLICT DO UPDATE`/`DO NOTHING`.

## Zusammenfassung (Stand 2026-07-05)

40 neue Tests in `tests/ingestion/` (226 insgesamt im Repo), `ruff`/`mypy` sauber,
fünf Alembic-Migrationen im upgrade→downgrade→upgrade-Zyklus verifiziert. Jeder
Baustein folgt demselben Muster: Provider-Protocol (testbar ohne echten
externen Aufruf), reine Sync-/Persistenz-Funktion, config-getriebener
`run_*`-Einstiegspunkt.

**Strukturell offen, nicht in dieser Session lösbar:**
1. **Scheduler/Orchestrator** für alle fünf `run_*`-Funktionen — kommt planmäßig mit
   P4 (LangGraph-Zyklen) oder einer Cron-Übergangslösung auf der UGREEN.
2. **Drei fehlende Zugangsdaten-Sets** (Ralf): `EDGAR_USER_AGENT` (echte
   Kontaktdaten für sec.gov), Mail/IMAP-Zugang für den n8n-Trigger,
   aktienfinder.de-Login für Playwright. Keines davon wurde ohne Rückfrage angelegt.
3. **Echte aktienfinder.de-Selektoren** — brauchen eine eingeloggte Session zum
   Inspizieren, die es noch nicht gibt.
4. **Live-Dauerläufe** (5 Handelstage, 10 Testtitel) sind per Definition erst nach
   Punkt 1+2 möglich.

Phase 3 bleibt bis zu diesen vier Punkten offen. Die nächsten sinnvollen Schritte:
Ralf entscheidet, ob/wann die drei Zugangsdaten-Sets kommen, und ob ein einfacher
Cron auf der UGREEN als Zwischenlösung reicht, bis der P4-Orchestrator steht.
