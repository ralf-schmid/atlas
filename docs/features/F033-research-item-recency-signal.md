# F033 — Research-Item-Aktualitätssignal

Status: umgesetzt
Datum: 2026-07-08
Phase: 5

## 1. Zieldefinition

Ralf beim ersten Live-Run beobachtet (siehe Deployment-Log 2026-07-08): der erste
Zyklus synthetisierte 874 Research-Items aus einem 7-Tage-Bootstrap-Fenster
(`_BOOTSTRAP_WINDOW`, F017) auf einen Schlag — Inhalte mit ganz unterschiedlichem
`published_at`, alle im selben Zyklus "neu". Ralfs Punkt: ein Item taucht im Pool
auf, weil es neu *eingelesen* wurde (`synced_at`), nicht weil sein Inhalt neu ist
(`published_at`) — ein Zeitschriften-Tipp von vor einem Monat, der erst jetzt
synchronisiert wird, ist im Datenpool nicht von einer taufrischen EDGAR-Filing zu
unterscheiden, wenn die Persona nicht explizit auf das Alter hingewiesen wird.

**Scope:** (1) code-berechnetes `age_days`-Feld pro Research-Item im LLM-Payload
(`_build_messages`, `persona_analysis.py`), relativ zu `cycle.started_at`. (2) Ein
neuer Charter-Abschnitt "Aktualität der Research-Items", der alle 6 Personas
anweist, ältere Items grundsätzlich schwächer zu gewichten. (3) `charter_version`
1 → 2 in allen 6 `config/personas/*.yaml` (Charter-Text ändert sich für alle
gleich).

**Non-Scope:** kein hartes Cutoff/Decay im Risk-Gate oder in der
Positionsgrößen-Arithmetik (das bleibt deterministischer Code für Risikoparameter,
nicht für Recherche-*Bewertung*) — die Gewichtung "wie stark zählt Alter" bleibt
bewusst Sache der Persona-eigenen Urteilsbildung, nicht einer neuen
System-Guardrail. Kein Eingriff in `_BOOTSTRAP_WINDOW`/Fenster-Logik selbst (F017)
— das Fenster bestimmt, *was* in den Pool kommt, dieses Feature nur, *wie alt* es
der Persona explizit erscheint.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness / Charter-Version-Bump | ja | Der neue Abschnitt steht im gemeinsamen `_TEMPLATE_SOURCE` (nicht in `_CHARTER_CONTENT`) — identischer Wortlaut für alle 6 Personas, keine bekommt eine andere Gewichtungsregel. `charter_version` in allen 6 YAMLs gleichzeitig gebumpt (1 → 2), damit der Wettbewerbsvergleich den Bruch sauber markiert. |
| Finanzkennzahlen nicht vom LLM ausrechnen lassen | ja | `age_days` wird in `_build_messages` (Python, `(reference_time - published_at).total_seconds() / 86400`) berechnet, nicht vom Modell aus zwei ISO-Timestamps — LLMs sind unzuverlässig in Datumsarithmetik; das Feld liegt fertig gerechnet im Payload. |
| Untrusted Content (#9) | nein | `age_days` ist ein zusätzliches, code-berechnetes Metadatenfeld auf einem bereits vertrauten Research-Item — ändert nichts an der Roh-/Getaggt-Unterscheidung. |
| Kosten | ja (marginal) | Ein zusätzliches Zahlenfeld pro Item im JSON-Payload — vernachlässigbarer Token-Mehrverbrauch, kein zusätzlicher LLM-Call. |

**Design-Entscheidungen:**
- **`reference_time = cycle.started_at`, nicht `datetime.now()` zum Zeitpunkt des
  Prompts:** stabil und reproduzierbar für Tests/Replays desselben Zyklus (F022
  HITL-Resume ruft `analyze_persona_cycle` ggf. später erneut auf — das Alter soll
  dabei nicht "weiterlaufen").
- **`age_days: None` bei fehlendem `published_at`:** einige Quellen (z. B.
  Screener-Ergebnisse ohne belastbares Ursprungsdatum) haben u. U. kein
  `published_at` — `None` statt eines erfundenen Werts ist ehrlicher; die Persona
  entscheidet selbst, wie sie ein Item ohne Altersangabe behandelt.
- **Keine feste Zahl/Formel im Prompt** (z. B. "ignoriere alles > 30 Tage"): jede
  Persona hat einen anderen Zeithorizont (HYPE/CHARTIST kurzfristig, GUARDIAN
  strukturell/lang) — eine harte Systemregel würde GUARDIANs Fundamentaldaten
  genauso abstrafen wie HYPEs Tipps. Die Instruktion bleibt qualitativ ("gewichte
  schwächer, wie stark hängt von deiner Signalart ab"), die Guardrails bleiben
  Sache des Risk-Gates, nicht dieses Prompts.

**Kosten:** keine neuen LLM-Calls, marginal mehr Tokens/Request. **Fairness:**
identischer Charter-Zusatz + identischer Versions-Bump für alle 6 Personas.

## 3. Testdefinition

`tests/orchestrator/test_persona_analysis.py::test_llm_payload_carries_code_computed_age_days_per_research_item`:
1. Drei Research-Items im selben Zyklus: `published_at == cycle.started_at` (frisch),
   `published_at == cycle.started_at - 30 Tage` (alt), `published_at is None`
   (unbekannt).
2. LLM-Request abgefangen (MockTransport) → `age_days` im Payload: `0.0`, `30.0`,
   `None`.

`tests/personas/test_charters.py::test_all_personas_contain_recency_weighting_instruction`
(parametrisiert über alle 6 Personas):
1. Charter enthält `age_days`-Erwähnung und den Kernsatz zur Nicht-Automatik
   ("nicht automatisch noch gültig").

`test_all_personas_render_with_their_charter_version` angepasst auf
"Charter-Version 2".

## 4. Implementierung

- `src/orchestrator/persona_analysis.py`: `analyze_persona_cycle` lädt jetzt die
  `Cycle`-Zeile (für `started_at`), `_build_messages` bekommt `reference_time` und
  berechnet `age_days` je Item über neue Helper-Funktion `_age_days`.
- `src/personas/charters.py`: neuer Abschnitt "Aktualität der Research-Items" im
  gemeinsamen `_TEMPLATE_SOURCE`.
- `config/personas/*.yaml`: `charter_version: 1` → `2` (alle 6 Dateien).
- Kein Alembic-Migrations-Bedarf (kein Schema-Change, nur Payload-/Prompt-Inhalt).

## 5. Test & Rollout

- `uv run pytest` (voller Lauf, lokal gegen Test-Postgres): 374 passed.
- `ruff check` + `ruff format --check`, `mypy` auf den geänderten Dateien: clean.
- Deployment: rsync + `docker compose build api scheduler` + `up -d` auf der UGREEN,
  danach `scripts/seed_personas.py` erneut ausgeführt (idempotent lt. F015 —
  übernimmt den neuen `charter_version`-Wert aus der YAML in die `persona`-Zeilen).
- **Rollback-Pfad:** `charter_version` in den 6 YAMLs zurück auf `1` und den
  Charter-Abschnitt in `charters.py` entfernen (reiner Text-/Config-Revert, kein
  DB-Migrationsschritt nötig) + erneuter Deploy.
