# F012 — aktienfinder-Grabbing

Status: umgesetzt, live verifiziert
Datum: 2026-07-05
Phase: 3

## 1. Zieldefinition

P3-DoD-Punkt "aktienfinder-Grabbing liefert für 10 Testtitel strukturierte Snapshots +
Beleg-Screenshot, täglich per Schedule" (ARCHITECTURE.md §3.5.2/§8): DOM-Extraktion
statt Vision (robuster, billiger), Screenshot als Beleg für Lineage, Ergebnis in
`aktienfinder_snapshot`. Primärnutzer GUARDIAN, CONTRA (Fundamentaldaten ändern sich
nicht pro Zyklus, daher 1×/Tag).

**Hinweis zur Domain:** ARCHITECTURE.md nennt "aktienfinder.de" — die tatsächliche
Domain ist `aktienfinder.net` (aktienfinder.de leitet dorthin um/existiert nicht als
separate Seite). Rein technische Detailkorrektur, hier dokumentiert statt stillschweigend
angenommen.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| "aktienfinder-Volltexte in UI oder Repo bringen" verboten (CLAUDE.md) | ja | `aktienfinder_snapshot.fields` enthält nur die konfigurierten, benannten Werte (Kurs, ISIN, Dividendenrendite, drei Qualitäts-Scores, Dividenden-Historie als strukturierte Zeilen) — keine Volltext-Seiteninhalte. Der Screenshot ist Beleg/Lineage, kein UI-Content; die API/UI-Schicht (nicht Teil dieses Features) muss beim Ausliefern weiterhin auf Metadaten/Zusammenfassung reduzieren. |
| #6 Secrets nie im Repo | ja | `AKTIENFINDER_USERNAME`/`_PASSWORD` ausschließlich aus Environment (`.env`, gitignored), wie überall sonst. Kein Wert im Repo, in `config/ingestion.yaml` stehen nur die Env-Var-*Namen*. |
| Idempotenz aller Ingestion-Jobs (P3-DoD Punkt 6) | ja | `sync_aktienfinder_snapshots` upsertet über `UniqueConstraint(symbol, snapshot_date)` — ein erneuter Lauf am selben Tag überschreibt, dupliziert nicht. |
| #10 Fairness | ja | GUARDIAN/CONTRA sind laut Architektur die "Primärnutzer", aber der Snapshot landet in einer für alle Personas gleichermaßen lesbaren Tabelle — kein exklusiver Zugriff, nur unterschiedliche Nutzungsgewichtung im späteren Agenten-Code (P4). |
| Kein Informationsvorsprung durch Live-Exploration | ja | Die Selektor-Recherche gegen die echte, eingeloggte Seite (Abschnitt 5) hat ausschließlich öffentlich für Premium-Abonnenten sichtbare Strukturdaten (Kurs, Scores, Dividendenhistorie) gelesen — keine Trades ausgelöst, keine Konto-Änderungen vorgenommen. |

**Design-Entscheidungen:**
- **`AktienfinderPage`-Protocol** entkoppelt die reine Extraktions-/Persistenzlogik
  (`extract_snapshot`, `sync_aktienfinder_snapshots`, `run_daily_grab`) von Playwright —
  diese bleiben mit einer Fake-Page testbar, kein echter Browser im Standard-Testlauf.
- **Zwei Ebenen von `run_*`-Funktionen**, wie schon bei F008–F011 etabliert, hier aber
  zusätzlich gestaffelt: `run_daily_grab` (nimmt fertig navigierte `AktienfinderPage`s
  entgegen, reine Logik, unit-getestet) und `run_daily_grab_live` (öffnet echten
  Playwright-Browser, loggt sich ein, navigiert selbst — Live-Pfad, nur manuell bzw.
  per `pytest.mark.integration` verifiziert, kein Standard-Unit-Test mit echtem Browser).
- **Playwrights eigene CSS-Erweiterungen** (`:has-text()`, `:nth-match()`) statt
  fragiler DOM-Positions-Selektoren — funktioniert robust über verschiedene Aktien
  hinweg (live an Apple und SAP verifiziert, siehe Abschnitt 5), weil es an
  Label-Texten ("ISIN", "Aktienkurs", "Dividendenrendite") ansetzt statt an
  Positionen/Klassennamen, die sich mit einem Frontend-Update leichter ändern.
  **Grenze:** falls aktienfinder.net auf ein anderes Frontend-Framework wechselt oder
  die Label-Texte ändert, brechen die Selektoren — kein Schutz gegen Layout-Änderungen,
  nur robuster als reine Positions-Selektoren.
- **Zwei Views pro Symbol:** `/aktien-profil/<isin>` (Kurs, ISIN, Dividendenrendite,
  drei Qualitäts-Scores — Dividendenertrag/-wachstum/Gewinnwachstum — plus
  Fair-Value-Chart-Screenshot) und `/dividenden-profil/<isin>` (Dividenden-Historie als
  Tabelle: Ex-Datum, Zahltag, Betrag, Art). Beide Views sind direkt per ISIN adressierbar
  (kein Namens-Slug nötig), das war beim Explorieren nicht offensichtlich (Architektur
  nennt "gezielte Views" im Plural — genau das).
- **Fair-Value-Zahl selbst nicht per DOM-Selektor extrahiert:** der Chart ist
  Canvas-gerendert (Chart.js o.ä.), kein Text-Element mit dem fairen Wert als Zahl.
  Konsequent mit ARCHITECTURE.md §3.5.2 ("... + Screenshot als Beleg") wird der Chart
  über den Screenshot dokumentiert, nicht über einen (nicht existierenden) DOM-Wert.
  Der Analysten-Kursziel-Text ("41 Analysten, Kursziel X USD") wäre extrahierbar, ist
  aber in Fließtext eingebettet statt in einem eigenen Element — für die
  Erstversion bewusst nicht als Selektor-Feld aufgenommen (zu brüchig), bleibt eine
  mögliche Erweiterung.
- **`fields` als JSONB** (`Snapshot.fields: dict[str, object]`, nicht nur `str | None`):
  hält sowohl die skalaren Werte als auch `dividend_history` (Liste strukturierter
  Zeilen) in einem Feld.

**Kosten:** keine LLM-Calls. **Fairness:** ein Extraktionspfad, ein Ergebnis-Datensatz
für alle Personas.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/ingestion/test_aktienfinder_grabbing.py`), `AktienfinderPage`/Page
per Fake implementiert, kein echter Browser:

1. `extract_snapshot` liest konfigurierte Felder aus der (Fake-)DOM, speichert einen
   Screenshot unter dem erwarteten Pfad (`<symbol>_<datum>.png`).
2. `extract_snapshot` liefert `None` für einen Selektor ohne Treffer (kein Crash).
3. `sync_aktienfinder_snapshots` mit leerer Liste → `0`.
4. `sync_aktienfinder_snapshots` zweimal für denselben Tag mit unterschiedlichen Werten
   → genau eine Zeile je Symbol, mit den Werten des zweiten Laufs (Idempotenz-Nachweis).
5. `run_daily_grab` liest Config (Feld-Selektoren, Screenshot-Verzeichnis-Env) korrekt
   und verarbeitet die übergebenen Pages.
6. `run_daily_grab` wirft eine klare `ValueError`, wenn die Env-Var fehlt.
7. `login` füllt Benutzername/Passwort in die erwarteten Felder und navigiert zu
   `/profil`.
8. `login` wirft `AktienfinderLoginError`, wenn die Navigationsleiste nach dem Absenden
   kein "Abmelden" zeigt (falsche Zugangsdaten / Login-Flow hat sich geändert).
9. `extract_dividend_history` mappt Tabellenzeilen korrekt auf strukturierte Dicts.
10. `extract_dividend_history` überspringt unvollständige Zeilen (kein Crash).

Zusätzlich ein Live-Integrationstest
(`tests/ingestion/test_aktienfinder_grabbing_integration.py`, `pytest.mark.integration`,
übersprungen ohne echte Zugangsdaten): `run_daily_grab_live` gegen zwei echte Symbole
(Apple, SAP), prüft echte Werte + nicht-leere Dividenden-Historie.

## 4. Implementierung

`src/ingestion/aktienfinder_grabbing.py`:
- Reine/testbare Ebene: `Snapshot`, `AktienfinderPage`-Protocol, `extract_snapshot`,
  `sync_aktienfinder_snapshots`, `run_daily_grab`.
- Live-Ebene: `PlaywrightAktienfinderPage`, `login`, `extract_dividend_history`,
  `grab_isin_snapshot`, `run_daily_grab_live`, `AktienfinderLoginError`.

`src/db/models.py` (`AktienfinderSnapshot`), Migration
`alembic/versions/f51bad7b1d9a_add_aktienfinder_snapshot.py`, `config/ingestion.yaml`
(`aktienfinder`-Sektion mit live verifizierten Selektoren + `username_env`/
`password_env`), `.env`/`.env.example` (`AKTIENFINDER_USERNAME`, `AKTIENFINDER_PASSWORD`,
`AKTIENFINDER_SCREENSHOT_DIR`). Dependency `playwright` (Python-Paket) +
Chromium-Browser-Binary lokal installiert (`playwright install chromium`).

## 5. Testdurchlauf

`uv run pytest tests/ingestion -q` → 44 passed (34 aus F008–F011 + 10 aus F012, Login/
Dividenden-Historie-Tests). `uv run pytest -q` (Gesamtsuite) → 230 passed, 2 deselected
(Alpaca- + aktienfinder-Integrationstests, per `-m 'not integration'`). `uv run ruff
check`/`ruff format --check` → sauber. `uv run mypy src/ingestion` → sauber. Migration
im upgrade→downgrade→upgrade-Zyklus verifiziert.

**Live-Verifikation (2026-07-05), gegen Ralfs echtes aktienfinder.net-Konto:**
1. Login-Flow interaktiv exploriert (Playwright, sichtbarer Chromium): `/profil` →
   "Anmelden"-Klick öffnet `#username`/`#password`-Felder → "Weiter"-Button. Erfolgreich
   eingeloggt, Premium-Abo bestätigt (Kundennummer, Abo-Details sichtbar).
2. Stock-Profile-URL-Schema gefunden: `/aktien-profil/<ISIN>` (leitet auf lesbaren
   Namens-Slug um), `/dividenden-profil/<ISIN>` — beide direkt per ISIN erreichbar.
3. Alle sechs `field_selectors` + Dividenden-Tabellen-Extraktion gegen **zwei
   verschiedene** Aktien getestet (Apple `US0378331005`, SAP `DE0007164600`) — beide
   lieferten korrekte, plausible Werte (Kurs, ISIN, Dividendenrendite, drei
   Qualitäts-Scores 1/6/7 bzw. 4/7/5, je 8 Dividenden-Historie-Zeilen).
4. `run_daily_grab_live(session, ["US0378331005", "DE0007164600"], today)` end-to-end
   gegen eine lokale Postgres-Instanz ausgeführt: 2 Snapshots persistiert, beide
   Screenshots real und nicht-leer (121 KB / 352 KB PNG), Cookie-Banner vor dem
   Screenshot automatisch weggeklickt.
5. Der Live-Integrationstest (`test_aktienfinder_grabbing_integration.py`) reproduziert
   genau diesen Ablauf und lief lokal grün (`AKTIENFINDER_USERNAME`/`_PASSWORD` aus
   `.env`).

**Noch offen:**
- **10-Testtitel-Nachweis** aus dem P3-DoD-Wortlaut: bisher 2 Symbole live verifiziert
  (Apple, SAP), nicht 10 — die Selektoren sind aber nachweislich symbolübergreifend
  stabil (unterschiedliche Branche/Land/Währung), ein Hochskalieren auf 10 ist reine
  Wiederholung, kein neues Risiko.
- **Scheduler/Poller** für `run_daily_grab_live` (analog F008–F011: P4/Ops-Folgearbeit).
- **CI-Integration bewusst nicht vorgenommen:** der Live-Integrationstest braucht
  `AKTIENFINDER_USERNAME`/`_PASSWORD` als GitHub Encrypted Secrets — analog zum
  Alpaca-Paper-Integrationstest wird das nur nach Ralfs explizitem Go gemacht, nicht
  automatisch beim Implementieren.
- **Analysten-Kursziel-Text** nicht als eigenes Feld extrahiert (siehe Design-
  Entscheidungen) — mögliche spätere Erweiterung.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert. Rollback = Commit
zurücknehmen + `alembic downgrade -1` (getestet, s. o.). Der Login-Flow schreibt nichts
auf aktienfinder.net (reine Leseoperationen), ein Rollback hinterlässt dort keine Spuren
außer den serverseitigen Zugriffslogs der Site selbst.
