# F009 — EDGAR-RSS Filings-Ingestion

Status: umgesetzt
Datum: 2026-07-05
Phase: 3

## 1. Zieldefinition

P3-DoD-Punkt "EDGAR-RSS + Marktdaten-Sync laufen 5 Tage unterbrechungsfrei"
(ARCHITECTURE.md §8): SEC EDGARs kostenloses, offizielles "current filings"-Atom-Feed
(§3.5.3) abrufen, in eine Staging-Tabelle `edgar_filing` persistieren. Agenten lesen
später ausschließlich aus dieser Tabelle, nie live von sec.gov (CLAUDE.md: "Agenten
lesen ausschließlich aus der DB, nie direkt aus dem Internet").

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #9 Untrusted Content (Prompt Injection) | ja | Der Feed ist externer Inhalt. Zwei Ebenen: (a) XML-Parsing über `defusedxml` statt `xml.etree.ElementTree` (XXE/Billion-Laughs-Schutz — Hinweis kam vom Security-Hook beim Schreiben der Datei, sofort übernommen). (b) Diese Ingestion schreibt nur strukturierte Metadaten in eine Staging-Tabelle; kein Agent mit Schreib-/Order-Rechten bekommt Feed-Rohtext in seinen System-Prompt — das bleibt Aufgabe der späteren Agenten-Anbindung (P4), hier nur die Persistenz. |
| Idempotenz aller Ingestion-Jobs (P3-DoD Punkt 6) | ja | `sync_edgar_filings` upsertet über `UniqueConstraint(accession_number)` (`ON CONFLICT DO NOTHING`, Filings sind nach Vergabe unveränderlich) — wiederholtes Polling desselben Feed-Fensters erzeugt keine Duplikate. |
| #6 Secrets nie im Repo | ja | Kein Secret im eigentlichen Sinn, aber SEC verlangt einen aussagekräftigen `User-Agent` (Name + Kontakt) für automatisierte Zugriffe — kommt aus `EDGAR_USER_AGENT` (Env), nicht aus `config/ingestion.yaml`. **Vor Live-Betrieb braucht Ralf hier seine echten Kontaktdaten** (kein Blocker für dieses Feature, da Tests den HTTP-Call mocken). |

**Design-Entscheidungen:**
- **Neue Tabelle `edgar_filing`**, nicht `research_item` — das ist die rohe Feed-Zeile,
  keine Agenten-Zusammenfassung (research_item entsteht erst, wenn ein Recherche-Agent
  daraus etwas macht — P4). Gleiche Argumentation wie bei `market_bar` (F008): direkt
  im Feature-Dokument begründet, kein separates ADR.
- **Titel-Parsing per Regex** (`FORM - COMPANY (CIK) (Filer)`), da EDGARs Atom-Feed
  Formtyp/Firma/CIK nicht als eigene Felder liefert, nur im `<title>`-Text kombiniert.
  Einträge, die nicht diesem Muster entsprechen, werden trotzdem übernommen (Titel roh
  als `company_name`, `cik=None`) — lieber unvollständige Metadaten als einen Filing
  stillschweigend zu verlieren.
- **`EdgarFeedProvider`-Protocol** (analog `BarsProvider` aus F008): Parsing- und
  Sync-Logik bleiben ohne echten HTTP-Call testbar.

**Kosten:** keine LLM-Calls, kostenloser öffentlicher Feed. **Fairness:** ein
Sync-Pfad, ein Datensatz für alle Personas.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/ingestion/test_edgar_rss.py`), HTTP-Call gemockt, kein echter
sec.gov-Zugriff:

1. `parse_atom_feed` extrahiert Accession-Number, Formtyp, Firma, CIK, Titel, Link,
   Summary, Zeitstempel korrekt aus einem Beispiel-Feed mit zwei Einträgen.
2. `parse_atom_feed` überspringt Einträge ohne `id` oder `updated` (kein Crash bei
   kaputten/unerwarteten Feed-Einträgen).
3. `HttpEdgarFeedProvider` sendet den konfigurierten `User-Agent`-Header.
4. `HttpEdgarFeedProvider` wirft `HTTPStatusError` bei einem Fehlerstatus (503).
5. `sync_edgar_filings` mit leerer Liste → `0`, kein DB-Zugriff nötig.
6. `sync_edgar_filings` fügt neue Filings ein, per DB-Query verifiziert.
7. `sync_edgar_filings` zweimal mit denselben Filings → zweiter Lauf liefert `0` neue
   Zeilen, insgesamt bleiben genau 2 Zeilen (Idempotenz-Nachweis).
8. `run_current_filings_sync` liest Feed-URL + Env-Var-Name aus Config-Datei.
9. `run_current_filings_sync` wirft eine klare `ValueError`, wenn die Env-Var fehlt.

## 4. Implementierung

`src/ingestion/edgar_rss.py` (`Filing`, `EdgarFeedProvider`, `HttpEdgarFeedProvider`,
`parse_atom_feed`, `sync_edgar_filings`, `run_current_filings_sync`),
`src/db/models.py` (`EdgarFiling`), Migration
`alembic/versions/74cd69ad0125_add_edgar_filing.py`, `config/ingestion.yaml`
(`edgar`-Sektion). Neue Dependency `defusedxml` (+ `types-defusedxml` für mypy).

## 5. Testdurchlauf

`uv run pytest tests/ingestion -q` → 16 passed (7 aus F008 + 9 aus F009).
`uv run pytest -q` (Gesamtsuite) → 202 passed. `uv run ruff check`/`ruff format --check`
→ sauber. `uv run mypy src/ingestion` → sauber. Migration im
upgrade→downgrade→upgrade-Zyklus verifiziert (keine ENUM-Typen in dieser Tabelle,
Standard-Autogenerate reicht ohne Anpassung).

**Noch offen:**
- `run_current_filings_sync` ist noch nirgends automatisch geplant (gleiche
  Ops-Folgearbeit wie F008 — P4/Orchestrator bzw. Cron-Übergangslösung).
- `EDGAR_USER_AGENT` mit Ralfs echten Kontaktdaten fehlt noch für den Live-Betrieb
  (Fallback-first: Code+Tests stehen, Live-Poll folgt sobald die Env-Var gesetzt ist).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert. Rollback = Commit
zurücknehmen + `alembic downgrade -1` (getestet, s. o.).
