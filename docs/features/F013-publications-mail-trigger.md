# F013 — Publications Mail-Trigger (n8n-Wiring)

Status: umgesetzt (Code + Workflow-Datei), n8n-Import und Live-Verifikation stehen bei Ralf aus
Datum: 2026-07-06
Phase: 3

## 1. Zieldefinition

P3-DoD-Punkt "n8n-IMAP-Trigger erkennt die Benachrichtigungs-Mail und stößt die
Pipeline an (mindestens Fallback-Aufforderung per Telegram; Playwright-Autodownload
darf nachgelagert reifen)" (ARCHITECTURE.md §3.5.1/§8).

Die Benachrichtigungs-Mails laufen bei Ralfs Haupt-Mailaccount auf (nicht bei einem
ATLAS-eigenen Postfach). Absender immer `no-reply@e.boersenmedien.com`, Betreff immer
mit `Neuer Inhalt - ` beginnend, drei Ausprägungen:

- `Neuer Inhalt - Euro am Sonntag 23/26` (Ausgabennummer wechselt wöchentlich)
- `Neuer Inhalt - BÖRSE ONLINE E-Paper` (konstant)
- `Neuer Inhalt - DER AKTIONÄR E-Paper` (konstant)

Jede Zeitschrift hat eine feste Übersichts-URL (neueste Ausgabe steht jeweils oben):

| Zeitschrift | Übersichts-URL |
|---|---|
| Der Aktionär | `https://konto.boersenmedien.com/produkte/abonnements/2778322/A-10510232/ausgaben` |
| Euro am Sonntag | `https://konto.boersenmedien.com/produkte/abonnements/2778324/A-10529198/ausgaben` |
| Börse Online | `https://konto.boersenmedien.com/produkte/abonnements/2778326/A-10510298/ausgaben` |

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Fallback-first (§3.5.1) | ja | Diese Iteration löst ausschließlich die Telegram-Fallback-Aufforderung aus — kein Playwright-Autodownload, kein Login gegen konto.boersenmedien.com. Reift explizit nachgelagert (P3-DoD-Wortlaut). |
| #6 Secrets nie im Repo | ja | `N8N_PUBLICATIONS_WEBHOOK_SECRET` aus Environment; im n8n-Workflow selbst als "HTTP Header Auth"-Credential hinterlegt (n8n verschlüsselt Credential-Werte in seinem eigenen Store, der Workflow-JSON-Export enthält nur eine Credential-**Referenz**, keinen Wert — siehe `n8n/publications-mail-trigger.json`). Ralfs Mail-IMAP-Zugangsdaten bleiben komplett in n8n's eigenem Credential-Store, kommen in diesem Repo nirgends vor (weder Code noch `.env`). |
| Kein Login-Code für konto.boersenmedien.com in diesem Repo | ja | Absichtlich — dafür bräuchte es Ralfs Boersenmedien-Zugangsdaten, die nicht ohne Rückfrage angelegt werden (Memory-Regel). Diese Iteration braucht sie nicht: die Übersichts-URLs sind öffentlich bekannt (Ralf hat sie geliefert), der Download bleibt manuell. |
| Alerts ausschließlich per Telegram (ARCHITECTURE.md §6.4) | ja | `send_alert` nutzt exakt den bestehenden `TelegramConfig`/Bot-Mechanismus aus F005 — kein neuer Alert-Kanal (kein E-Mail-Versand von ATLAS aus). |
| Webhook-Endpoint auf dem LAN | ja | `POST /api/ingestion/publications/notify` prüft einen Shared-Secret-Header (`X-Webhook-Secret`) gegen `N8N_PUBLICATIONS_WEBHOOK_SECRET` — ohne das würde jeder im 192.168.178.0/24-Netz beliebige Telegram-Alerts auslösen können. Kein Auth-Overkill (kein OAuth/JWT nötig für einen einzelnen internen Webhook-Aufrufer), aber auch kein offener Endpoint. |

**Design-Entscheidungen:**
- **n8n bekommt nur den Betreff, keine Business-Logik:** die Zuordnung Betreff →
  Zeitschrift → Ablage-Pfad → Übersichts-URL lebt komplett in
  `src/ingestion/publications_notify.py` + `config/ingestion.yaml` (versioniert,
  getestet). Der n8n-Workflow bleibt absichtlich dünn (IMAP-Trigger → Filter → ein
  HTTP-Request-Node) — weniger Logik, die außerhalb von Git/Tests lebt.
- **`identify_magazine` per Substring-Match, nicht exakter Vergleich:** Euro am
  Sonntags Betreff trägt eine wechselnde Ausgabennummer
  (`Neuer Inhalt - Euro am Sonntag 23/26`), ein exakter Vergleich würde jede Woche
  brechen.
- **Der Webhook validiert den Betreff selbst nach** (nicht nur der n8n-Filter): ein
  502/422 bei unbekanntem Betreff ist ein klareres Signal für ein kaputtes
  Filter-Setup in n8n als ein stiller Fehlschlag.
- **Alert-Text enthält den vollen Ziel-Pfad** (`<PUBLICATIONS_INGEST_DIR>/<slug>/<Datum>.pdf`),
  exakt in der Konvention, die F011s Fallback-Pipeline erwartet — Ralf muss die Datei
  nur exakt dorthin legen, ohne nachzudenken, wohin.
- **`send_alert` als eigenständige Funktion statt über die `Application`:** die
  Telegram-`Application` aus F005 ist für Long-Running-Polling gebaut (Kommandos,
  HITL-Callbacks); ein einzelner Alert aus einem Webhook-Handler braucht nur einen
  `sendMessage`-Call, keinen laufenden Bot-Prozess.

**Kosten:** keine LLM-Calls. **Fairness:** betrifft nur Ingestion, keine Persona
bevorzugt.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests, kein echtes n8n/keine echte Mailbox nötig:

`tests/ingestion/test_publications_notify.py`:
1. `load_magazines` liest die drei echten Zeitschriften aus `config/ingestion.yaml`.
2. `identify_magazine` erkennt Euro am Sonntag trotz wechselnder Ausgabennummer.
3. `identify_magazine` erkennt Börse Online und Der Aktionär (konstante Betreffs).
4. `identify_magazine` ist case-insensitiv.
5. `identify_magazine` liefert `None` für einen unbekannten Betreff.
6. `format_fallback_alert` enthält Betreff, korrekten Ziel-Pfad und Übersichts-URL.

`tests/api/test_routes_ingestion.py`:
7. Fehlender `X-Webhook-Secret`-Header → `401`.
8. Falscher `X-Webhook-Secret`-Header → `401`.
9. Unbekannter Betreff (auch mit korrektem Secret) → `422`.
10. Bekannter Betreff + korrektes Secret → `202`, `send_alert` wird mit einer
    Nachricht aufgerufen, die den erkannten Zeitschriften-Slug enthält.

## 4. Implementierung

`src/ingestion/publications_notify.py` (`Magazine`, `load_magazines`,
`identify_magazine`, `format_fallback_alert`), `src/telegram/alerts.py`
(`send_alert`), `src/api/routes_ingestion.py` (`POST /api/ingestion/publications/notify`),
`src/api/app.py` (Router eingebunden), `config/ingestion.yaml`
(`publications`-Sektion), `.env`/`.env.example`
(`PUBLICATIONS_INGEST_DIR`, `N8N_PUBLICATIONS_WEBHOOK_SECRET`),
`n8n/publications-mail-trigger.json` (importierbarer n8n-Workflow-Export).

## 5. Testdurchlauf

`uv run pytest tests/ingestion/test_publications_notify.py tests/api/test_routes_ingestion.py -q`
→ 11 passed. `uv run pytest -q` (Gesamtsuite) → 241 passed, 2 deselected
(Integrationstests). `uv run ruff check`/`ruff format --check` → sauber.
`uv run mypy src/ingestion src/api src/telegram` → sauber.

**Noch offen (braucht Ralfs Mitwirkung in n8n selbst, nicht in diesem Repo lösbar):**
1. `n8n/publications-mail-trigger.json` in Ralfs n8n-Instanz importieren
   (`ix-n8n-*`-Stack auf der UGREEN, siehe `docs/deployment.md`).
2. Im importierten Workflow eine **IMAP-Credential** für Ralfs Hauptmailaccount
   anlegen und dem IMAP-Trigger-Node zuweisen.
3. Eine **HTTP-Header-Auth-Credential** ("ATLAS Webhook Secret", Header-Name
   `X-Webhook-Secret`, Wert = `N8N_PUBLICATIONS_WEBHOOK_SECRET` aus `.env`) anlegen
   und dem HTTP-Request-Node zuweisen.
4. Workflow aktivieren, mit einer echten (oder erneut zugestellten) Benachrichtigungs-
   Mail live verifizieren — Telegram-Alert muss ankommen.
5. **Playwright-Autodownload** (Login bei konto.boersenmedien.com) bleibt bewusst
   spätere Arbeit (Fallback-first, siehe Abschnitt 2).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert (neuer Router, neue Datei,
keine Schema-Änderung). Rollback = Commit zurücknehmen; auf n8n-Seite reicht
Deaktivieren/Löschen des importierten Workflows, keine Datenmigration nötig.
