# F015 — Persona/Portfolio Seed

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

P4-Auftakt (ARCHITECTURE.md §8 P4 "Vollständiger Zyklus läuft automatisch für alle 6
Portfolios"): dafür müssen die 6 `persona`- und `portfolio`-Zeilen erstmal in der DB
existieren. Bisher gibt es nur einen Dev-Demo-Seed für VULTURE
(`scripts/seed_demo_snapshot.py`, F007, ausdrücklich "nicht Teil von Production Code").
Dieses Feature liefert den echten, idempotenten Seed für alle 6 Personas mit den
Werten aus `docs/adr/0001-alpaca-paper-account-limit.md` (3 native Alpaca-Accounts) und
`config/broker.yaml` (3 virtuelle `internal_ledger`-Personas) — Voraussetzung für den
LangGraph-Orchestrator (F016), der über echte `portfolio`-Zeilen fanoutet statt über
Test-Fixtures.

**Scope:** `persona` + `portfolio` Zeilen für alle 6 Personas, idempotent.
**Non-Scope:** keine Snapshots/Positionen (das bleibt F007s Demo-Seed bzw. kommt mit dem
Trading-Agenten), kein Scheduler, keine Charter-Prompt-Inhalte (kommen mit der
Persona-Analyse-Node in F016+).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Alle 6 Personas werden mit identischer Struktur angelegt (gleiches Startkapital 5.000 USD/Base-CCY, gleiche Snapshot-Kadenz vorbereitet) — kein Feld bevorzugt eine Persona. |
| #5 Paper/Live-Trennung | ja | `mode=PortfolioMode.PAPER` hart codiert für alle 6 — kein Parameter, der auf `LIVE` umschaltbar wäre; Live-Portfolios entstehen frühestens in P6 durch ein eigenes Feature. |
| #6 Secrets nie im Repo | ja | Die Alpaca-Account-IDs (`PA32N1PG3J5G` etc.) aus ADR-0001 sind Account-*Identifier*, keine Secrets (keine Keys/Passwörter) — analog dazu, wie `broker_account_ref` in F001 bereits für Order-Records verwendet wird. Für die virtuellen Personas gibt es gar keine Broker-Credentials (`internal_ledger`). |
| Idempotenz | ja | `get_or_create` je Persona/Portfolio über `name` bzw. `persona_id` (analog `scripts/seed_demo_snapshot.py`) — mehrfaches Ausführen erzeugt keine Duplikate. |
| Fehlende Alembic-Änderung nötig? | nein | Nutzt ausschließlich das bestehende Schema aus F003. |

**Design-Entscheidungen:**
- **`config_ref` zeigt auf `config/personas/<name>.yaml`** (bereits vorhandene Dateien
  aus P1/P2) — der Seed liest daraus `charter_version` und `model`, statt diese Werte
  im Seed-Skript zu duplizieren; ein Charter-Version-Bump in der YAML-Datei wird beim
  nächsten Seed-Lauf automatisch übernommen (`ON CONFLICT` aktualisiert `charter_version`
  + `model`, nicht nur Insert).
- **`broker_account_ref` je Adapter-Typ unterschiedlich befüllt:** native Personas
  bekommen die echte Alpaca-Account-ID aus ADR-0001; virtuelle Personas bekommen
  `"internal_ledger"` als Marker-String (kein echter Account, aber ein konsistenter,
  nicht-leerer Wert für `order_record.broker`-Zuordnung später).
- **Reine, testbare Funktion `seed_personas_and_portfolios(session)`** statt nur ein
  Skript — so ist der Seed auch aus dem künftigen Orchestrator-Bootstrap
  (F016) oder aus Tests aufrufbar, nicht nur manuell per CLI.

**Kosten:** keine LLM-Calls. **Fairness:** siehe oben, identische Struktur für alle 6.

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_persona_seed.py`:
1. `seed_personas_and_portfolios` auf leerer DB → genau 6 `Persona`- und 6
   `Portfolio`-Zeilen, Namen == `{VULTURE, HYPE, GUARDIAN, CHARTIST, CONTRA, CRYPTOR}`.
2. Alle 6 Portfolios: `mode == PAPER`, `start_value == 5000`.
3. VULTURE/GUARDIAN/CHARTIST: `broker_account_ref` == jeweilige Alpaca-Account-ID aus
   ADR-0001.
4. HYPE/CONTRA/CRYPTOR: `broker_account_ref == "internal_ledger"`.
5. Zweiter Aufruf (Idempotenz) → weiterhin genau 6 + 6 Zeilen, keine Duplikate.
6. Zweiter Aufruf mit geänderter `charter_version` in einer Persona-YAML (Fixture) →
   bestehende Zeile wird aktualisiert, keine neue Zeile.

## 4. Implementierung

`src/orchestrator/seed.py` (`seed_personas_and_portfolios`), liest
`config/broker.yaml` (Adapter-Zuordnung) + `config/personas/<name>.yaml`
(`charter_version`, `model`) + die ADR-0001-Account-IDs als Modul-Konstante
(`_NATIVE_ACCOUNT_IDS`, mit Verweis auf die ADR im Docstring statt einer neuen
Config-Datei — es sind exakt 3 feste Werte, keine Konfigurierbarkeit nötig).
`scripts/seed_personas.py` als dünner CLI-Wrapper (lädt `.env`, ruft die Funktion mit
einer echten Session auf, committet).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator -q` → 6 passed. `uv run pytest -q` (Gesamtsuite,
`-m 'not integration'`) → 258 passed, 2 deselected. `uv run ruff check`/
`ruff format --check` → sauber. `uv run mypy src/orchestrator` → sauber.

`uv run python scripts/seed_personas.py` gegen die lokale Postgres-Instanz
ausgeführt: 6 Personas + 6 Portfolios angelegt (VULTURE/GUARDIAN/CHARTIST mit den
echten Alpaca-Paper-Account-IDs, HYPE/CONTRA/CRYPTOR mit `internal_ledger`),
zweiter Lauf bestätigt idempotent (keine neuen Zeilen, `charter_version`/`model`
aktualisiert).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert. Rollback = Commit
zurücknehmen; die geseedeten `persona`/`portfolio`-Zeilen können bei Bedarf manuell
gelöscht werden (keine Migration, keine Fremd-Referenzen von anderen Features aus
diesem Zeitpunkt).
