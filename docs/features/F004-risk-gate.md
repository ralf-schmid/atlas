# F004 — Risk-Gate (deterministisches Zwei-Ebenen-Regelwerk)

Status: in Umsetzung
Datum: 2026-07-05
Phase: 2

## 1. Zieldefinition

Deterministisches, LLM-freies Risk-Gate (`src/risk/`) das jede `buy`/`sell`/`close`-Decision
gegen die zwei Guardrail-Ebenen aus ARCHITECTURE.md §6 prüft: systemweit
(`config/risk.yaml`, unveränderlich durch Personas) und persona-spezifisch
(`config/personas/<name>.yaml`). Bei Konflikt gilt die strengere Regel. Ergebnis ist ein
`RiskCheckResult` (approved/rejected + `rules_evaluated`), das 1:1 in `decision.risk_check`
(JSONB) persistiert werden kann. **Kein LLM-Aufruf, keine Netzwerk-/DB-Seiteneffekte** in
der Kernfunktion `evaluate_decision()` — reine, deterministische Funktion, damit
100%-Branch-Coverage überhaupt sinnvoll möglich ist.

**Nicht Teil dieses Features:** Anbindung an den (noch nicht existierenden) Handels-Agenten;
Kosten-Guardrail/`cost_ledger`-Enforcement (§6.3, eigenständige Zähler-Logik, nicht
Teil des Trade-Risk-Gates); Universums-Filterung (`tradable=true`, kein Whitelisting —
das ist Screener-Logik, keine Order-Prüfung).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #1 Risk-Gate deterministisch | ja | Kernfunktion ist eine reine Funktion ohne LLM/IO — Aufrufer (später: Handels-Agent) liefert alle Zahlen (Portfolio-Zustand, Preise) als Parameter. |
| #8 Circuit Breaker >15% Drawdown | ja | `evaluate_decision` lehnt jede `buy`-Decision ab, wenn `drawdown > circuit_breaker_drawdown_pct`; `sell`/`close` bleiben erlaubt (Portfolio soll Risiko abbauen können — "sell_only"). Reset ist laut Spec nur manuell (Telegram) — hier nicht Teil der reinen Gate-Funktion, sondern der künftigen Persistenzschicht (`portfolio.circuit_breaker_reset_at` o.ä., **nicht in diesem Feature**, da noch keine Portfolio-State-Machine existiert). |
| Kein Margin/Leverage/Short | ja | `allow_margin`/`allow_short` sind systemweite Schalter (`config/risk.yaml`), aktuell `false`. Aufweichung nur per ADR + Config-Deploy, wie in §6.1 gefordert — der Code selbst ändert diese Werte nie. |
| Persona-Guardrails bei Konflikt → strengere Regel | ja | Für Obergrenzen (`max_position_pct`, `max_trades_per_day`, `max_open_positions`) wird `min(persona, system_ceiling)` verwendet; für Untergrenzen (`min_cash_pct`) `max(persona, system_floor)` (aktuell kein system-seitiger Floor definiert, `system_floor=0`). |
| Reject-Gründe sichtbar (§6.2) | ja | `rules_evaluated` enthält für **jede** geprüfte Regel Input-Werte + Ergebnis (nicht nur die verletzte) — Grundlage für UI/Grafana-Anzeige, die noch nicht existiert. |

**Design-Entscheidungen, die ARCHITECTURE.md nicht wörtlich festlegt** (dokumentiert statt
einzeln nachgefragt, da `/goal`-Modus aktiv):
- **`CRYPTOR.max_open_positions`**: ARCHITECTURE.md §4.6 nennt für CRYPTOR keine Zahl
  (nur "kleines Universum" als Begründung, warum kein Limit nötig scheint). In
  `config/personas/cryptor.yaml` auf `null` gesetzt → Risk-Gate verwendet dann nur die
  systemweite Ceiling (30). **Bitte von Ralf gegenprüfen/fixieren**, das ist eine echte
  Lücke in der Spezifikation, keine Erfindung meinerseits.
- **Stop-Loss-Policy-Typen:** zwei Typen. `fixed` (VULTURE, HYPE, GUARDIAN, CONTRA,
  CRYPTOR): der genannte Prozentwert (z. B. "-25%") wird als **Obergrenze** interpretiert
  (Stop darf enger, nicht weiter). `atr` (CHARTIST): "2×ATR14, mindestens -8%" wird als
  **Untergrenze** interpretiert (Stop-Distanz darf nicht enger als 8% sein, unabhängig vom
  ATR-Wert) — schützt vor zu engen Stops in ruhigen Marktphasen. Für den ATR-Typ gibt es
  keine Obergrenze, da die Spec keine nennt.
- **Systemweite Ceilings** (`config/risk.yaml`): `max_position_pct_ceiling=0.25`,
  `max_trades_per_day_ceiling=15`, `max_open_positions_ceiling=30` — bewusst oberhalb aller
  aktuellen Persona-Werte gewählt (reines Sicherheitsnetz gegen fehlerhafte
  Persona-Config-Änderungen, bindet unter heutigen Configs nirgends). `circuit_breaker_drawdown_pct=0.15`
  ist keine Ceiling, sondern der exakte Spec-Wert.
- **Handels-Umfang des Gates:** `buy` durchläuft alle Checks (Circuit-Breaker, Trade-Count,
  Margin, Positionsgröße, Cash-Reserve, Stop-Loss-Policy). `sell`/`close` durchlaufen nur
  den Trade-Count-Check — sie reduzieren Risiko und sollen auch im `sell_only`-Zustand
  möglich bleiben.

**Kosten:** keine LLM-Calls. **Fairness:** identischer Code-Pfad für alle 6 Personas,
nur die geladene Config unterscheidet sich (persona-neutral, Invariante 10).

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/risk/`), reine Funktionsaufrufe, keine DB/Netzwerk. Ziel:
**100% Branch-Coverage** (`pytest --cov-branch`, Pflicht laut CLAUDE.md).

1. `buy` unterhalb aller Limits → `approved=True`, alle Regeln in `rules_evaluated` mit `ok=True`.
2. Circuit Breaker: `drawdown > 15%` + `buy` → abgelehnt; `drawdown > 15%` + `sell`/`close` → weiterhin erlaubt.
3. `trades_today_count >= max_trades_per_day` → abgelehnt (für `buy` **und** `sell`).
4. `buy`-Kosten > verfügbares Cash (kein Margin) → abgelehnt.
5. Positionsgröße > `min(persona.max_position_pct, system_ceiling)` → abgelehnt; Grenzfall exakt am Limit → erlaubt.
6. `open_positions_count >= min(persona.max_open_positions, system_ceiling)` → abgelehnt; `persona.max_open_positions = None` (CRYPTOR-Fall) nutzt nur die Ceiling.
7. Verbleibendes Cash nach Kauf < `persona.min_cash_pct` → abgelehnt (GUARDIAN-Fall); bei Personas mit `min_cash_pct=0` nie bindend.
8. Stop-Loss-Richtung ungültig (`stop_loss_price >= entry_price` bei `buy`) → abgelehnt.
9. `fixed`-Policy: Stop weiter als erlaubte Obergrenze → abgelehnt; exakt am Limit → erlaubt; enger als Limit → erlaubt.
10. `atr`-Policy: Stop enger als `2×ATR14`-Untergrenze (bzw. enger als die 8%-Untergrenze bei niedrigem ATR) → abgelehnt; `atr14=None` bei einer Persona mit `atr`-Policy → abgelehnt (`atr_required_but_missing`).
11. Mehrere Regeln gleichzeitig verletzt → alle Verletzungen erscheinen in `rejection_reasons`, nicht nur die erste (kein frühes Aussteigen bei der Auswertung, nur bei der Entscheidung `approved`).
12. Config-Loading: `config/risk.yaml` + alle 6 `config/personas/*.yaml` laden ohne Fehler und ergeben die in §4.1–4.6 dokumentierten Werte.

## 4. Implementierung

`src/risk/models.py` (Dataclasses), `src/risk/config.py` (YAML-Loader),
`src/risk/gate.py` (`evaluate_decision`), `config/risk.yaml`, `config/personas/*.yaml`.

## 5. Testdurchlauf

`uv run pytest tests/risk/ --cov=src/risk --cov-branch` → **46/46 grün, 100% Branch-Coverage**
(Pflicht-Kriterium für `src/risk`, CLAUDE.md). `branch = true` dauerhaft in
`[tool.coverage.run]` (`pyproject.toml`) ergänzt, damit das künftig nicht mehr manuell
angegeben werden muss — Gesamtprojekt (`src/broker` + `src/db` + `src/risk`) liegt damit
bei 104/104 Tests, 100% Line- **und** Branch-Coverage. `uv run ruff check` und
`uv run mypy src/risk` (strict) → beide sauber.

Kein Integrationstest nötig (reine Funktion ohne IO, siehe §1) — die 46 Unit-Tests decken
alle 12 in §3 definierten Testfälle ab, inkl. Grenzfälle (exakt am Limit → erlaubt) und der
Mehrfach-Verletzungs-Fall (Test 11).

## 6. Rollback-Pfad

Additives Feature, reine Funktionsbibliothek ohne Seiteneffekte. Nichts ruft `src/risk`
bisher auf (kein Handels-Agent existiert). Rollback = Commit zurücknehmen.
