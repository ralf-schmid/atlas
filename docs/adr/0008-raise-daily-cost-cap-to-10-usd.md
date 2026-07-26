# System-Tagescap von 5 auf 10 USD angehoben (Monats-Soft-Cap 120 → 240)

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-25
* Betrifft Invariante(n): #7 (Kosten-Caps doppelt durchgesetzt)
* Betrifft: ARCHITECTURE.md §7 Punkt 1 (Kosten-Caps fixiert), CLAUDE.md §7

## Kontext und Problemstellung

Die in Phase 1→2 fixierten LLM-Kosten-Caps (5 USD/Tag System, 1 USD/Tag je
Persona, 120 USD/Monat Soft-Cap; Einheiten-Näherung siehe ADR-0004) wurden für
den P4-Betrieb gesetzt, bevor der Review-Agent existierte. Für Phase 5 kommen
zwei Kostentreiber dazu (Analyse in `docs/dod/phase-5.md`, Abschnitt
„Kosten-Headroom"):

* **Review-Agent (F084):** läuft auf Sonnet als shared role (`review`,
  `config/llm.yaml`) und zählt damit gegen den **System**-Tagescap, nicht gegen
  die Per-Persona-Caps.
* **Sonnet-5-Intro-Preis endet am 31.08.2026** → +50 % auf die Sonnet-Kosten.

Der Tagesverbrauch lag im Stichprobenzeitraum 22.–24.07. bei ~2,6–3,0 USD gegen
den 5-USD-Cap. Review-Agent + Preisanstieg zusammen können den 5-USD-Cap reißen
und LLM-Calls stoppen (Invariante 7: 100 % → Stopp weiterer Calls). Ein
gestoppter Zyklus mitten im Wettbewerb (Start 03.08.2026) ist der teurere Fehler
als etwas mehr zugelassenes Budget für ein Experiment mit Eigengeld.

## Entscheidung

System-Tagescap **5 → 10 USD**. Monats-Soft-Cap **120 → 240 USD** (in gleichem
Schritt, damit die bisherige Ratio „~24 Tage voller Ausschöpfung" erhalten
bleibt und der Monats-Cap nicht still zur bindenden Grenze wird — bei 10 USD/Tag
gegen 120 USD/Monat wäre nach 12 vollen Tagen Schluss). Per-Persona-Tagescap
**unverändert bei 1 USD** — der aktuelle Verbrauch liegt bei ~0,4–0,5 USD je
Persona/Tag, und die Anhebung zielt auf System-/shared-Kosten, nicht auf die
`persona_analysis`-Calls.

Werte gelten weiterhin als USD-Zahlen ohne FX-Umrechnung (ADR-0004 unverändert
gültig).

### Konsequenzen

* Gut: Headroom für Review-Agent + Sonnet-Preisanstieg, ohne dass ein
  Wettbewerbszyklus an der Kosten-Bremse stoppt.
* Schlecht: höhere maximal zugelassene Ausgaben (Soft-Limit auf Experiment-Ebene,
  akzeptabel — Eigengeld, keine Fremdgelder). Bei tatsächlicher Annäherung an die
  neuen Caps erneut bewerten.
* **Zweite Enforcement-Ebene (Invariante 7):** die LiteLLM-Proxy-Key-Budgets
  (Ebene 1) werden im Proxy selbst als virtuelle Keys verwaltet, **nicht** in
  diesem Repo. Sie müssen dort passend nachgezogen werden, sonst greift die
  Proxy-seitige Bremse weiter unterhalb von 10 USD. Diese Anpassung liegt bei
  Ralf (kein Repo-Artefakt, analog zum Branch-Protection-Ruleset ADR-0007).
* **Deployment:** `config/llm.yaml` ist ins Docker-Image gebacken (nicht
  gemountet) — die Änderung wird erst nach Rebuild + Redeploy auf `atlas-ugreen`
  wirksam, ein reiner Restart reicht nicht.
* Folgearbeit für Ralf offen (`docs/dod/phase-5.md`, offene Entscheidung #3 damit
  beantwortet): endgültige Cap-/Modell-Mix-Bewertung nach dem Intro-Preis-Ende
  (31.08.2026).
