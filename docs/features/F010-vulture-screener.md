# F010 — VULTURE-Screener

Status: umgesetzt
Datum: 2026-07-05
Phase: 3

## 1. Zieldefinition

P3-DoD-Punkt "VULTURE-Screener liefert täglich eine Kandidatenliste mit definierten
Feldern" (ARCHITECTURE.md §8/§3.5.3): das komplette tradable/aktive Alpaca-Universum
(`GET /v2/assets`, kein Whitelisting) auf Preis < 5 $ filtern, Mindestvolumen dabei nur
als Datenqualitätsfilter (nicht als Handelsverbot) — sonst müsste ein LLM 10.000+
Symbole durchsuchen und Token verbrennen.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness / kein Informationsvorsprung | ja | Genau ein Screener-Lauf pro Tag, Ergebnis landet in einer für alle Personas gleichermaßen lesbaren Tabelle (`screener_result`) — keine VULTURE-exklusive Vorfilterung im Agenten-Code, das Filtern passiert einmalig hier in Code, nicht pro Persona. |
| "Mindestvolumen als Datenqualitäts-, nicht Verbotsfilter" (§3.5.3, wörtlich) | ja | `min_volume` filtert nur die Kandidatenliste dieses Screener-Laufs (schließt Symbole mit unzuverlässigen/fehlenden Daten aus); es gibt keinen Code-Pfad, der einen Kauf unterhalb dieser Schwelle verbietet — das bleibt Sache des Risk-Gates (`src/risk`), das dieses Feature nicht anfasst. |
| Idempotenz aller Ingestion-Jobs (P3-DoD Punkt 6) | ja | `sync_screener_results` upsertet über `UniqueConstraint(symbol, screened_at)` — ein erneuter Lauf für denselben Tag überschreibt nur, dupliziert nicht. |

**Design-Entscheidungen:**
- **Getrennt von F008 (Marktdaten-Sync):** F008 pflegt Bars für eine kuratierte
  Watchlist (für Indikatoren); der Screener braucht stattdessen eine einmalige,
  günstige Momentaufnahme über das *gesamte* Universum — dafür Alpacas
  Snapshot-Endpoint (`get_stock_snapshot`, liefert Latest-Trade + Daily-Bar in einem
  Call je Symbol-Batch) statt einzelner Bar-Requests pro Symbol. Batches zu 500
  Symbolen (`_SNAPSHOT_BATCH_SIZE`), um die Request-URL-Länge unter gängigen
  Server-Limits zu halten — kein von Alpaca dokumentiertes Hard-Limit bekannt, aber
  ein konservativer, unauffälliger Wert.
- **Neue Tabelle `screener_result`**: `(symbol, screened_at)` eindeutig, `price`,
  `volume`. Bewusst kein Verweis auf `research_item` — der Screener liefert Rohdaten,
  keine Agenten-Interpretation (P4 macht daraus research_items).
- **Symbole ohne vollständige Snapshot-Daten** (`latest_trade`/`daily_bar` fehlt, z. B.
  bei Halts/neu gelisteten Werten) werden übersprungen statt mit `None`-Werten
  aufgenommen — konsistent mit dem Datenqualitäts-Gedanken des Volumenfilters.

**Kosten:** keine LLM-Calls. **Fairness:** ein Screener-Lauf, ein Ergebnis-Datensatz
für alle Personas.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/ingestion/test_vulture_screener.py`), Alpaca-Clients gemockt:

1. `AlpacaAssetUniverseProvider` liefert nur `tradable=True`-Symbole.
2. `AlpacaSnapshotProvider` mappt vollständige Snapshots korrekt, überspringt
   Symbole ohne `latest_trade`/`daily_bar`.
3. `run_screener` filtert nach Preis < `max_price` UND Volumen ≥ `min_volume`.
4. `run_screener` liefert `[]` für ein leeres Universum (kein Snapshot-Call nötig).
5. `sync_screener_results` mit leerer Liste → `0`.
6. `sync_screener_results` zweimal für denselben Tag mit unterschiedlichen Werten →
   genau eine Zeile je Symbol, mit den Werten des zweiten Laufs (Idempotenz-Nachweis).
7. `run_daily_screener` liest Config + Env korrekt und ruft den Screener auf.
8. `run_daily_screener` wirft eine klare `ValueError`, wenn die Env-Var fehlt.

## 4. Implementierung

`src/ingestion/vulture_screener.py` (`Snapshot`, `AssetUniverseProvider`,
`SnapshotProvider`, `AlpacaAssetUniverseProvider`, `AlpacaSnapshotProvider`,
`run_screener`, `sync_screener_results`, `run_daily_screener`), `src/db/models.py`
(`ScreenerResult`), Migration
`alembic/versions/ce4f6d238812_add_screener_result.py`, `config/ingestion.yaml`
(`vulture_screener`-Sektion, wiederverwendet dieselben Alpaca-Market-Data-Keys wie
F008/`broker.yaml`).

## 5. Testdurchlauf

`uv run pytest tests/ingestion -q` → 24 passed (7 F008 + 9 F009 + 8 F010).
`uv run pytest -q` (Gesamtsuite) → 210 passed. `uv run ruff check`/`ruff format --check`
→ sauber. `uv run mypy src/ingestion` → sauber. Migration im
upgrade→downgrade→upgrade-Zyklus verifiziert.

**Noch offen:** `run_daily_screener` ist noch nirgends automatisch geplant (gleiche
P4/Ops-Folgearbeit wie F008/F009).

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert. Rollback = Commit
zurücknehmen + `alembic downgrade -1` (getestet, s. o.).
