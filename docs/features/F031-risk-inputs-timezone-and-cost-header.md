# F031 — Trading-Day-Zeitzone + defensives Cost-Header-Parsing

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Security-Audit 2026-07-07, Finding P7 (zwei der drei Härtungs-Punkte; der dritte,
EUR/USD-Cap-Mismatch, ist als ADR dokumentiert, siehe `docs/adr/0004-cost-cap-currency-approximation.md`):

- **"trades today" zählte den UTC-Kalendertag, nicht den Handelstag der Persona**
  (`src/orchestrator/risk_inputs.py::_count_trades_today`) — ein Trade kurz vor/nach
  UTC-Mitternacht konnte dem falschen Tag zugerechnet werden (bei US-Aktien ET,
  UTC-4/-5, ein Fenster von 4-5 Stunden pro Tag).
- **LiteLLM-Cost-Header-Parsing wirft bei defektem Header nach bereits bezahltem
  Call** (`float(response.headers.get(...))` in `src/llm/client.py`) — der
  Ledger-Eintrag ginge verloren statt defensiv geloggt zu werden.

## 2. Kritische Betrachtung

**"trades today" — Wiederverwendung statt Neuberechnung:** `Cycle.trading_day`
wird vom Scheduler bereits korrekt in der Markt-Zeitzone berechnet (Commit
`6d63c18`, selber Audit-Tag) — dieser Fix betraf aber nur die Erstellung der
`Cycle`-Zeile selbst, nicht `_count_trades_today`, das weiterhin einen rohen
`now`-Zeitstempel UTC-Kalendertag-mäßig zerschnitt. Statt die Zeitzonen-Logik ein
zweites Mal zu implementieren, liest der Fix `Cycle.trading_day` +
`Cycle.market_session` (über die neue `cycle_id`-Signatur) und wandelt den
lokalen Mitternacht-Zeitpunkt der Markt-Zeitzone (`config/cycles.yaml` via
`load_cycles_config`) in UTC-Grenzen für den Datenbank-Vergleich um — eine Quelle
der Wahrheit für "welcher Handelstag ist das".

**Signatur-Änderung `now` → `cycle_id`:** `read_portfolio_risk_state` /
`_count_trades_today` brauchten „jetzt" nur für diese eine Grenzberechnung; mit
`cycle_id` ist das Ergebnis deterministisch an den tatsächlichen Zyklus gebunden
statt an einen zusätzlichen, separat mitgeführten Zeitstempel.

**Cost-Header — defensiv statt Ledger-Verlust:** `float(...)` bleibt der Regelfall
(LiteLLM ist ein vertrauter interner Dienst), aber ein `try/except` fängt einen
unparsebaren/fehlenden Wert ab, loggt ihn als Incident (`logger.error`, dieselbe
`src/logging_config.py`-Infrastruktur aus F029) und bucht `cost_usd=0.0` statt die
Ausnahme bis zum Aufrufer durchschlagen zu lassen und den kompletten
`cost_ledger`-Eintrag zu verlieren (Invariante 7: Kosten-Tracking darf nicht
lückenhaft werden, auch wenn ein einzelner Header kaputt ist).

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_risk_inputs.py`:
1. Bestehende Tests auf `cycle_id`-Signatur umgestellt (neuer Helper
   `_current_cycle_id`, getrennt von den historischen Order-Cycles).
2. Neu: eine Order kurz nach UTC-Mitternacht, aber noch im ET-Handelstag, zählt
   weiterhin zum richtigen `trading_day` (demonstriert exakt den Bug-Fix).

`tests/llm/test_client.py` (LiteLLM-Client):
3. Fehlender/defekter `x-litellm-response-cost`-Header → `cost_usd=0.0`, Response
   wird trotzdem zurückgegeben (kein verlorener Call), Incident geloggt.
4. Gültiger Header → unverändertes Verhalten (Regression).

## 4. Implementierung

`src/orchestrator/risk_inputs.py` (`_count_trades_today`/`_market_timezone`
via `cycle_id`), `src/orchestrator/persona_analysis.py` (Aufrufer angepasst,
`now`-Variable entfernt), `src/llm/client.py` (defensives Header-Parsing).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator tests/llm -q` → siehe Gesamtlauf in
`docs/dod/` bzw. Commit-Historie; keine Regression. `uv run mypy
src/orchestrator src/llm` → sauber. `uv run ruff check`/`ruff format --check` →
sauber.

## 6. Rollback-Pfad

Commit zurücknehmen. Additiv/Signatur-Change ohne Schema-Änderung — der einzige
Call-Site (`persona_analysis.py`) ist im selben Commit mit angepasst.
