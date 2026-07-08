# F042 — Verwaiste `publication_article`-Zeilen beim Re-Sync

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

Beim Live-Vergleich der F038-verbesserten Extraktion gegen eine bereits
verarbeitete Ausgabe (Ralfs Auftrag: "führe die optimierte Analyse der
Zeitschrift durch") sollte die Artikel-Zeilenzahl für `2026-07-07` von 874
(alter, F038-loser Lauf) auf die vom neuen Parser tatsächlich extrahierten 212
sinken. Sie blieb aber bei 874 — 662 verwaiste Alt-Zeilen blieben in der DB
und wären dauerhaft Teil des Research-Pools geblieben.

## 2. Kritische Betrachtung

**Root Cause:** `extract_articles()` (F038) vergibt `seq` während des Walks,
**bevor** der Mindestlängen-Filter greift (`return [a for a in articles if
len(a.text) >= _MIN_ARTICLE_BODY_LENGTH]`) — die überlebenden Artikel behalten
ihre ursprünglichen, nicht-zusammenhängenden `seq`-Werte aus dem
Rohdurchlauf (z. B. 11, 15, ..., 520 statt 0..211). `sync_publication_articles`
machte reinen Upsert über `(publication, issue_date, seq)` — traf ein neuer
Lauf zufällig weniger oder andere `seq`-Werte als ein vorheriger (z. B. weil
sich die Heuristik geändert hat), blieben alle Alt-Zeilen mit nicht
getroffenen `seq`-Werten für immer als Karteileichen liegen. Kein
F038-spezifischer Bug — hätte auch jede künftige Heuristik-Änderung oder ein
erneuter Lauf nach korrigierter PDF-Datei getroffen.

| Invariante | Berührt? | Umgang |
|---|---|---|
| Datengrundlage-Korrektheit für alle Personas gleich (#10 Fairness, mittelbar) | ja | Verwaiste Zeilen verzerren den gemeinsamen Research-Pool für alle Personas gleichermaßen falsch — kein Fairness-Verstoß im engeren Sinn, aber eine echte Datenqualitäts-Regression. |

**Design-Entscheidung:** `sync_publication_articles` löscht jetzt vor dem
Insert alle bestehenden Zeilen für `(publication, issue_date)` und fügt den
kompletten neuen Satz frisch ein (kein Upsert mehr nötig) — ein erneuter Lauf
ersetzt eine Ausgabe immer vollständig, keine Karteileichen möglich. Ein
leerer `articles`-Input (z. B. bei einem defekten PDF) löscht **nicht** —
bleibt ein bewusster No-op, um bestehende, gültige Daten nicht durch einen
transienten Extraktionsfehler zu verlieren. Keine FK-Referenzen auf diese
Tabelle (research_item speichert nur einen String-Verweis, kein FK) — Löschen
ist sicher.

**Kosten:** keine. **Fairness:** unverändert (behebt eine Datenqualitäts-,
keine Fairness-Lücke).

## 3. Testdefinition

`tests/ingestion/test_publications_pipeline.py` (2 neue Tests):
1. Ein zweiter Lauf mit weniger/anderen `seq`-Werten als der erste entfernt
   die nicht mehr getroffenen Alt-Zeilen vollständig.
2. Ein leerer `articles`-Input lässt bestehende Zeilen unangetastet (Contract
   für den "defektes PDF"-Fall).

## 4. Implementierung

- `src/ingestion/publications_pipeline.py`: `sync_publication_articles` von
  Upsert (`on_conflict_do_update`) auf Delete-then-Insert umgestellt.

## 5. Test & Rollout

- `uv run pytest` (voller Lauf): 443 passed. `ruff`/`mypy`: clean.
- Deployment: rsync + `docker compose build api scheduler` + `up -d`.
- Live verifiziert: beide bereits eingelesenen Ausgaben (`2026-07-07`,
  `2026-07-08`) erneut verarbeitet → `publication_article`-Zeilenzahl je
  Ausgabe jetzt exakt gleich der von `extract_articles` zurückgegebenen
  Artikel-Anzahl (212 bzw. 203), keine Karteileichen mehr (per SQL geprüft).
- **Rollback-Pfad:** reiner Code-Revert (keine Schema-/Migrations-Änderung).
