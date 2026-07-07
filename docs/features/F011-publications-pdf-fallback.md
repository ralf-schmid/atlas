# F011 — Publications PDF-Fallback-Pipeline

Status: teilweise umgesetzt (Fallback-Kernpfad fertig, n8n-/Mail-Wiring offen)
Datum: 2026-07-05
Phase: 3

## 1. Zieldefinition

P3-DoD-Punkt "PDF-Fallback: manuell abgelegte Ausgabe wird binnen 5 Min erkannt,
geparst, segmentiert → `staging.publication_article` mit Titel/Ausgabe/Seite je
Artikel" (ARCHITECTURE.md §3.5.1/§8). Der Fallback wird **zuerst** gebaut, die
Playwright-Login-Automatisierung reift danach — der Agenten-Betrieb hängt nie am
fragilsten Glied (Paywall-Login).

Dieses Feature liefert den Kernpfad: ein bereits im Ingest-Verzeichnis liegendes PDF
erkennen (Verzeichnis-Scan), parsen (PyMuPDF), in Artikel segmentieren, idempotent in
`publication_article` schreiben. Das eigentliche n8n-File-Watcher-Trigger-Wiring auf
der UGREEN sowie die IMAP-Benachrichtigungs-Erkennung sind **nicht** Teil dieses
Commits — siehe Abschnitt 5 "Noch offen".

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| "Zeitschriften-/aktienfinder-Volltexte in UI oder Repo bringen" verboten (CLAUDE.md, "Was Claude Code NICHT tun darf") | ja | `publication_article.text` enthält vollen Artikeltext — das ist nötig, damit Recherche-Agenten (P4) den Inhalt lesen können ("Agenten lesen ausschließlich aus der DB"). Die Einschränkung gilt für **UI und Repo**, nicht für die DB selbst; die API/UI-Schicht (nicht Teil dieses Features) muss beim Ausliefern auf Zusammenfassung + Quellenverweis reduzieren. Im Repo landen nur Code + Test-Fixtures (synthetische PDFs, keine echten Abo-Inhalte). |
| #9 Untrusted Content (Prompt Injection) | ja | Extrahierter Artikeltext ist Fremdinhalt. Diese Ingestion schreibt ihn nur strukturiert in eine Staging-Tabelle; die Anbindung an Agenten mit Schreibrechten (die ihn als getaggten Datenblock, nie im System-Prompt, bekommen müssen) ist P4-Arbeit. |
| Idempotenz aller Ingestion-Jobs (P3-DoD Punkt 6) | ja | `sync_publication_articles` upsertet über `UniqueConstraint(publication, issue_date, seq)` — erneutes Verarbeiten derselben Datei (Crash-Recovery, manueller Re-Trigger) überschreibt, dupliziert nicht. |
| ToS/rechtlicher Rahmen (§3.5.1 Gotcha b) | ja | Nur Metadaten/Volltext-in-DB für private Auswertung, keine Weiterverbreitung — dieses Feature verändert daran nichts, hält sich an die vorgegebene Pipeline. |

**Design-Entscheidungen:**
- **PyMuPDF statt Docling:** leichtgewichtiger (keine zusätzliche ML-Pipeline nötig),
  reicht für Text + Font-Größen-Extraktion. Docling bleibt eine spätere Option, falls
  die Segmentierung mehr Layout-Verständnis braucht (siehe Heuristik-Grenze unten).
- **Artikel-Segmentierung per Font-Größen-Heuristik:** eine Text-Span, deren Größe
  deutlich über dem Seiten-Median liegt (Faktor `_HEADLINE_SIZE_RATIO = 1.3`), markiert
  eine neue Überschrift; alles bis zur nächsten Überschrift ist der Artikeltext. Das ist
  bewusst eine einfache Heuristik, kein vollständiges Layout-Verständnis — ausreichend
  für den Fallback-Pfad, austauschbar (z. B. gegen Docling) ohne Schema-/Sync-Änderung.
  **Grenze:** funktioniert zuverlässig, wenn Artikel-Fließtext den Median klar
  dominiert (typisch für eine Zeitschriftenseite); bei Seiten mit wenigen, kurzen
  Textblöcken kann die Heuristik fehlschlagen (im Test explizit dokumentiert: das
  Test-Fixture braucht mehr Fließtext- als Überschriftzeilen, sonst kippt der Median).
- **Verzeichnis-Konvention `<base_dir>/<publikation>/<YYYY-MM-DD>.pdf`**: liefert
  Publikation + Ausgabedatum ohne zusätzliche Metadaten-Datei — einfach und robust für
  den manuellen Fallback (Ralf legt die Datei einfach in den richtigen Unterordner).
- **`scan_ingest_directory`** ist eine reine Auflist-Funktion, kein eigener
  Datei-Watcher-Prozess — das eigentliche "binnen 5 Minuten erkannt" braucht einen
  Scheduler/Poller (n8n File-Watcher oder ein einfacher Cron), der diese Funktion
  aufruft. Idempotenz von `process_pdf_fallback_file` macht wiederholtes Scannen
  ungefährlich.

**Kosten:** keine LLM-Calls. **Fairness:** ein Parse-Pfad, ein Ergebnis-Datensatz für
alle Personas (die Zeitschriften-Artikel selbst sind ohnehin plattformweit dieselben).

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/ingestion/test_publications_pipeline.py`), Test-PDFs werden mit
PyMuPDF selbst synthetisch erzeugt (keine echten Abo-Inhalte im Repo):

1. `extract_articles` segmentiert eine zweiseitige Test-PDF korrekt anhand der
   Font-Größen-Heuristik (zwei Artikel, Titel + Fließtext getrennt).
2. `extract_articles` liefert `[]` für eine leere Seite (kein Crash).
3. `parse_issue_path` extrahiert Publikation + Ausgabedatum aus dem
   Verzeichnis-Pfad.
4. `parse_issue_path` wirft `ValueError` bei falschem Dateinamen-Format.
5. `parse_issue_path` wirft `ValueError` bei falscher Verzeichnistiefe.
6. `sync_publication_articles` mit leerer Liste → `0`.
7. `sync_publication_articles` zweimal mit unterschiedlichem Inhalt für denselben
   `(publication, issue_date, seq)` → genau eine Zeile, mit den Werten des zweiten
   Laufs (Idempotenz-Nachweis).
8. `process_pdf_fallback_file` Ende-zu-Ende: PDF → 2 Artikel in der DB; erneuter
   Aufruf auf derselben Datei dupliziert nicht.
9. `scan_ingest_directory` findet PDFs über mehrere Publikations-Unterordner hinweg.
10. `scan_ingest_directory` liefert `[]`, wenn das Verzeichnis noch nicht existiert.

## 4. Implementierung

`src/ingestion/publications_pipeline.py` (`Article`, `extract_articles`,
`parse_issue_path`, `sync_publication_articles`, `process_pdf_fallback_file`,
`scan_ingest_directory`), `src/db/models.py` (`PublicationArticle`), Migration
`alembic/versions/b7876aca814a_add_publication_article.py`. Neue Dependency
`pymupdf` (+ gezielte mypy-Ausnahme `disallow_untyped_calls = false` nur für dieses
Modul, da PyMuPDFs `Document`-Konstruktor keine vollständigen Typannotationen hat).

## 5. Testdurchlauf

`uv run pytest tests/ingestion -q` → 34 passed (24 aus F008–F010 + 10 aus F011).
`uv run pytest -q` (Gesamtsuite) → 220 passed. `uv run ruff check`/`ruff format --check`
→ sauber. `uv run mypy src/ingestion` → sauber. Migration im
upgrade→downgrade→upgrade-Zyklus verifiziert (keine ENUM-Typen in dieser Tabelle).

**Update 2026-07-07 — Host-Verzeichnis + manueller Trigger nachgezogen:** n8n-IMAP-Trigger
und der API-Webhook (F013) waren bereits live, aber `PUBLICATIONS_INGEST_DIR` war nur ein
Env-Wert für den Telegram-Nachrichtentext — kein Docker-Volume band ihn an einen
tatsächlich erreichbaren Ort auf der Box, und nichts rief `scan_ingest_directory`/
`process_pdf_fallback_file` je auf (echte Lücke, aufgefallen als Ralf die erste reale
Benachrichtigung bekam und die PDF ablegen wollte). Behoben:
- `docker-compose.yml`: `api`-Service bindet `./data/ingest/publications` (host-persistent,
  `.gitignore`d, übersteht Redeploys) an `/data/ingest/publications` im Container.
- `scripts/ingest_publications.py`: manueller Trigger (analog `scripts/run_cycle.py`),
  scannt das Verzeichnis und verarbeitet alle gefundenen PDFs, idempotent.
- Lokal Ende-zu-Ende gegen echte (migrierte) Test-Postgres verifiziert: synthetische PDF
  abgelegt, Skript zweimal gelaufen (1 Artikel, keine Duplikate).
- **Mit einer echten (nicht synthetischen) "Der Aktionär"-Ausgabe von Ralf verifiziert:**
  Download → `scp` ins Verzeichnis → `scripts/ingest_publications.py` → Artikel korrekt
  in `publication_article` gelandet. Der zuvor offene Praxistest-Punkt ist damit erledigt.

**Noch offen — vollautomatischer Ablauf (Ralf möchte künftig keinen manuellen Schritt
mehr):** aktuell macht Ralf nach der Telegram-Benachrichtigung drei Dinge von Hand
(PDF herunterladen, per `scp` ins Verzeichnis legen, `scripts/ingest_publications.py`
manuell ausführen). Ziel: alle drei Schritte automatisch, ausgelöst durch dieselbe
n8n-Benachrichtigung, die heute nur die Telegram-Fallback-Nachricht schickt.
- **Playwright-Auto-Download + Ablage** (Login bei konto.boersenmedien.com, PDF
  herunterladen, direkt unter `<base_dir>/<slug>/<issue_date>.pdf` ablegen — F011s
  Verzeichniskonvention bleibt gültig, nur die Quelle wechselt von "Ralf" zu
  "Playwright"). Braucht Zugangsdaten-Freigabe von Ralf (keine Credentials ohne
  Absprache anlegen).
- **Automatischer Trigger für die Verarbeitung** nach erfolgtem Download/Ablage —
  entweder direkt am Ende des Auto-Download-Skripts (`process_pdf_fallback_file`
  aufrufen) oder als separater Poller (n8n File-Watcher/Cron auf
  `scan_ingest_directory`, deckt auch den Fall ab, dass doch mal jemand manuell eine
  PDF ablegt). Erfüllt nebenbei den offenen P3-DoD-Punkt "binnen 5 Min erkannt".
- Der heutige manuelle Fallback (Verzeichniskonvention, `scripts/ingest_publications.py`,
  Idempotenz) bleibt unverändert bestehen und dient danach nur noch als Rückfalloption,
  falls der Auto-Download fehlschlägt (Login-Änderung, Layout-Wechsel etc.).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert. Rollback = Commit
zurücknehmen + `alembic downgrade -1` (getestet, s. o.).
