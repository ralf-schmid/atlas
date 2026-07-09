# F043 — Kursziel/Stabilität-Kriterien über den Aktienfinder-Screener

Status: umgesetzt
Datum: 2026-07-09
Phase: 5

## 1. Zieldefinition

F041 hatte drei Kriterien aus Ralfs ursprünglicher Liste (Dividendenertrag,
Dividendenwachstum, Gewinnwachstum, Stabilität, Cashflow, Kursziel) als
Platzhalter-Selektoren in `config/ingestion.yaml` eingetragen — explizit als
unverifiziert markiert, da diese Session zu dem Zeitpunkt keinen Zugriff auf
Ralfs aktienfinder-Login hatte. Ralf hat jetzt `AKTIENFINDER_USER`/
`AKTIENFINDER_PASSWORD` lokal hinterlegt (`/goal neu analysieren und einbauen
wie geplant`) — dieses Feature verifiziert die Platzhalter live und baut die
tatsächlich verfügbaren Kriterien ein.

## 2. Kritische Betrachtung

**Live-Befund (gegen die echte, eingeloggte Seite geprüft):** Von den 3
Platzhaltern (`price_target`, `cashflow`, `quality_score_earnings_stability`)
existiert **keiner** als einfaches Feld auf der Profil-Seite
(`/aktien-profil/<isin>`):
- `Cashflow` kommt dort überhaupt nicht vor.
- `Kursziel` steckt nur in einem Tooltip-Fließtext ("... niedrigste Kursziel
  bei 130,00 EUR und das höchste Kursziel bei 290,00 EUR ...") — kein
  Einzelwert-Feld.
- Die Gewinnstabilität (0,91) steckt in einem AngularJS-`uib-tooltip`-Attribut,
  nicht in sichtbarem Text.

Alle drei existieren dagegen als saubere Tabellenspalten im separaten
Aktienfinder-Screener-Tool (`https://aktienfinder.net/aktienfinder`, ein
DataTables-Grid mit ca. 67 Spalten, u. a. "Kursziel", "Kursziel Rendite",
"Stabilität Gewinn", "Stabilität CashFlow", "Stabilität Dividende"). Jede
Zeile enthält die ISIN, und das Grid hat eine per-ID adressierbare globale
Suche (`#SecuritiesTable_filter input[type=search]`), die client-seitig auf
eine ISIN filtert — kein Full-Table-Scrape/Pagination-Handling nötig.

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Gleicher gemeinsamer Sync-Pfad (`aktienfinder_snapshot.fields`), keine Persona bekommt exklusiven Zugriff. |
| Keine LLM-Berechnung von Kennzahlen | nein | Reine DOM-Extraktion, keine Interpretation im Code. |
| Zeitschriften-/aktienfinder-Volltexte nicht in UI/Repo | nein | Nur einzelne Kennzahlen-Werte (Zahlen/Prozent), kein Fließtext. |

**Design-Entscheidungen:**
- **Neuer, eigener Extraktionspfad (`screener_fields`/`extract_screener_row`)
  statt Erweiterung von `field_selectors`.** Die Profil-Seiten-Selektoren
  (`extract_snapshot`) sind reine CSS-Selektor-Strings gegen eine
  Playwright-`Page`; das Screener-Grid braucht dagegen einen Ablauf
  (Suchfeld befüllen → warten → Zeile lesen → Spalten per Header-Text
  zuordnen) — passt nicht in den bestehenden `selector: str`-Contract.
- **Spalten werden per Header-Text zugeordnet, nicht per festem Index.** Das
  Grid hat sichtbar konfigurierbare Spalten (viele Checkboxen für
  Spalten-Sichtbarkeit im UI beobachtet) — ein harter Index wäre bei
  Neuanordnung/Deaktivierung einzelner Spalten in Ralfs Account still falsch
  zugeordnet worden. `_map_screener_row` liest `<th>`-Texte bei jedem Aufruf
  frisch und schlägt `screener_fields`-Namen (`config/ingestion.yaml`) exakt
  nach — live gegen zwei reale Aktien (SAP, Apple) verifiziert, auch mit
  künstlich vertauschter Spaltenreihenfolge unit-getestet. Kein Header
  gefunden → `None` statt eines falsch zugeordneten Werts.
- **Ein Navigations-Aufruf für alle Kandidaten-ISINs**, nicht einer pro ISIN:
  das Grid bleibt geladen, nur das Suchfeld wird pro ISIN neu befüllt
  (client-seitiges Filtern, kein Page-Reload) — günstiger als N zusätzliche
  Navigationen.
- **`cashflow` wird nicht als absoluter Betrag abgebildet.** Es gibt keine
  Einzelspalte mit einem Cashflow-Euro-Betrag, nur Wachstums-/
  Stabilitäts-/Fairer-Wert-Ableitungen davon. Um im Stil der bereits
  bestehenden `quality_score_*`-Familie (Dividendenertrag/-wachstum,
  Gewinnwachstum) zu bleiben, wird `quality_score_cashflow_stability` (Spalte
  "Stabilität CashFlow", 0–1-Skala) ergänzt — konsistent mit dem bereits
  vorhandenen `quality_score_earnings_stability` (Spalte "Stabilität
  Gewinn"). Deckt Ralfs "Stabilität"/"CashFlow"-Kriterien inhaltlich ab, ohne
  eine nicht vorhandene Kennzahl zu erfinden.
- **`price_target_upside_pct`** ("Kursziel Rendite") zusätzlich zu
  `price_target` mitgenommen — dieselbe Spalten-Extraktion, keine
  Zusatzkosten, und direkt nützlich für eine Persona, die den Kursziel-Wert
  im Verhältnis zum aktuellen Kurs einordnen will.
- **Fehlende Zeile (0 oder >1 Treffer beim Ohnehin unwahrscheinlichen Fall
  einer nicht getrackten ISIN) → alle Felder `None`**, kein Fehlschlag des
  gesamten Grabs — gleiche Partial-Snapshot-Philosophie wie
  `extract_snapshot` (F012).

**Kosten:** keine. **Fairness:** unverändert (gleicher gemeinsamer
Sync-Pfad).

## 3. Testdefinition

`tests/ingestion/test_aktienfinder_grabbing.py` (6 neue Tests):
1. `_map_screener_row` ordnet Header→Zelle korrekt per Text zu.
2. Robust gegen vertauschte Spaltenreihenfolge (künstlich vertauschte
   Header-/Zellen-Listen).
3. Unbekannter Header → `None` für das betroffene Feld.
4. `cells=None` (keine eindeutige Zeile gefunden) → alle Felder `None`.
5. `_merge_fields` kombiniert Snapshot- und Screener-Felder.
6. `_merge_fields` mit leerem Extra-Dict gibt den Snapshot unverändert
   zurück.

Playwright-Teil (`extract_screener_row`, `run_daily_grab_live`-Verdrahtung)
ist wie der Rest des Profil-Seiten-Pfads nicht unit-, sondern live getestet
(kein Browser im Standard-Testlauf, siehe Moduldocstring).

## 4. Implementierung

- `src/ingestion/aktienfinder_grabbing.py`: `_map_screener_row` (pure
  Header/Zellen-Zuordnung), `extract_screener_row` (Playwright-I/O:
  Suchfeld befüllen, Zeile lesen), `_merge_fields` (Snapshot +
  Screener-Felder kombinieren). `run_daily_grab_live` navigiert nach dem
  Login einmalig zu `/aktienfinder`, sammelt Screener-Felder je ISIN, merged
  sie in die bestehenden `grab_isin_snapshot`-Ergebnisse.
- `config/ingestion.yaml`: `aktienfinder.field_selectors` um die 3 nicht
  funktionierenden Platzhalter bereinigt; neue `aktienfinder.screener_fields`
  (`price_target`, `price_target_upside_pct`,
  `quality_score_earnings_stability`, `quality_score_cashflow_stability`).
- Kein neues DB-Feld/keine Migration nötig — `aktienfinder_snapshot.fields`
  ist bereits JSONB (F012), nimmt die neuen Keys ohne Schema-Änderung auf.

## 5. Test & Rollout

- `uv run pytest` (voller Lauf, mit lokalem Test-Postgres): 455 passed.
  `ruff check`/`format --check`, `mypy`: clean.
- **Live verifiziert** (echter Login, echte Kandidaten-ISINs SAP + Apple über
  den vollständigen `run_daily_grab_live`-Pfad, DB-Sync lokal gestubbt):
  beide liefern alle 4 neuen Felder korrekt befüllt (SAP: Kursziel 207.79
  EUR/50.6 % Rendite, Stabilität Gewinn 0.91, Stabilität CashFlow 0.88;
  Apple: Kursziel 278.04 EUR/1.4 % Rendite, Stabilität Gewinn 0.96,
  Stabilität CashFlow 0.97) — bereits bestehende Felder (Kurs,
  Dividendenrendite, die 3 Quality-Scores, Dividenden-Historie) unverändert
  korrekt.
- Deployment: rsync + `docker compose build scheduler` + `up -d` (kein neuer
  Service, kein neuer Container-Typ betroffen).
- **Offener Punkt (nicht Teil dieses Features, separat zu klären):** Ralfs
  lokale `.env` nutzt `AKTIENFINDER_USER`, `config/ingestion.yaml`/
  `.env.example` erwarten `AKTIENFINDER_USERNAME` — der produktive
  Scheduler-Pfad (`run_daily_grab_configured` → `_require_env`) würde mit dem
  aktuellen lokalen Namen die Variable nicht finden. Betrifft die Box-`.env`
  nicht zwangsläufig (dort ggf. anders benannt) — vor dem nächsten
  geplanten `aktienfinder`-Job-Lauf auf der Box zu prüfen.
- **Rollback-Pfad:** reiner Code-/Config-Revert (kein Schema-Impact) — bei
  Bedarf `screener_fields` in `config/ingestion.yaml` auf `{}` setzen, dann
  überspringt `run_daily_grab_live` den Screener-Teil komplett.
