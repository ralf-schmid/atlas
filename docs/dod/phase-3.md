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
- [x] n8n-IMAP-Trigger erkennt die Benachrichtigungs-Mail und stößt die Pipeline an
      (mindestens Fallback-Aufforderung per Telegram)
      **Nachweis:** [F013](../features/F013-publications-mail-trigger.md) — Workflow
      in Ralfs n8n-Instanz importiert, IMAP- und Webhook-Secret-Credentials angelegt,
      2026-07-06 live mit einer echten Benachrichtigungs-Mail getestet: Telegram-Alert
      kam an. **Erweiterung** [F014](../features/F014-musterdepot-transactions.md):
      zweiter Mail-Typ (DER AKTIONÄR-Musterdepot-Transaktionen, Absender
      `noreply@boersenmedien.de`, Betreff "Neue Transaktion") als zweiter Workflow-
      Zweig ergänzt, Regex-Parser + eigene Tabelle `musterdepot_transaction`, Endpoint
      per Smoke-Test auf der UGREEN mit der echten Beispielmail verifiziert; n8n-Import
      inkl. Fix eines Feldnamen-Fehlers (`$json.metadata['message-id']` statt
      `$json.messageId`) ebenfalls live verifiziert — Workflow läuft durchgängig
      (2026-07-06).
- [ ] aktienfinder-Grabbing liefert für 10 Testtitel strukturierte Snapshots +
      Beleg-Screenshot, täglich per Schedule
      **Teilweise:** [F012](../features/F012-aktienfinder-grabbing.md) — Login +
      Extraktion + Persistenz sind live gegen Ralfs echtes aktienfinder.net-Konto
      verifiziert: 10 echte Symbole (Apple, SAP am 2026-07-05; Microsoft,
      Coca-Cola, Johnson & Johnson, Nestlé, Siemens, Allianz, Procter & Gamble,
      BASF am 2026-07-07, über US/CH/DE gestreut), je ein echter Screenshot.
      **10-Testtitel-Nachweis damit vollständig.** **Offen:** kein Scheduler,
      daher noch kein täglicher Live-Lauf — kommt planmäßig mit P4.
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
2. **8 weitere Testtitel** für den vollen aktienfinder-10-Titel-Nachweis (aktuell 2
   verifiziert) — reine Wiederholung, kein neues Risiko, aber noch nicht gemacht.
3. **Grafana-Freshness-Panel** für den 5-Tage-Nachweis — braucht Punkt 1 zuerst.

**Update (2026-07-06):** n8n-IMAP-Trigger (F013) und die Musterdepot-Erweiterung
(F014) sind beide live verifiziert — beide Punkte aus der DoD-Liste oben abgehakt.
Phase 3 bleibt bis zu den drei verbleibenden Punkten offen (alle drei brauchen einen
Scheduler, der planmäßig erst mit P4 kommt).

**Update (2026-07-07):** Zwei der drei offenen Punkte final geklärt, bevor P4 startet:
1. **aktienfinder 10-Testtitel-Nachweis komplett** — 8 weitere reale ISINs live gegen
   Ralfs Konto verifiziert (siehe F012). Verbleibt nur noch der Scheduler.
2. **Telegram-Fallback-Pfad direkt verifiziert** — der ursprüngliche Magazin-Zweig
   (nicht nur der Musterdepot-Zweig) wurde per echtem Webhook-Call gegen
   `atlas-api-1` auf der UGREEN ausgelöst, Ralf hat den Erhalt der Telegram-Nachricht
   bestätigt (siehe F013).

**Alle drei verbleibenden P3-DoD-Punkte hängen jetzt ausschließlich am Scheduler**
(täglicher aktienfinder-/Screener-Lauf, 5-Tage-Dauerlauf EDGAR/Marktdaten,
PDF-Fallback-Poller binnen 5 Min). Der Scheduler ist planmäßig Teil von P4
(LangGraph-Zyklen); Phase 3 wird formal mit P4 zusammen abgeschlossen, sobald der
Scheduler steht und die drei Punkte damit nachweisbar sind — kein separater
P3-Abschluss davor.
