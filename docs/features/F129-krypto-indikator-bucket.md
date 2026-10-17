# F129 — Krypto-Indikatoren als eigener Auswahl-Bucket

Status: implementiert, noch nicht live
Datum: 2026-10-17
Phase: 6 (Vorbereitung Saison 2)
Auslöser: [ADR-0021](../adr/0021-persona-universums-filter.md), Option D (Ralf, 17.10.2026)

## 1. Zieldefinition

Bis jetzt war `technical_indicator` ein einziger Bucket der Round-Robin-Auswahl
(F047). Zehn Krypto-Paare standen darin gegen ~380 Aktien und bekamen einen
Anteil der Slots, der ihrer Anzahl entsprach. Auch mit der F128-Rotation sah
CRYPTOR sein Universum deshalb nur in etwa jedem fünften Zyklus.

**Done heißt:** Krypto- und Aktien-Indikatoren sind zwei Buckets mit gleichem
Anteil an der Round-Robin-Auswahl, für alle Personas gleich.

**Non-Scope:** andere `source_type`s (z. B. `market_mover` mit Krypto-Movern),
persona-spezifische Logik (ADR-0021 Option C), eine Large-Cap-Liste für GUARDIAN.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein | Die Regel hängt am Instrument (Paarformat `BASE/QUOTE`, wie F116), nicht an der Persona. Alle sechs sehen im selben Zyklus denselben Ausschnitt. |
| Ralfs Entscheidung 15.08. (`universe_screen` nicht deterministisch durchsetzen) | nein | Es wird kein Kauf gesperrt und kein Universum gefiltert. |
| Charter | nein | Kein Bump. |

**Kosten:** keine. Der Cap von 30 Items bleibt.
**Preis:** Die Aktien-Personas verlieren je Zyklus einige Indikator-Slots an
Krypto (ADR-0021, Konsequenzen).

## 3. Testdefinition (vor der Umsetzung)

`tests/orchestrator/test_persona_analysis.py`

1. Ein Pool aus 380 Aktien- und 4 Krypto-Indikatoren mit einem Cap von 8 ergibt
   je 4 Krypto- und 4 Aktien-Indikatoren. Vor der Umsetzung rot.
2. Die bestehenden Auswahl-Tests (F047, F128) bleiben grün.

## 4. Implementierung

`src/orchestrator/persona_analysis.py`: `_selection_bucket(item)` liefert
`technical_indicator:crypto` für Indikator-Items mit Paar-Symbol, sonst den
`source_type`. `_select_prompt_items` bildet die Buckets darüber.

## 5. Testdurchlauf

Lokal am 17.10.2026 gegen Postgres 16 + pgvector: Test 1 war vor der Umsetzung
rot und ist danach grün. `ruff` und `mypy` sind sauber, `pytest tests/`:
**1281 passed**, Coverage 92,04 %. Maßgeblich ist CI auf dem PR.

## 6. Livesetzung

Gemeinsam mit F128: ein Deploy, keine Migration. Nachweis im ersten Krypto- und
im ersten Aktien-Zyklus danach: Im Agent Trace stehen
`technical_indicator`-Items mit `/USD`-Symbolen im Prompt.

## 7. Rollback

Commit-Revert und Rebuild. Kein Datenbestand betroffen.
