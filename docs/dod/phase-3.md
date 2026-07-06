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
      **Teilweise:** [F013](../features/F013-publications-mail-trigger.md) — Code-Seite
      fertig und getestet (Zeitschriften-Erkennung, Telegram-Fallback-Text,
      geschützter Webhook), importierbarer n8n-Workflow
      (`n8n/publications-mail-trigger.json`) liegt bereit. **Offen:** Workflow muss
      noch in Ralfs n8n-Instanz importiert werden, IMAP-Credential (Ralfs
      Hauptmailaccount) + HTTP-Header-Auth-Credential (Webhook-Secret) müssen dort
      angelegt werden — beides bewusst nicht von mir eingerichtet (n8n-eigener
      Credential-Store, kein Zugriff/keine Zugangsdaten von hier aus). Noch kein
      Live-Nachweis mit einer echten (erneut zugestellten) Benachrichtigungs-Mail.
- [ ] aktienfinder-Grabbing liefert für 10 Testtitel strukturierte Snapshots +
      Beleg-Screenshot, täglich per Schedule
      **Teilweise:** [F012](../features/F012-aktienfinder-grabbing.md) — Login +
      Extraktion + Persistenz sind live gegen Ralfs echtes aktienfinder.net-Konto
      verifiziert (2026-07-05): echter Login, echte Selektoren (Kurs, ISIN,
      Dividendenrendite, drei Qualitäts-Scores, Dividenden-Historie-Tabelle),
      2 echte Symbole (Apple, SAP), 2 echte Screenshots. **Offen:** nur 2 von 10
      Testtiteln live verifiziert (Selektoren sind aber nachweislich
      symbolübergreifend stabil); kein Scheduler, daher noch kein täglicher
      Live-Lauf.
- [ ] EDGAR-RSS + Marktdaten-Sync laufen 5 Tage unterbrechungsfrei
      (Grafana-Freshness-Panel als Nachweis)
      **Teilweise:** [F008](../features/F008-marktdaten-sync.md)/
      [F009](../features/F009-edgar-rss.md) — Sync-Logik fertig, idempotent,
      unit-getestet (16 Tests grün). EDGAR-Live-Poll gegen den echten sec.gov-Feed
      verifiziert (2026-07-05, echter `EDGAR_USER_AGENT`): 42 echte Filings korrekt
      geparst und persistiert. **Offen:** kein Scheduler deployt (P4/Ops-Task), damit
      kein 5-Tage-Dauerlauf und kein Grafana-Freshness-Panel möglich. Marktdaten-Sync
      selbst noch nicht live gegen echte Alpaca-Bars verifiziert (nur unit-getestet).
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

**Update (2026-07-05):** Ralf hat `EDGAR_USER_AGENT` und
`AKTIENFINDER_USERNAME`/`AKTIENFINDER_PASSWORD` eingetragen. Beide live verifiziert:
EDGAR-Feed liefert echte Filings, aktienfinder.net-Login + Extraktion funktionieren
gegen 2 echte Symbole (Details in F009/F012). Verbleibt strukturell offen:

1. **Scheduler/Orchestrator** für alle fünf `run_*`-Funktionen — kommt planmäßig mit
   P4 (LangGraph-Zyklen) oder einer Cron-Übergangslösung auf der UGREEN. Ohne
   Scheduler kein 5-Tage-Dauerlauf, kein täglicher aktienfinder-/Screener-Lauf.
2. **n8n-Workflow-Import** (F013): Code + Workflow-Datei liegen bereit
   (`n8n/publications-mail-trigger.json`), aber der Import selbst sowie das Anlegen
   der IMAP- und Webhook-Secret-Credentials passieren in Ralfs n8n-Instanz — kann
   nicht von hier aus erledigt werden.
3. **8 weitere Testtitel** für den vollen aktienfinder-10-Titel-Nachweis (aktuell 2
   verifiziert) — reine Wiederholung, kein neues Risiko, aber noch nicht gemacht.
4. **Grafana-Freshness-Panel** für den 5-Tage-Nachweis — braucht Punkt 1 zuerst.

Phase 3 bleibt bis zu diesen vier Punkten offen.
