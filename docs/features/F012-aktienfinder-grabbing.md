# F012 — aktienfinder-Grabbing

Status: teilweise umgesetzt (Extraktions-/Persistenz-Kernpfad fertig, Login/Playwright-Wiring offen)
Datum: 2026-07-05
Phase: 3

## 1. Zieldefinition

P3-DoD-Punkt "aktienfinder-Grabbing liefert für 10 Testtitel strukturierte Snapshots +
Beleg-Screenshot, täglich per Schedule" (ARCHITECTURE.md §3.5.2/§8): DOM-Extraktion
statt Vision (robuster, billiger), Screenshot als Beleg für Lineage, Ergebnis in
`aktienfinder_snapshot`. Primärnutzer GUARDIAN, CONTRA (Fundamentaldaten ändern sich
nicht pro Zyklus, daher 1×/Tag).

Wie bei F011: der Kernpfad (Feld-Extraktion aus einer bereits navigierten Seite,
Screenshot-Ablage, idempotente Persistenz) ist hier fertig und getestet. Die eigentliche
Playwright-Session mit echtem aktienfinder.de-Login ist **nicht** Teil dieses Commits —
siehe Abschnitt 5.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| "aktienfinder-Volltexte in UI oder Repo bringen" verboten (CLAUDE.md) | ja | `aktienfinder_snapshot.fields` enthält nur die konfigurierten, benannten Werte (Fair-Value, Qualitäts-Score, Dividenden-Historie) — keine Volltext-Seiteninhalte. Der Screenshot ist Beleg/Lineage, kein UI-Content; die API/UI-Schicht (nicht Teil dieses Features) muss beim Ausliefern weiterhin auf Metadaten/Zusammenfassung reduzieren. |
| #6 Secrets nie im Repo | ja | Kein Login-Code in diesem Commit — daher auch keine aktienfinder.de-Zugangsdaten anzulegen. Wenn das Login-Wiring kommt, gilt dieselbe Env-Var-Konvention wie überall sonst. |
| Idempotenz aller Ingestion-Jobs (P3-DoD Punkt 6) | ja | `sync_aktienfinder_snapshots` upsertet über `UniqueConstraint(symbol, snapshot_date)` — ein erneuter Lauf am selben Tag überschreibt, dupliziert nicht. |
| #10 Fairness | ja | GUARDIAN/CONTRA sind laut Architektur die "Primärnutzer", aber der Snapshot landet in einer für alle Personas gleichermaßen lesbaren Tabelle — kein exklusiver Zugriff, nur unterschiedliche Nutzungsgewichtung im späteren Agenten-Code (P4). |

**Design-Entscheidungen:**
- **`AktienfinderPage`-Protocol** entkoppelt Extraktionslogik von Playwright: die
  Kernfunktionen (`extract_snapshot`, `sync_aktienfinder_snapshots`, `run_daily_grab`)
  nehmen eine bereits navigierte, bereits eingeloggte "Seite" (Protocol mit
  `query_selector_text`/`screenshot`) entgegen — Browser-Lifecycle und Login sind damit
  bewusst *nicht* Teil dieses Moduls. `run_daily_grab` bekommt fertige Pages
  (`dict[symbol, AktienfinderPage]`) übergeben, statt selbst einen Browser zu starten.
  Das hält die Kernlogik vollständig ohne echten Playwright-Browser testbar und legt
  die Grenze klar dort, wo tatsächlich Zugangsdaten gebraucht werden.
- **`field_selectors` in Config statt Code:** die echten CSS-Selektoren von
  aktienfinder.de sind aktuell unbekannt (dafür bräuchte es eine eingeloggte Session zum
  Inspizieren) — `config/ingestion.yaml` trägt Platzhalter-Selektoren
  (`[data-field='fair-value']` etc.), die durch echte ersetzt werden, sobald jemand die
  reale Seite inspiziert hat. Kein Code-Change nötig, wenn sich Selektoren ändern.
  **Wichtige Einschränkung:** diese Platzhalter sind nicht gegen die echte Seite
  verifiziert.
- **Fehlender Selektor → `None` statt Exception:** ein einzelnes fehlendes Feld soll
  nicht den ganzen Snapshot für ein Symbol verwerfen (aktienfinder.de-Layout ist nicht
  unter unserer Kontrolle).
- **`fields` als JSONB**, nicht feste Spalten: das erwartete Feld-Set wird wahrscheinlich
  wachsen, sobald die echte Seitenstruktur bekannt ist.

**Kosten:** keine LLM-Calls. **Fairness:** ein Extraktionspfad, ein Ergebnis-Datensatz
für alle Personas.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/ingestion/test_aktienfinder_grabbing.py`), `AktienfinderPage` per
Fake implementiert, kein echter Browser/keine echte Website:

1. `extract_snapshot` liest konfigurierte Felder aus der (Fake-)DOM, speichert einen
   Screenshot unter dem erwarteten Pfad (`<symbol>_<datum>.png`).
2. `extract_snapshot` liefert `None` für einen Selektor ohne Treffer (kein Crash).
3. `sync_aktienfinder_snapshots` mit leerer Liste → `0`.
4. `sync_aktienfinder_snapshots` zweimal für denselben Tag mit unterschiedlichen Werten
   → genau eine Zeile je Symbol, mit den Werten des zweiten Laufs
   (Idempotenz-Nachweis).
5. `run_daily_grab` liest Config (Feld-Selektoren, Screenshot-Verzeichnis-Env) korrekt
   und verarbeitet die übergebenen Pages.
6. `run_daily_grab` wirft eine klare `ValueError`, wenn die Env-Var fehlt.

## 4. Implementierung

`src/ingestion/aktienfinder_grabbing.py` (`Snapshot`, `AktienfinderPage`,
`extract_snapshot`, `sync_aktienfinder_snapshots`, `run_daily_grab`),
`src/db/models.py` (`AktienfinderSnapshot`), Migration
`alembic/versions/f51bad7b1d9a_add_aktienfinder_snapshot.py`, `config/ingestion.yaml`
(`aktienfinder`-Sektion mit Platzhalter-Selektoren). Neue Dependency `playwright`
(Python-Paket) — **Browser-Binaries sind nicht installiert** (`playwright install`
nicht ausgeführt), da hier noch keine echte Browser-Session läuft.

## 5. Testdurchlauf

`uv run pytest tests/ingestion -q` → 40 passed (34 aus F008–F011 + 6 aus F012).
`uv run pytest -q` (Gesamtsuite) → 226 passed. `uv run ruff check`/`ruff format --check`
→ sauber. `uv run mypy src/ingestion` → sauber. Migration im
upgrade→downgrade→upgrade-Zyklus verifiziert (keine ENUM-Typen in dieser Tabelle).

**Noch offen (bewusst nicht Teil dieses Commits):**
- **Echte Playwright-Session mit Login** gegen aktienfinder.de — braucht Ralfs
  aktienfinder.de-Zugangsdaten. Wird nicht ohne Rückfrage angelegt.
- **`playwright install`** (Browser-Binaries) auf der UGREEN, sobald das Login-Wiring
  ansteht.
- **Echte CSS-Selektoren** für Fair-Value-Chart, Qualitäts-Score, Dividenden-Historie —
  aktuell Platzhalter in `config/ingestion.yaml`, müssen gegen die echte, eingeloggte
  Seite verifiziert werden.
- **10-Testtitel-Nachweis** aus dem P3-DoD-Wortlaut ("liefert für 10 Testtitel
  strukturierte Snapshots + Beleg-Screenshot") ist erst nach dem Login-Wiring möglich.
- Scheduler/Poller für `run_daily_grab` (analog F008–F011: P4/Ops-Folgearbeit).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert. Rollback = Commit
zurücknehmen + `alembic downgrade -1` (getestet, s. o.).
