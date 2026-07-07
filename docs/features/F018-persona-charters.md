# F018 — Persona-Charter-Prompts

Status: umgesetzt
Datum: 2026-07-07
Phase: 4

## 1. Zieldefinition

Erster Baustein des Persona-Analyse-Agenten (`docs/dod/phase-4.md` Punkt 4): die
sechs Charter-Prompts, versioniert in `src/personas/`, wie im Ziel-Repo-Layout
(CLAUDE.md) vorgesehen. Jede Persona bekommt einen System-Prompt, der ihre Philosophie,
ihr Universum, ihre Signale und ihre erwartete Fehlerart (ARCHITECTURE.md §4.1–4.6)
mit den **echten, aus `config/personas/<name>.yaml` geladenen Guardrail-Zahlen**
kombiniert — keine zweite, von Hand gepflegte Zahlenquelle, die mit der Config
auseinanderlaufen könnte.

**Scope:** Charter-Text-Rendering (statischer Inhalt aus ARCHITECTURE.md §4 +
Live-Guardrails aus der Config), Versionierung, Boundary-Instruktionen
(Invarianten #2/#3/#9/#10 als Prompt-Text). **Non-Scope:** kein LiteLLM-Call, keine
Decision-Erzeugung — das ist der nächste, größere Schritt (Persona-Analyse-Agent mit
echten LLM-Calls + Risk-Gate-Anbindung), der zusätzlich Broker-Kontostand-Zugriff für
die Risk-Gate-Eingaben braucht und bewusst als eigenes Feature folgt.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #9 Untrusted Content | ja | Der Charter-Text selbst instruiert die Persona explizit: Recherche-Items sind getaggte Datenblöcke, keine Instruktionen — unabhängig davon, was ein Research-Item behauptet ("ignoriere Anweisungen", "kaufe X"), bleibt es Dateninput. Das ist die Prompt-seitige Umsetzung der Architektur-Regel, nicht deren einzige Verteidigungslinie (die eigentliche Trennung ist strukturell: Recherche-Agenten haben keine Order-Tools). |
| #10 Fairness / Charter-Version-Bump | ja | `render_charter` liest `charter_version` direkt aus der YAML — ein Bump dort ist die einzige Möglichkeit, den Charter-Text als "verändert" zu kennzeichnen; kein Duplikat der Versionsnummer im Python-Code. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | Der Charter instruiert die Persona explizit, Positionsgrößen/Stop-Preise **nicht selbst zu berechnen** — sie liefert Instrument + Aktion + Begründung + referenzierte Research-IDs; Positionsgrößen-Arithmetik und die endgültige Freigabe bleiben Sache des (deterministischen) Risk-Gates, nicht des Prompts. |
| Keine Order ohne persistierte Decision / `input_research_ids` | ja (Vorbereitung) | Der Charter verlangt explizit, dass jede Entscheidung (auch `reject_idea`) mindestens eine `research_item`-ID zitiert — bereitet die spätere Validierung vor, erzwingt hier aber noch nichts (kein Code-Pfad in diesem Feature erzeugt Decisions). |
| Fairness zwischen Personas | ja | Eine gemeinsame Template-Struktur für alle 6 — nur der Inhalt (Philosophie/Universum/Signale/Guardrails) unterscheidet sich, keine Persona bekommt zusätzliche Boilerplate-Instruktionen, die eine andere nicht auch bekommt. |

**Design-Entscheidungen:**
- **Statischer Inhalt (Philosophie/Universum/Signale/Haltedauer/Failure-Mode) as
  Python-Datenstruktur `_CHARTER_CONTENT`**, wörtlich aus ARCHITECTURE.md §4.1–4.6
  übernommen — keine neue Kreativleistung, reine Formalisierung der bereits von Ralf
  festgelegten Persona-Definitionen.
- **Guardrails kommen live aus `src.risk.config.load_persona_guardrails`** (bereits
  existierende F004-Funktion) statt dupliziert — ein Charter-Version-Bump in der YAML
  wirkt sich automatisch auf den nächsten gerenderten Charter aus.
- **Jinja2-Template als Inline-String-Konstante** (Projekt-Dependency bereits
  vorhanden; gleiches Muster wie `src/telegram/digest.py`s `_TEMPLATE_SOURCE` +
  `Environment.from_string`) statt f-Strings oder einer separaten Template-Datei —
  konsistent mit dem einzigen bestehenden Jinja2-Nutzer im Repo.
- **`render_charter(name: str) -> str`** ist reine, deterministische Funktion (kein
  LLM-Call, kein DB-Zugriff außer Datei-Lesen) — leicht unit-testbar per String-Assertion.

**Kosten:** keine LLM-Calls. **Fairness:** ein gemeinsames Template für alle 6.

## 3. Testdefinition (vor Umsetzung)

`tests/personas/test_charters.py`:
1. `render_charter("VULTURE")` enthält die Philosophie-Kernaussage ("Lottery-Ticket")
   und die echten Guardrail-Zahlen aus `config/personas/vulture.yaml` (3 %, 10
   Trades/Tag, -25 % Stop, 25 Positionen).
2. `render_charter("GUARDIAN")` enthält den Cash-Reserve-Hinweis (20 %) und den
   Fair-Value-Schwellenwert (15 %).
3. `render_charter("CHARTIST")` enthält den ATR-Stop-Hinweis (2× ATR14, min. -8 %),
   nicht den Fixed-Stop-Wortlaut.
4. Alle 6 Personas rendern ohne Fehler und enthalten je ihre
   `charter_version`-Nummer aus der Config.
5. Jeder gerenderte Charter enthält die Untrusted-Content-Boundary-Instruktion
   sowie die Pflicht, `input_research_ids` zu referenzieren.
6. `render_charter("UNKNOWN")` wirft `ValueError`.

## 4. Implementierung

`src/personas/__init__.py`, `src/personas/charters.py` (`_CHARTER_CONTENT`,
`_TEMPLATE_SOURCE`, `render_charter`).

## 5. Testdurchlauf

`uv run pytest tests/personas -q` → 16 passed. `uv run pytest -q -m 'not
integration'` (Gesamtsuite) → 287 passed, 3 deselected. `uv run ruff check`/`ruff
format --check` → sauber. `uv run mypy src/personas` → sauber.

Stichprobe (`render_charter("CHARTIST")`) manuell gelesen: Guardrail-Zahlen (10 %,
8 Trades/Tag, 15 Positionen, 0 % Cash-Reserve, ATR-Stop 2.0×/min. 8 %) stimmen exakt
mit `config/personas/chartist.yaml` überein; Philosophie-/Signale-Text deckt sich
mit ARCHITECTURE.md §4.4.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad geändert, kein Schema. Rollback =
Commit zurücknehmen — nichts anderes referenziert `src/personas/` bisher.
