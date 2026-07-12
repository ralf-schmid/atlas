# F071 — Positionsgrößen-Berechnung berücksichtigt bestehenden Bestand

Status: umgesetzt
Datum: 2026-07-12
Phase: 4

## 1. Zieldefinition

Bug-Fix (von Ralf per `/goal` gemeldet): Personas kommen über mehrere Zyklen
hinweg wiederholt auf dasselbe Instrument — legitim, wenn sich Wahrscheinlichkeiten
ändern oder neue Impulse hinzukommen (F021 unterstützt genau das: jeder Zyklus ist
eine unabhängige `buy`-Entscheidung). Der Sizing-Code (`decision_sizing.py` +
`persona_analysis._resolve_buy_decision`) berechnete die Positionsgröße bei jedem
`buy` jedoch komplett neu aus `conviction × max_position_pct × equity`, ohne einen
bereits gehaltenen Bestand im selben Instrument abzuziehen — und das Risk-Gate
(`evaluate_decision`) prüfte `max_position_pct` nur gegen den Wert der *neuen*
Order, nicht gegen den *Gesamtbestand* nach der Order. Ergebnis: wiederholte
`buy`-Entscheidungen auf demselben Symbol konnten die persona-eigene
`max_position_pct`-Obergrenze kumulativ überschreiten (Fehlallokation in der Höhe)
— genau das Gegenteil dessen, was F021 §1 dokumentiert
("`conviction=1.0` → exakt die persona-eigene Obergrenze ausgeschöpft, nie mehr").

Die eigentliche Bestandsbuchung beim Broker/Ledger (`InternalLedgerAdapter._apply_fill`)
war bereits korrekt (`total_qty = existing.qty + qty`, mengengewichteter
Einstandspreis) — der Fehler lag ausschließlich in der Sizing-/Risk-Gate-Schicht,
die den bestehenden Bestand beim *Berechnen* der neuen Order-Größe schlicht nicht
kannte.

**Fix, zwei Ebenen (beide nötig, siehe §2):**
1. **Sizing** (`decision_sizing.compute_incremental_buy_value_usd`): die
   bestehende `compute_position_value_usd` liefert weiterhin den
   *Ziel-Gesamtwert* der Position bei der gegebenen `conviction` (Formel
   unverändert, weiterhin wie in F021 spezifiziert). Neu: die tatsächlich zu
   kaufende Menge ist `target_position_value_usd - existing_position_value_usd`,
   nach unten auf 0 begrenzt (bereits voll bzw. übererfüllt → nichts zu kaufen →
   Fallback `reject_idea` mit `rejection_reason="position_already_at_target_size"`,
   kein Nullmengen-Order-Platzieren).
2. **Risk-Gate** (`evaluate_decision`, neuer optionaler Parameter
   `existing_position_value_usd`, Default `0.0` für Rückwärtskompatibilität): die
   `max_position_pct`-Regel prüft jetzt `existing_position_value_usd +
   position_value_usd` (Gesamtbestand nach der Order) gegen die Obergrenze, nicht
   mehr nur die neue Order isoliert. Das bleibt das eigentliche Sicherheitsnetz
   (Invariante #1) — unabhängig von Sizing-Bugs oder Kursbewegungen, die den
   bestehenden Bestand seit dem letzten Kauf über das Ziel hinaus haben wachsen
   lassen.

`PortfolioRiskState` (`risk_inputs.py`) trägt jetzt zusätzlich `positions:
list[Position]` — der ohnehin vorhandene `get_positions()`-Aufruf in
`read_portfolio_risk_state` wird wiederverwendet, kein zusätzlicher
Broker-Roundtrip.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate ist deterministischer Code | ja (Kern) | Die Korrektur ist reine Arithmetik in `evaluate_decision`/`decision_sizing.py`, kein LLM-Bezug. Das LLM liefert weiterhin nur `conviction`, keine USD-Beträge — es sieht `OPEN_POSITIONS` im Prompt (unverändert seit F021), aber die tatsächliche Verrechnung bleibt Code. |
| #10 Fairness | ja | Identischer Code-Pfad für alle 6 Personas — die Änderung sitzt in `evaluate_decision`/`decision_sizing.py`/`persona_analysis.py`, keine Persona-spezifische Sonderlogik. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | `compute_incremental_buy_value_usd` ist reine Funktion, kein LLM-Aufruf. |
| Rückwärtskompatibilität bestehender Aufrufer von `evaluate_decision` | ja | `existing_position_value_usd` ist ein optionaler Keyword-Parameter mit Default `0.0` — bestehende Tests/Aufrufer ohne Kenntnis des Parameters verhalten sich exakt wie vorher. |

**Kein ADR nötig:** keine Abweichung von ARCHITECTURE.md, keine
Sizing-*Formel*-Änderung (F021s `conviction × max_position_pct × equity` bleibt
exakt der Ziel-Gesamtwert) — nur eine Korrektur, wie das Ergebnis dieser Formel
mit bereits Vorhandenem verrechnet wird, bevor eine Order daraus wird.

**Kosten:** keine (kein zusätzlicher LLM-Call, kein zusätzlicher Broker-Call —
`positions` wird aus dem bereits vorhandenen `get_positions()`-Aufruf in
`read_portfolio_risk_state` wiederverwendet).

## 3. Testdefinition (vor Umsetzung)

`tests/orchestrator/test_decision_sizing.py`:
1. `compute_incremental_buy_value_usd` ohne bestehenden Bestand → voller
   Zielwert.
2. Mit teilweisem Bestand → nur die Differenz zum Ziel.
3. Bestand == Ziel → `0.0`.
4. Bestand > Ziel (z. B. Kursanstieg seit letztem Kauf) → `0.0`, nicht negativ.

`tests/risk/test_gate.py`:
5. Bestehender Bestand + neue Order zusammen über dem Limit → abgelehnt, obwohl
   die neue Order allein im Limit läge.
6. Bestehender Bestand + neue Order exakt am Limit → erlaubt.
7. `existing_position_value_usd` nicht angegeben → Default `0.0`, Verhalten wie
   vor F071 (Regressionsschutz für bestehende Aufrufer).

`tests/orchestrator/test_persona_analysis.py`:
8. `buy` auf ein bereits (teilweise) gehaltenes Instrument → Order-Menge ist nur
   die Differenz zum Ziel, `expected_outcome` trägt
   `existing_position_value_usd`/`target_position_value_usd`,
   `risk_check.rules_evaluated.max_position_pct.total_position_value_usd`
   entspricht dem vollen Zielwert.
9. `buy` auf ein Instrument, dessen bestehender Bestand bereits am/über dem Ziel
   liegt → `reject_idea` mit `rejection_reason="position_already_at_target_size"`,
   keine Order platziert.

## 4. Implementierung

`src/orchestrator/decision_sizing.py` (`compute_incremental_buy_value_usd`),
`src/risk/gate.py` (`existing_position_value_usd`-Parameter,
`max_position_pct`-Regel geändert), `src/orchestrator/risk_inputs.py`
(`PortfolioRiskState.positions`), `src/orchestrator/persona_analysis.py`
(`_resolve_buy_decision` verrechnet Bestand vor Risk-Gate-Aufruf).

## 5. Testdurchlauf

`uv run pytest tests/orchestrator/test_decision_sizing.py tests/risk/test_gate.py
tests/orchestrator/test_persona_analysis.py tests/orchestrator/test_risk_inputs.py -q`
→ **87 passed** (echte lokale Postgres-Instanz). `uv run pytest -q -m 'not
integration'` (Gesamtsuite) → **578 passed, 15 deselected**. `uv run pytest -q -m
integration` → **13 passed, 2 skipped**. `uv run pytest tests/risk/
--cov=src/risk --cov-branch` → **52 passed, 100% Line- und Branch-Coverage**
(Pflicht-Kriterium für `src/risk`, unverändert erfüllt). `uv run ruff check` /
`uv run ruff format --check` / `uv run mypy src/risk src/orchestrator src/broker
src/db` → alle sauber.

## 6. Rollback-Pfad

Reiner Code-Fix ohne Schema-/Config-Änderung. Rollback = Commit zurücknehmen —
`existing_position_value_usd` fällt auf den Default `0.0` zurück (Vor-F071-
Verhalten), keine Migration nötig.

## 7. Nachtrag (12.07.2026): Test-Coverage- und Doku-Audit

Auf Ralfs Auftrag geprüft: sind die neuen Funktionen vollständig testabgedeckt,
und bildet die Dokumentation die Realität ab?

**Test-Coverage** (`--cov-branch`, echte lokale Postgres-Instanz):
- `src/orchestrator/decision_sizing.py` (inkl. neuer
  `compute_incremental_buy_value_usd`): **100 % Line + Branch**.
- `src/risk/gate.py` (inkl. neuem `existing_position_value_usd`-Pfad): **100 %
  Line + Branch** — deckt sich mit dem Pflicht-Kriterium für `src/risk` aus
  CLAUDE.md.
- `src/orchestrator/risk_inputs.py` (neues `PortfolioRiskState.positions`-Feld):
  **95 %** — die einzige fehlende Zeile (`_market_timezone`, CRYPTO-Zweig) ist
  vorbestehend und nicht Teil dieser Änderung.
- `src/orchestrator/persona_analysis.py`: **93 %** — alle Zeilen der F071-Änderung
  selbst (Bestandsabgleich, Top-up-Sizing, `position_already_at_target_size`-
  Fallback, Persistenz der neuen `expected_outcome`-Felder) sind durch die zwei
  neuen Integrationstests abgedeckt; die verbleibenden Lücken (`BudgetExceededError`-
  Handler, `unsupported_action`-Fallback u. Ä.) sind vorbestehend und nicht Teil
  dieser Änderung (`src/orchestrator` unterliegt laut CLAUDE.md keiner
  Pflicht-Coverage-Schwelle wie `src/risk`/`src/broker`).

**Doku-Konsistenz:** `ARCHITECTURE.md` §3.6 (ER-Übersicht) listete für
`decision.expected_outcome` ein Beispielschema (`{target_price, horizon_days,
stop_loss, confidence}`), das schon vor F071 nicht mit dem tatsächlich
persistierten JSONB übereinstimmte (Code seit F021: `entry_price`,
`stop_loss_price`, `conviction`) — und durch F071s zwei neue Felder
(`existing_position_value_usd`, `target_position_value_usd`) noch weiter
divergiert wäre. Korrigiert auf die tatsächlichen Feldnamen. Alle übrigen
Fundstellen von `position_value_usd`/`Sizing-Formel`/`max_position_pct` in
`docs/features/` (F004, F018, F021, F033, F051, F052) beschreiben entweder
unverändertes Verhalten (`compute_position_value_usd` selbst, das
Risk-Gate-Timing relativ zur Rundung) oder sind — wie in diesem Projekt üblich
(siehe F031 vs. F020) — bewusst unangetastete historische Snapshots, auf die
dieses Dokument verweist, statt sie rückwirkend zu überschreiben. `CLAUDE.md`
enthält keine Sizing-Formel-Aussage, die zu korrigieren wäre.
`docs/dod/phase-4.md` bekam einen kurzen Nachtrag (siehe dort) analog zum
bestehenden F049–F061-Muster für live gemeldete Korrekturen.
