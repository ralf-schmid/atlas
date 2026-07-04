# F003 — DB-Schema: persona/portfolio/cycle/research_item/decision/order_record

Status: in Umsetzung
Datum: 2026-07-04
Phase: 2

## 1. Zieldefinition

PostgreSQL-Schema (SQLAlchemy-Modelle + Alembic-Migration) für die Data-Lineage-Kette
Persona → Portfolio → Cycle → Research-Item → **Decision** → **Order-Record** aus
ARCHITECTURE.md §3.6. Ralf hat explizit `decision` und `order_record` angefragt; die vier
referenzierten Eltern-Tabellen (`persona`, `portfolio`, `cycle`, `research_item`) werden als
schlanke Stubs mitgebaut, damit deren Foreign Keys echt sind statt ins Leere zu laufen
(mit Ralf abgestimmt).

**Nicht Teil dieses Features** (bewusst abgegrenzt, spätere Features): `agent_run`,
`position_snapshot`, `portfolio_snapshot`, `review`, `cost_ledger`. Auch keine Seed-Daten
(die 6 Personas werden nicht in dieser Migration angelegt — das ist Aufgabe eines
Config-Loaders, der `config/personas/*.yaml` in die `persona`-Tabelle einliest und noch
nicht existiert).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate deterministisch | ja | `decision.risk_check` (JSONB) persistiert die ausgewerteten Regeln — die Spalte existiert, die Risk-Gate-Logik selbst ist ein späteres Feature (`src/risk`). |
| #3 Keine Order ohne persistierte Decision | ja | `order_record.decision_id` ist `NOT NULL` **und** echter Foreign Key auf `decision.id` — auf DB-Ebene erzwungen, nicht nur Anwendungslogik. |
| Lineage (`input_research_ids[]` Pflicht) | ja | `decision.input_research_ids` ist `ARRAY(UUID) NOT NULL` mit `CHECK`-Constraint (nicht leer). Die **Existenz** der referenzierten `research_item`-Zeilen kann Postgres bei einer Array-Spalte nicht nativ per Foreign Key prüfen (das bräuchte einen Trigger oder eine Normalisierung in eine Join-Tabelle). ARCHITECTURE.md Zeile 219 sagt explizit "Persistenz-Layer validiert Existenz" — das ist hier als Anwendungs-Funktion (`validate_research_ids_exist`, `src/db/validation.py`) umgesetzt, die vor jedem Insert läuft, nicht als DB-Constraint. Dokumentiert als bewusste, spezifikationskonforme Entscheidung. |
| #6 Secrets nie im Repo | ja | `DATABASE_URL` aus Environment, Dummy-Wert in `.env.example` passt zu `docker-compose.yml`. |
| Reject-Idea-Persistenz (Kernprinzip 3) | ja | `decision.rejection_reason` existiert, `action` erlaubt `reject_idea`; kein separates Reject-Modell nötig. |

**Design-Entscheidungen, die ARCHITECTURE.md §3.6 nicht wörtlich festlegt** (rein technisch,
hier dokumentiert statt einzeln nachgefragt):
- **Primärschlüssel:** `UUID` (Python-seitig `uuid4()`), konsistent mit den bereits
  verwendeten Alpaca-Order-IDs im Broker-Layer (F001/F002).
- **`decision.status`**: eigenes Enum `pending, risk_rejected, hitl_pending, hitl_rejected,
  approved, executed, recorded` (`recorded` für `reject_idea`/`hold`, die keine Order
  auslösen). Nicht in ARCHITECTURE.md enumeriert — Vorschlag, anpassbar.
- **`order_record.status`**: reduziertes Enum `new, filled, partially_filled, canceled,
  rejected, expired` statt des vollen Alpaca-`OrderStatus`-Enums (18 Werte, viele
  Alpaca-spezifisch/irrelevant für `InternalLedgerAdapter`-Fills). Der volle Broker-Payload
  bleibt in `order_record.raw` (JSONB) erhalten — nichts geht verloren, nur die normalisierte
  `status`-Spalte ist bewusst schlanker.
- **`decision.quantity`**: `NULL` erlaubt (für `hold`/`reject_idea`, die keine Menge haben).

**Kosten:** keine LLM-Calls. **Fairness:** reines Schema, keine Persona-spezifische Logik.

## 3. Testdefinition (vor Umsetzung)

Integrationstests (`tests/db/`) gegen echtes Postgres (`docker-compose.yml`, `pgvector/pgvector:pg16`):

1. Migration läuft sauber durch (`alembic upgrade head`) und ist idempotent (`downgrade` +
   erneutes `upgrade` funktioniert).
2. `order_record` ohne `decision_id` → `IntegrityError` (NOT NULL).
3. `order_record.decision_id` verweist auf nicht-existierende `decision.id` → `IntegrityError`
   (Foreign Key).
4. `decision` ohne `input_research_ids` bzw. mit leerem Array → `IntegrityError` (CHECK).
5. `validate_research_ids_exist()` wirft `ValueError`, wenn eine referenzierte
   `research_item`-ID nicht existiert; lässt gültige IDs durch.
6. Voller Lineage-Pfad: `persona` → `portfolio` → `cycle` → `research_item` → `decision`
   (referenziert das `research_item`) → `order_record` (referenziert die `decision`) lässt
   sich anlegen und per Join zurückverfolgen (spiegelt die in ARCHITECTURE.md geforderte
   Lineage-Query).
7. `decision.action = 'reject_idea'` mit `rejection_reason` gesetzt, ohne `order_record` —
   lässt sich anlegen (verworfene Ideen sind eigenständig persistiert, Kernprinzip 3).
8. Enum-Spalten (`portfolio.mode`, `cycle.market_session`, `decision.action`,
   `decision.status`, `order_record.status`) lehnen ungültige Werte ab.

## 4. Implementierung

`src/db/base.py` (Engine/Session aus `DATABASE_URL`), `src/db/models.py` (6 Modelle),
`src/db/validation.py` (`validate_research_ids_exist`), `alembic/` (Migration),
`docker-compose.yml` (Postgres+pgvector für lokale Entwicklung/Tests).

## 5. Testdurchlauf

**Abweichung vom Plan:** `docker-compose.yml` (Postgres+pgvector) existiert im Repo als
künftiges Deployment-Ziel, wurde für diesen Testlauf aber nicht verwendet — die
Lima/Docker-VM auf der Entwicklungsmaschine startete nicht (fehlende/inkompatible
`socket_vmnet`-Installation, aus Sicherheitsgründen von Lima nicht per Homebrew
unterstützt). Stattdessen: **natives Postgres 17 + pgvector via Homebrew**
(`brew install postgresql@17 pgvector`), lokal auf Port 5432, Rolle/DB `atlas`/`atlas`.
Funktional identisch zum späteren `docker-compose.yml`-Setup (gleiche Postgres-Major-Version,
gleiche pgvector-Extension); `docker-compose.yml` wurde von `pg16` auf `pg17` angepasst, um
konsistent zu bleiben.

Durchgeführt:
- `alembic upgrade head` → alle 6 Tabellen angelegt, verifiziert per `\dt`/`\dT`.
- Idempotenz-Zyklus manuell verifiziert: `upgrade head` → `downgrade base` →
  `upgrade head` — beim ersten Versuch schlug der zweite `upgrade` mit
  `DuplicateObject: type "market_session" already exists` fehl, weil Postgres-ENUM-Typen
  ein `DROP TABLE` überleben. Fix: `downgrade()` droppt jetzt explizit alle 5 ENUM-Typen
  (`sa.Enum(name=...).drop(...)`). Zyklus danach dreimal sauber wiederholt.
- `uv run pytest tests/db/ tests/broker/ --cov=src` → **48/48 grün, 100 % Line-Coverage**
  über `src/broker` und `src/db` zusammen. Isolation der DB-Tests über
  Connection+Transaction+Rollback pro Test (`tests/db/conftest.py`); Schema wird einmal
  pro Testsession via echtem Alembic-Migrationslauf auf- und abgebaut.
- `uv run ruff check` und `uv run mypy src/db` (strict) → beide sauber. Alembic-Revisionen
  sind vom Line-Length/Import-Lint ausgenommen (`pyproject.toml`
  `per-file-ignores` — maschinengeneriert, nicht von Hand formatiert).

Nicht gemacht: echter Test gegen `docker-compose.yml` selbst (kein laufendes Docker in
dieser Session) — Folgearbeit, sobald Docker auf der Maschine wieder funktioniert.

## 6. Rollback-Pfad

Additives Feature: neues `src/db/`-Paket, neue `alembic/`-Migration, neuer
`docker-compose.yml`. Kein bestehender Code betroffen (noch kein Agent/API nutzt die DB).
Rollback = `alembic downgrade base` + Commit zurücknehmen. Kein Config-Flag nötig.
