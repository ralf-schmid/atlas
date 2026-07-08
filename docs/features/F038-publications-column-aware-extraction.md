# F038 — Spalten-bewusste Zeitschriften-Extraktion

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

HYPEs erster Live-Zyklus: *"ohne zusammenhängenden Fließtext [...] nur
zerstückelte Inhaltsverzeichnis-/Layout-Fragmente"*. Die bestehende
PDF-Segmentierung (`extract_articles`, F011) nutzt eine reine
Schriftgrößen-Heuristik ohne Spalten-/Layout-Verständnis — bei echtem
Magazin-Layout (Mehrspaltig, Inhaltsverzeichnis, Werbeanzeigen,
wiederkehrende Kopf-/Fußzeilen) zerlegt das in genau die Schnipsel, die
HYPE/VULTURE/CHARTIST/CONTRA/CRYPTOR alle unabhängig voneinander bemängelt
haben.

**Scope:** drei gezielte, abhängigkeitsfreie Ergänzungen der bestehenden
PyMuPDF-Heuristik (Spalten-bewusste Reihenfolge, Kopf-/Fußzeilen-Filter,
Mindestlänge). **Non-Scope:** Docling/Vision-basierte Segmentierung (im Code
bereits als mögliche Eskalationsstufe vermerkt, hier nicht umgesetzt — siehe
Design-Entscheidungen).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Zeitschriften-Volltexte nicht in UI/Repo | nein | Unverändert — nur die Segmentierungs-*Qualität* ändert sich, nicht was gespeichert/angezeigt wird. |
| #9 Untrusted Content | nein | Reine Text-Vorverarbeitung vor der Persistenz, keine neue Interpretation. |

**Design-Entscheidungen:**
- **Leichte PyMuPDF-Verbesserung statt Docling.** Docling ist ein schweres
  ML-Layout-Modell (Gewichts-Download, spürbar größeres Image, langsamerer
  Kaltstart) — auf der UGREEN (kein GPU, ARCHITECTURE.md §3.2/§3.3.1) bei
  wöchentlicher Kadenz (§3.5.1) unverhältnismäßig. Die drei Ergänzungen hier
  brauchen keine neue Abhängigkeit, arbeiten nur mit Daten, die PyMuPDF ohnehin
  liefert (`span["bbox"]`). Docling bleibt explizit vermerkte
  Eskalationsstufe, falls diese leichte Verbesserung nicht reicht.
- **Spalten-Erkennung: einfache 2-Spalten-Bisektion** (`x0 < Seitenbreite/2`)
  statt echter Layout-Analyse — deckt die häufigste Magazin-Spaltenzahl ab,
  bei einspaltigem Text landet ohnehin alles in Spalte 0 (kein Nachteil).
  Spans werden vor der Segmentierung nach `(Spalte, y0)` sortiert statt in
  PyMuPDFs Roh-Blockreihenfolge verarbeitet.
- **Kopf-/Fußzeilen-Filter erkennt nur exakt wiederholten Text** (auf ≥ 3
  Seiten identisch) — trifft echte wiederkehrende Elemente ("DER AKTIONÄR —
  Ausgabe 28/2026"), **nicht** Seitenzahlen, die sich von Seite zu Seite
  unterscheiden ("12", "13", ...). Letztere werden stattdessen indirekt durch
  den Mindestlängen-Filter abgefangen, wenn sie als eigenständige,
  bedeutungslose "Artikel" auftauchen.
- **Mindestlänge 80 Zeichen** — konservativer Startwert, im Feature-Doc
  bewusst als nachjustierbar markiert (kein prinzipiell "richtiger" Wert).
- **`_BOILERPLATE_MIN_PAGES = 3`** — ebenfalls ein Startwert; zu niedrig würde
  echte, zufällig wiederholte kurze Phrasen fälschlich filtern, zu hoch würde
  bei kurzen Ausgaben (wenige Seiten) nichts mehr erkennen.

**Kosten:** keine. **Fairness:** unverändert (gleiche Pipeline für alle
Publikationen/Personas).

## 3. Testdefinition

`tests/ingestion/test_publications_pipeline.py` (5 neue Tests, synthetische
PyMuPDF-Test-PDFs, keine echte Magazin-Datei nötig):
1. Zwei Spalten, gegeneinander interleaved eingefügt (um PyMuPDFs
   Roh-Blockreihenfolge realistisch zu verwürfeln) → beide Artikel sauber
   getrennt, kein Text der anderen Spalte im jeweiligen Body.
2. Eine auf ≥ 3 Seiten identische Zeile wird aus allen Artikeln entfernt.
3. Dieselbe Zeile auf nur 2 Seiten bleibt erhalten (Schwellenwert-Grenze).
4. Ein kurzer "Artikel" (Überschrift + < 80 Zeichen Body, z. B. ein
   TOC-Eintrag) wird komplett verworfen.
5. Bestehender Zwei-Artikel-Test (Schriftgrößen-Segmentierung) auf längeren,
   realistischeren Body-Text angepasst, damit er weiterhin die
   Segmentierung testet und nicht versehentlich am neuen Mindestlängen-Filter
   scheitert.

Manueller Vergleichslauf gegen eine bereits eingelesene, echte Ausgabe
(Artikel-Anzahl/Stichproben-Diff vorher/nachher) als Test&Rollout-Schritt —
Layout-Qualität ist kein rein unit-testbares Kriterium.

## 4. Implementierung

- `src/ingestion/publications_pipeline.py`: `extract_articles` umgebaut auf
  einen zweistufigen Ablauf (Spans pro Seite sammeln + spalten-sortieren,
  dann Kopf-/Fußzeilen-Erkennung über alle Seiten, dann die bestehende
  Segmentierungs-Logik auf der bereinigten, sortierten Span-Folge); neue
  Helfer `_extract_page_spans`, `_detect_boilerplate_lines`, neuer
  `_Span`-Dataclass. Bestehende `sync_publication_articles`/
  `process_pdf_fallback_file`/`parse_issue_path` unverändert.
- Kein Alembic-Migrations-Bedarf.

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 414 passed. `ruff check`/`format --check`,
  `mypy`: clean.
- Deployment: rsync + `docker compose build api` + `up -d` (kein neuer Service,
  `process_pdf_fallback_file` läuft weiterhin über den bestehenden
  Webhook-/Poller-Pfad, F013).
- Manuelle Verifikation nach Deploy: eine bereits verarbeitete Ausgabe erneut
  durch `extract_articles` laufen lassen (idempotent, kein DB-Effekt bei
  reinem Vergleich außerhalb von `process_pdf_fallback_file`), Artikel-Anzahl
  und 3-5 Stichproben mit dem alten Ergebnis vergleichen.
- **Rollback-Pfad:** reiner Code-Revert von `extract_articles` (keine
  Schema-/Config-Änderung).
