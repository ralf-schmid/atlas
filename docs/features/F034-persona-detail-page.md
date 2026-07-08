# F034 — Persona-Detailseite (Bestand, Transaktionen, Impuls-Analyse)

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

Ralf nach dem ersten Blick auf die (jetzt alle 6 Personas zeigende) Übersicht:
die Darstellung ist "etwas knapp". Gewünscht pro Persona: eine Detailseite mit
Bestand (Menge, Kaufdatum/-preis, aktueller Preis, P&L absolut/Prozent),
Transaktionshistorie, einer Kurzbeschreibung der Persona (Philosophie/Vorgehen)
und einer Analyse der verarbeiteten Impulse — welche Recherche-Quelle
(Zeitschrift, EDGAR, aktienfinder.de, ...) hat zur Entscheidung geführt, wie
sicher war sich die Persona (Conviction).

**Scope:** 4 neue Read-only-Endpunkte (`/profile`, `/holdings`, `/transactions`,
`/decisions`), eine neue Next.js-Route `/personas/[name]`, plus eine kurze
Kurzbeschreibung auf der Übersichtsseite mit Link zur Detailseite.
**Non-Scope:** keine neue Ranking-/Leaderboard-Logik (spätere Phase laut
CLAUDE.md), keine Pagination (Decision-Journal hart auf 50 begrenzt — für das
aktuelle Datenvolumen ausreichend), kein Live-Update/SSE (Server-Rendering wie
F007).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #9 Untrusted Content | nein | Alle neuen Endpunkte lesen nur bereits persistierte, code-erzeugte Felder (Decision/OrderRecord/ResearchItem-Metadaten) — kein LLM-Call, keine Ausgabe von Rohtext aus Zeitschriften/Webseiten (nur `summary`, das bereits in F009-F014 deterministisch/redaktionell erzeugt wird). |
| Finanzkennzahlen nicht vom Frontend "ausrechnen" lassen | ja | `current_price`/`pnl_unrealized_pct` werden im FastAPI-Layer aus bereits vom Code berechneten Werten (`market_value`, `avg_price`, `pnl_unrealized`) abgeleitet — reine Arithmetik auf vorhandenen, deterministischen Feldern, keine neue Bewertungslogik. |
| Zeitschriften-/aktienfinder-Volltexte nicht in UI bringen | ja | Nur `research_item.summary` (bereits die redaktionelle Kurzfassung aus der Ingestion, kein Volltext) + `source_type`-Label + Alter — konsistent mit dem bestehenden Verbot in CLAUDE.md. |
| Fairness (#10) | nein | Rein lesende Darstellung, keine Persona bekommt zusätzliche Daten gegenüber einer anderen — jede Persona zeigt exakt ihre eigenen Bestände/Transaktionen/Decisions. |

**Design-Entscheidungen:**
- **Kein neuer "Kaufdatum"-Datentyp:** Positionen sind Broker-/Ledger-seitig
  gemittelte Bestände (kein FIFO-Lot-Tracking). `last_buy_at` im Holdings-Endpoint
  ist daher explizit als Referenzwert dokumentiert (letzter *gefüllter* Buy-Order
  für dieses Instrument), nicht als exakte Lot-Historie — die Transaktionsliste
  darunter zeigt die tatsächliche Kauf-für-Kauf-Chronologie.
- **`age_days` wiederverwendet (F033):** `compute_age_days` wurde von
  `persona_analysis.py` public gemacht, damit die Impuls-Analyse exakt dasselbe
  Alterssignal zeigt, das die Persona bei der Entscheidung selbst gesehen hat —
  keine zweite Altersberechnung.
- **`conviction` nur bei `buy`:** das Schema hat aktuell keine Konfidenzzahl für
  hold/reject_idea — die UI zeigt dort bewusst nichts statt eines erfundenen
  Werts.
- **Persona-Profil aus `_CHARTER_CONTENT` (F018), nicht dupliziert:** neue
  `get_persona_profile()`-Funktion in `charters.py` liest dieselbe
  Single-Source-of-Truth wie der LLM-Prompt — eine Formulierungsänderung an einer
  Stelle wirkt auf Charter-Prompt und UI gleichermaßen.

**Kosten:** keine (reine DB-Reads). **Fairness:** identische Datenstruktur für
alle 6 Personas.

## 3. Testdefinition

`tests/api/test_routes.py` (9 neue Tests):
1. `/profile`: liefert statischen Charter-Content (200) / 404 für unbekannte
   Persona.
2. `/holdings`: berechnet `current_price`/`pnl_unrealized_pct` korrekt aus
   Snapshot-Daten; `last_buy_at` aus dem letzten gefüllten Buy-Order; leere Liste
   (nicht 404) ohne Snapshot.
3. `/transactions`: neueste zuerst.
4. `/decisions`: referenzierte Research-Items inkl. `age_days` relativ zum
   Zyklus-Start; `conviction` nur bei `buy` gesetzt, bei `hold` `null`.

## 4. Implementierung

- `src/personas/charters.py`: `PersonaProfile`-Dataclass + `get_persona_profile()`.
- `src/orchestrator/persona_analysis.py`: `_age_days` → public `compute_age_days`.
- `src/api/schemas.py`: `PersonaProfileOut`, `HoldingOut`, `TransactionOut`,
  `ResearchRefOut`, `DecisionOut`.
- `src/api/routes.py`: `_get_persona_and_portfolio()`-Helper (dedupliziert die
  Persona/Portfolio-404-Logik über 5 Endpunkte) + 4 neue Routen.
- `tests/db/factories.py`: `make_decision`/`make_order_record` um
  `expected_outcome`/`submitted_at`/`filled_at`/`fill_price`/`status`-Overrides
  erweitert (additiv, Defaults unverändert).
- `web/src/lib/api.ts`: Typen + Fetcher für die 4 neuen Endpunkte.
- `web/src/lib/labels.ts`: deutsche Anzeige-Labels für Action/Status/Source-Type
  (rein präsentational, API bleibt Englisch).
- `web/src/app/page.tsx`: Kurzbeschreibung je Karte + Link zur Detailseite.
- `web/src/app/personas/[name]/page.tsx`: neue Detailseite (Profil, Bestand,
  Transaktionen, Impuls-Analyse).

## 5. Test & Rollout

- `uv run pytest`: 382 passed. `ruff check`/`format --check`, `mypy`: clean.
- `npm run lint`, `npx tsc --noEmit`: clean.
- Lokal gegen die Test-Postgres verifiziert (Preview-Browser): Übersichtsseite
  mit 6 Personas + Kurzbeschreibung, Detailseite mit realistischem
  Bestand/Transaktion/Impuls-Szenario (inkl. sichtbarer F033-Aktualitätsgewichtung
  im Thesis-Text), leere Zustände für Personas ohne Daten, 404 für unbekannte
  Persona. DB danach wieder in sauberem Zustand (Session-Fixture-Teardown).
- Deployment: rsync + `docker compose build api web` + `up -d`.
- **Rollback-Pfad:** reiner Code-/Route-Revert (keine Migration, kein
  Schema-Change) — `git revert` der Commits genügt.
