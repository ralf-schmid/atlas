# F078 — Publications Auto-Download (Playwright, Session-basiert)

Status: in Umsetzung
Datum: 2026-07-22
Phase: 4 (löst den in Phase 3 bewusst vertagten Teil von ARCHITECTURE.md §3.5.1 ein)

## 1. Zieldefinition

Ralfs Auftrag: „Ich möchte keine Info, dass ich eine neue E-Mail erhalten habe und
diese selbst hochladen muss. Optimiere den Ablauf, dass automatisch die neue
PDF-Datei heruntergeladen wird und dann im korrekten Verzeichnis auf der UGREEN
abgelegt wird."

Damit wird die in ARCHITECTURE.md §3.5.1 beschriebene **Ziel-Pipeline** eingelöst,
die F013 explizit vertagt hatte (Fallback-first):

```
n8n IMAP-Trigger  →  ATLAS-Webhook  →  Playwright lädt PDF  →  /data/ingest/publications/<slug>/<YYYY-MM-DD>.pdf
                                                             →  PDF→Artikel-Pipeline (publication_article)
                                                             →  Telegram: Vollzugsmeldung
```

Zwei Lücken werden geschlossen, nicht nur eine:

1. **Der Download** war manuell (F013 schickte nur eine Telegram-Aufforderung).
2. **Die Verarbeitung** war *ebenfalls* manuell — auch eine korrekt abgelegte PDF
   landete nie in `publication_article`, solange niemand
   `scripts/ingest_publications.py` von Hand startete (F011 §5 „Noch offen": kein
   Poller, kein Cron). Ohne (2) wäre der Ablauf weiterhin halb-manuell und die
   Personas sähen die Ausgabe nicht.

**Nicht-Ziel:** kein täglicher Poll. Ralf hat sich bewusst für den reinen
Mail-Trigger entschieden — bleibt die Mail aus, bleibt der Download aus (bewusst
akzeptiertes Restrisiko, siehe §2).

## 2. Kritische Betrachtung

### 2.1 Live-Recherche am Portal (22.07.2026)

Vor dem Entwurf wurde die echte Portalstruktur in einer bereits angemeldeten
Browser-Session inspiziert (nur lesend, keine Downloads, keine Änderungen):

| Befund | Konsequenz |
|---|---|
| **Cloudflare Turnstile** schützt das Login-Formular (`login.boersenmedien.de`, verstecktes `TurnstileToken`-Feld, `cf-chl-widget-*`) | Automatisiertes Passwort-Login ist strukturell unzuverlässig. Bot-Schutz wird **nicht** umgangen — stattdessen einmalig gespeicherte Session (§2.2). Nebeneffekt: Ralfs Passwort muss nirgends in der `.env` liegen. |
| Nur **ein aktives Abo**: `DER AKTIONÄR E-Paper` (A-10546504). Euro am Sonntag und BÖRSE ONLINE sind nicht (mehr) aktiv | Der Job muss „kein passendes Abo" sauber behandeln (Telegram-Hinweis), nicht abstürzen. Die beiden anderen Magazine bleiben konfiguriert, damit ein neues Abo ohne Code-Änderung wirkt. |
| Die Abo-Nummer **wechselt bei jeder Verlängerung** (`2778322` → `2877536`) | Die drei in `config/ingestion.yaml` fest verdrahteten `overview_url`s sind veraltet/tot. Der Job darf keine Abo-URL hart verdrahten, sondern **entdeckt sie zur Laufzeit** über `/produkte/abonnements`. Das ist der eigentliche Robustheitsgewinn dieses Features. |
| Ausgaben-Seite listet Ausgaben **neueste zuerst**, je Eintrag ein `a[href="/produkte/content/<id>/download"]` | Erster Download-Link = aktuellste Ausgabe (von Ralf bestätigt). |
| `HEAD` auf den Download-Link liefert `405` | Download nur per GET/Klick → Playwrights `expect_download` statt HTTP-Client. |

### 2.2 Auth-Weg: gespeicherter Session-State statt Passwort

Ralf führt **einmalig** `scripts/boersenmedien_session.py` auf seinem Mac aus, meldet
sich im geöffneten Browser selbst an (inkl. „Angemeldet bleiben") und das Skript
sichert den Playwright-`storage_state` (Cookies) als JSON. Die Datei kommt auf die
Box und wird in den `api`-Container gemountet.

- **Kein Umgehen von Bot-Schutz:** ATLAS füllt kein Login-Formular aus und löst kein
  Turnstile-Widget. Es benutzt ausschließlich eine Session, die ein Mensch erzeugt hat.
- **Kein Secret im Repo/`.env`:** die Session-Datei liegt nur auf der Box unter
  `data/ingest/boersenmedien/` (nicht im Git, wie `data/ledger/` und
  `data/ingest/publications/`). Sie ist ein Credential — Dateirechte `600`.
- **Ablauf der Session** ist der erwartete Normalfall, kein Ausnahmefehler: der Job
  erkennt ihn (Redirect auf `login.boersenmedien.de` bzw. sichtbares
  `#SignInPassword`) und fällt auf **exakt die heutige F013-Telegram-Aufforderung**
  zurück, ergänzt um den Hinweis, das Session-Skript neu laufen zu lassen. Damit ist
  der schlechteste Fall dieses Features identisch mit dem heutigen Normalfall — es
  gibt keine Regression.

### 2.3 Invarianten

| Invariante | Berührt? | Umgang |
|---|---|---|
| #6 Secrets nie im Repo | ja | Session-JSON nur auf der Box (`data/` ist git-ignoriert und vom Deploy-rsync ausgeschlossen), Pfad über `BOERSENMEDIEN_SESSION_STATE`. Kein Passwort, kein Token im Repo oder in `.env.example`. |
| #9 Untrusted Content | ja | Unverändert: der PDF-Volltext geht durch dieselbe F011/F038-Pipeline in `publication_article` und erreicht Personas nur als getaggter Datenblock. Dieses Feature ändert **nichts** am Prompt-Pfad — es ersetzt nur „Mensch legt Datei ab" durch „Job legt Datei ab". Der Inhalt war vorher wie nachher fremdbestimmt. |
| #10 Fairness | nein | Shared Research Pool, kein persona-spezifischer Zugang. Es ändert sich nur die *Latenz*, mit der eine Ausgabe ankommt (Minuten statt „wann Ralf dazu kommt") — für alle Personas gleich. |
| #1 Risk-Gate / #2 Privilege Separation / #3 Decision-Pflicht | nein | Reiner Ingestion-Pfad, keine Order-Tools, keine Decisions. |
| ToS / §3.5.1 Gotcha (b) | ja | Automatisierter Abruf ausschließlich zur privaten Auswertung eines **bezahlten Abos**, ein Download pro erschienener Ausgabe (nicht mehr als ein Mensch abrufen würde). Volltexte bleiben intern; die UI zeigt weiterhin nur Zusammenfassungen + Quellenverweis. |
| Kosten | nein | Keine LLM-Calls. Ein Headless-Chromium für ~30 s pro Ausgabe (wöchentlich). |

### 2.4 Design-Entscheidungen

- **Abo-Discovery statt konfigurierter URLs.** Die Zuordnung läuft über den
  Produkt-Titel der Abo-Karte (`DER AKTIONÄR E-Paper`) gegen dasselbe
  `subject_keyword`, das schon die Mail-Betreff-Erkennung nutzt — eine
  Wahrheitsquelle, und Abo-Verlängerungen brechen nichts mehr.
- **Nur `AKTIV`-Karten.** Ein abgelaufenes Abo desselben Titels darf nicht gewinnen,
  sonst lädt der Job stillschweigend eine alte Ausgabe. Matching per
  `\bAKTIV\b`-Wortgrenze, damit `INAKTIV` nicht mitmatcht.
- **Dateiname = Downloadtag**, nicht Ausgabennummer: hält die bestehende
  F011-Konvention `<slug>/<YYYY-MM-DD>.pdf` unverändert (die Portal-Beschriftung
  „31/26" ist kein Datum). Existiert die Zieldatei schon, wird der Download
  übersprungen und nur die Pipeline erneut (idempotent) ausgeführt — schützt gegen
  n8n-Retries.
- **Webhook antwortet sofort mit 202, Arbeit läuft als Background-Task.** Ein
  Browser-Download dauert deutlich länger als n8n auf eine HTTP-Antwort warten
  sollte. Der Playwright-Teil (Sync-API) läuft über `anyio.to_thread.run_sync`
  außerhalb des Event-Loops.
- **Eigene DB-Session im Background-Task**, nicht die Request-Session: die ist beim
  Ausführen des Tasks bereits geschlossen.
- **`overview_url` je Magazin entfällt**, ersetzt durch ein einzelnes
  `subscriptions_url` (`/produkte/abonnements`). Die drei alten URLs zeigen nach der
  Abo-Verlängerung ins Leere — eine tote URL in der Fallback-Aufforderung ist
  schlimmer als ein generischer, immer gültiger Einstiegspunkt.

## 3. Testdefinition (vor der Umsetzung)

Wie bei F012/F068: die Portalinteraktion steckt hinter einem schmalen `Protocol`
(`BoersenmedienPortal`), das im Test ein Fake erfüllt — die Auswahllogik ist damit
ohne Browser vollständig testbar. Der echte Playwright-Pfad
(`PlaywrightBoersenmedienPortal`, `run_auto_download_live`) wird live verifiziert,
nicht unit-getestet (kein Browser im Standard-Testlauf).

`tests/ingestion/test_publications_download.py`:

1. `select_subscription` findet die Karte per `subject_keyword` (case-insensitiv).
2. `select_subscription` ignoriert eine inaktive Karte desselben Titels und wählt die aktive.
3. `select_subscription` wirft `SubscriptionNotFound`, wenn nur inaktive Karten passen.
4. `select_subscription` wirft `SubscriptionNotFound` bei komplett fehlendem Abo.
5. `parse_active_flag` unterscheidet `AKTIV` von `INAKTIV` (Wortgrenze).
6. `select_latest_issue` liefert den ersten Download-Link (Dokumentreihenfolge).
7. `select_latest_issue` wirft `IssueNotFound` bei leerer Ausgabenliste.
8. `target_pdf_path` erzeugt exakt `<base>/<slug>/<YYYY-MM-DD>.pdf`.
9. `download_latest_issue` legt die Datei über das Fake-Portal am Zielpfad ab und meldet `skipped=False`.
10. `download_latest_issue` überspringt den Download, wenn die Zieldatei schon existiert (`skipped=True`, Portal wird nicht aufgerufen).
11. `download_latest_issue` legt ein fehlendes `<slug>`-Verzeichnis an.
12. Session-Ablauf (`BoersenmedienSessionExpired` aus dem Portal) propagiert und wird nicht verschluckt.
13. `format_download_success` enthält Magazin, Ausgabenbezeichnung und Artikelanzahl.
14. `format_fallback_alert` hängt den Fehlergrund an, wenn einer übergeben wird (F013-Verhalten ohne Grund unverändert).

Ergänzend in `tests/api/test_routes_ingestion.py` (bestehende Datei erweitern):

15. `/publications/notify` antwortet weiterhin `202` und stößt den Background-Task an (Task gemockt).
16. Unbekannter Betreff liefert weiterhin `422`, ohne Task-Start.
17. Fehlendes/falsches Secret liefert weiterhin `401`.

Vollständiger Testdurchlauf (`pytest` mit `DATABASE_URL`, ruff, mypy) plus
Live-Verifikation auf der Box, siehe §5.

## 4. Implementierung

| Datei | Rolle |
|---|---|
| `src/ingestion/publications_download.py` | neu — Abo-Discovery, Ausgabenauswahl, Download; `BoersenmedienPortal`-Protocol + Playwright-Implementierung |
| `scripts/boersenmedien_session.py` | neu — einmalige, menschengeführte Session-Erfassung (headed Browser) |
| `src/api/routes_ingestion.py` | Webhook antwortet 202 und startet `_download_and_ingest` als Background-Task; Rollback-Flag `_auto_download_enabled` |
| `src/ingestion/publications_notify.py` | `format_fallback_alert(..., reason=...)` — Fehlerpfad nennt jetzt die Ursache |
| `config/ingestion.yaml` | `auto_download`, `session_state_env`; tote Abo-URLs → `/produkte/abonnements` |
| `docker-compose.yml`, `.env.example` | Read-only-Mount `data/ingest/boersenmedien`, `BOERSENMEDIEN_SESSION_STATE` |
| `tests/ingestion/test_publications_download.py`, `tests/api/test_routes_ingestion.py` | die 17 Fälle aus §3 |

Der n8n-Workflow selbst bleibt **unverändert** — er war nie das Problem: er meldet
korrekt „neue Ausgabe da". Geändert hat sich nur, was ATLAS daraufhin tut.

## 5. Testdurchlauf und Live-Verifikation

**Automatisiert (22.07.2026, lokal):** `pytest` 645 passed / 20 deselected,
`ruff check` + `ruff format --check` sauber, `mypy` (strict für `src/risk`,
`src/broker`) ohne Findings.

**Selektor-Verifikation gegen die echte Seite (22.07.2026):** die beiden fragilen
Abfragen wurden in einer angemeldeten Browser-Session 1:1 gegen
konto.boersenmedien.com ausgeführt (nur lesend):

- `list_subscriptions`-Logik → genau 1 Karte:
  `{title: "DER AKTIONÄR E-Paper", active: true, issues_url: ".../2877536/A-10546504/ausgaben"}`
  → `select_subscription(..., "DER AKTIONÄR")` trifft.
- `list_issue_downloads`-Logik → 4 Ausgaben, erste:
  `{label: "DER AKTIONÄR 31/26", href: "/produkte/content/13601/download"}`
  → `select_latest_issue` wählt genau die aktuellste.
- Dabei gefunden und korrigiert: die vierte Karte trägt ein Promo-Badge
  (`★GRATIS★`) als erste Textzeile. Der Titel kommt deshalb aus dem `h2` der Karte,
  nicht aus der ersten Zeile des Kartentexts — sonst hieße die Ausgabe in der
  Telegram-Meldung „★GRATIS★".

**Noch offen (braucht Ralf):** Session-Erfassung + Ende-zu-Ende-Lauf auf der Box.

## 6. Rollback

Config-Flag `publications.auto_download: true|false` in `config/ingestion.yaml`:
steht es auf `false`, verhält sich der Webhook exakt wie F013 (nur
Telegram-Aufforderung). Rollback ist damit eine Config-Änderung + Rebuild
(`config/` ist ins Image gebacken) ohne Code-Revert.
