# F079 — Sizing erzeugt keine Sub-1-Aktien-Orders mehr

**Status:** ✅ **Umgesetzt 25.07.2026** (Commits `9cf0509`, Test-Fix `44c94d5`).
`BrokerAdapter.requires_whole_shares` (True Alpaca / False Ledger),
`_resolve_buy_decision` rejektet Sub-1-Aktien-Buys (`floor(quantity)==0` →
`reject_idea`/`RECORDED`, `position_too_small_for_whole_share`) vor dem Risk-Gate
und persistiert für Whole-Share-Broker die `floor`-Menge. Tests §4 (1–7) grün,
inkl. Regression + HITL-Flow-Adapter-Fix. Rollback: rein additiver Code-Pfad.
**Phase:** 5, Block 0 (P4-Abschluss + Aufräumer, vor dem P5-Start)
**Abhängigkeiten:** keine harten. Muss vor dem Wettbewerbsstart (2026-08-03)
erledigt sein, da sonst am Stichtag weiterhin unausführbare APPROVED-Leichen
entstehen können. Verwandt mit [F080] (Stuck-Decision-Sweep) — F079 verhindert
das Entstehen, F080 räumt bestehende auf.

## 1. Zieldefinition

Die Ganzaktien-Rundung sitzt aktuell **nur** im Broker-Adapter
(`AlpacaPaperAdapter.place_order`, F052): `rounded_qty = round(qty)`, und bei
`round(qty) == 0` wirft der Adapter `ValueError`. Die Sizing-Schicht
(`persona_analysis._resolve_buy_decision`) persistiert die Decision aber schon
vorher als `APPROVED` mit der **fraktionalen** Rohmenge (z. B. 0,04 Aktien,
Befund `phase-4.md` 21.07.2026). Ergebnis: eine APPROVED-Decision, die nie
ausführbar ist — sie scheitert bei jeder Ausführung im Adapter und wird von
`retry_stuck_decisions` endlos wiederholt.

Ziel: Der Mindestgrößen-Check wandert **nach vorn in die Sizing-Schicht**. Eine
BUY-Decision, deren gerundete Menge 0 ganze Aktien ergäbe, wird gar nicht erst
APPROVED, sondern als `reject_idea` (`DecisionStatus.RECORDED`,
`rejection_reason="position_too_small_for_whole_share"`) terminal abgelegt.

**Entscheidung (Ralf, 25.07.2026): Schwelle = < 1 ganze Aktie.** Kein
zusätzliches USD-Minimum — die reine Ganzaktien-Rundung deckt den beobachteten
Fall exakt ab und bleibt transparent.

**Scope:**
- Broker-Semantik „braucht Ganzaktien" explizit machen: neues Feld
  `requires_whole_shares: bool` im `BrokerAdapter`-Protocol (`True` für
  `AlpacaPaperAdapter`, `False` für `InternalLedgerAdapter`).
- `_resolve_buy_decision`: nach der `quantity`-Berechnung, vor dem Risk-Check —
  wenn `broker_adapter.requires_whole_shares` und `floor(quantity) == 0` →
  `reject_idea` statt APPROVED.
- Wenn Ganzaktien nötig: die persistierte `decision.quantity` ist die
  **gerundete** Ganzmenge (`floor`), nicht die fraktionale Rohmenge — damit
  Risk-Gate, Malus (F083) und Adapter dieselbe Zahl sehen und der Adapter nicht
  ein zweites Mal (anders) rundet.
- Unit-Tests mit beiden Adapter-Typen.

**Non-Scope:**
- Kein Eingriff in die Alpaca-Rundung selbst (`round(qty)` im Adapter bleibt als
  Verteidigungslinie für Alt-Decisions bestehen — F080 räumt die bestehenden auf).
- Kein absolutes USD-Minimum (bewusst verworfen, s. o.).
- Krypto/fraktionaler Handel wird **nicht** eingeschränkt — `InternalLedgerAdapter`
  (HYPE, CONTRA, CRYPTOR) akzeptiert weiterhin fraktionale Mengen.
- Kein LLM-Anteil (Sizing ist Code, CLAUDE.md-Verbot).

## 2. Kontext / Ist-Zustand

Adapter-Zuordnung (`config/broker.yaml`):

| Adapter | Personas | qty-Verhalten |
|---|---|---|
| `alpaca_paper` | VULTURE, GUARDIAN, CHARTIST | `round(qty)`; `ValueError` bei 0 |
| `internal_ledger` | HYPE, CONTRA, CRYPTOR | fraktional, keine Rundung |

Der Bug betrifft also strukturell **nur die drei Alpaca-Personas**. Ein
adapter-blindes „< 1 Aktie → reject" würde CRYPTOR (z. B. 0,1 BTC → floor 0)
fälschlich abweisen und die reale fraktionale Krypto-Semantik brechen. Deshalb
die adapter-abhängige Weiche über `requires_whole_shares`.

Warum Rundung per `floor`, nicht `round`: `round(0,6) = 1` würde eine Order
**größer** als die vom Risk-Gate freigegebene Menge erzeugen (die
Positionsgröße überschreitet die Persona-Obergrenze). `floor` rundet immer nach
unten — die tatsächlich gehandelte Position ist nie größer als die vom Gate
geprüfte. Der Adapter rundet historisch mit `round`; für neue Decisions ist ab
F079 die Sizing-Menge bereits ganzzahlig (`floor`), sodass der Adapter-`round`
sie unverändert lässt. Die kleine Abweichung (Adapter `round` vs. Sizing
`floor`) betrifft nur noch Alt-Decisions und ist bewusst so belassen.

## 3. Kritische Betrachtung

- **Invariante 1 (Risk-Gate = Code, kein LLM):** eingehalten — die Weiche ist
  deterministischer Code, kein Gate-Bypass. Der Check läuft **vor** dem
  Risk-Gate; eine zu kleine Order kommt gar nicht erst zur Bewertung.
- **Invariante 4 (Stop-Loss-Pflicht):** unberührt — eine reject_idea-Decision
  platziert keine Order, also kein Stop nötig.
- **Invariante 10 (Fairness):** Die Ganzaktien-Regel gilt an die Assetklasse/den
  Broker gebunden, nicht an die Persona — Alpaca-Aktien-Personas unterliegen der
  Börsen-Realität (keine fraktionalen Bracket-Orders), Krypto nicht. Das bildet
  reale Marktstruktur ab, benachteiligt niemanden unfair.
- **Nebeneffekt auf die Erfolgsquote:** Sub-1-Aktien-Ideen zählen künftig als
  `reject_idea` statt als (nie ausgeführte) APPROVED. Das ist die ehrlichere
  Zählung — eine unausführbare APPROVED war ohnehin kein Trade.
- **Kosten:** 0 — reiner Code, keine LLM-Calls.

## 4. Testdefinition

Fixtures analog `tests/orchestrator/` (echte Postgres-Schema-Fixture).

1. **Alpaca-Persona, Order rundet auf 0:** `requires_whole_shares=True`,
   position_value/entry_price = 0,04 → Decision ist `RECORDED`/`reject_idea`
   mit `rejection_reason="position_too_small_for_whole_share"`, **kein**
   `order_record`, Status nie APPROVED.
2. **Alpaca-Persona, Order ≥ 1 Aktie:** qty roh 3,7 → Decision APPROVED,
   `decision.quantity == 3` (floor, nicht 4), Risk-Gate lief.
3. **Alpaca-Persona, Order exakt 1,0 Aktie:** qty 1,0 → APPROVED, quantity 1.
4. **Internal-Ledger-Persona (CRYPTOR), fraktional:** `requires_whole_shares=False`,
   qty 0,1 BTC → APPROVED, `decision.quantity == 0.1` (unverändert fraktional).
5. **Internal-Ledger-Persona, sehr kleine Menge:** qty 0,0001 → APPROVED,
   fraktional erlaubt (kein Whole-Share-Reject).
6. **`requires_whole_shares`-Flag:** `AlpacaPaperAdapter.requires_whole_shares is
   True`, `InternalLedgerAdapter.requires_whole_shares is False`.
7. **Regression:** existierende Sizing-Tests bleiben grün (floor ändert die
   persistierte quantity für Alpaca-Personas — betroffene Assertions anpassen).

## 5. Offene Punkte

- Keine — Schwelle und Reihenfolge (F079 vor F080) sind mit Ralf entschieden
  (25.07.2026).

[F080]: F080-stuck-decision-sweep-permanent-transient.md
