# F065 — HYPE/CONTRA JSON-Parse-Fehler: Retry + robusterer Parser

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

Wiederkehrende Rückmeldung: HYPE und CONTRA lehnen überproportional oft mit
`rejection_reason=llm_output_parse_error` ab ("LLM-Antwort konnte nicht als
valides JSON geparst werden"). Ralf: *"Diesen Fehler schleppen wir schon ewig
rum. Bereinige das jetzt nachhaltig und sichere es durch Tests ab."*

Live-Diagnose (Box-DB, 11.07.2026): alle 17 Fälle der letzten 3 Tage stammen
aus der Zeit **vor** F057 (10.07., 22:04 Uhr Deploy) — seit Deploy lief wegen
des Wochenendes noch kein Zyklus, F057s eigene "Live-Bestätigung ausstehend"
war also noch unbeobachtet. F057 behebt eine plausible, aber unbestätigte
Ursache (Tools/`tool_choice`-Inkonsistenz in der letzten Tool-Runde) — bleibt
bestehen, wird hier aber um zwei strukturelle Lücken ergänzt, die F057 nicht
abdeckt:

1. **Kein Retry.** Ein einzelner leerer/fehlerhafter LLM-Turn führt sofort zum
   permanenten `reject_idea` — bei einer bekanntlich probabilistischen
   Fehlerquelle (in 17/17 Fällen: leere Completion, kein kaputtes JSON)
   strukturell riskant, eine reale Handelsidee für den ganzen Zyklus zu
   verlieren.
2. **Fragiler Parser.** Die Codefence-Regex war case-sensitiv (```JSON wurde
   nicht erkannt) und verankert (`^...$`), sodass Text nach dem schließenden
   Fence (z. B. eine Abschlussfloskel des Modells) das gesamte Parsing brechen
   ließ, obwohl das JSON selbst wohlgeformt war.

**Scope:** ein bounded Retry bei Parse-Fehlschlag + robusterer
Codefence-Parser + Testabdeckung für alle gefundenen Lücken. **Non-Scope:**
natives JSON-Mode/`response_format` am LiteLLM-Client (größerer Eingriff,
nicht durch die live beobachteten Daten begründet — der Fehler ist leere
Completion, nicht Formatierung), Trailing-Comma-Repair (keine beobachtete
Produktions-Instanz, spekulativ).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein | `_run_llm_with_parse_retry` ersetzt den bisherigen einzelnen Aufruf für **alle 6 Personas** identisch — keine persona-spezifische Sonderbehandlung, obwohl nur HYPE/CONTRA das Symptom zeigen. |
| #7 Kosten-Caps | ja, geprüft | Jeder Retry-Versuch läuft komplett durch `guarded_complete`/`cost_ledger` (unverändert, pro Aufruf geprüft) — ein bestehender Budget-Erschöpfungs-Fall bricht wie bisher sofort mit `BudgetExceededError` ab, der Retry umgeht keine Kostenprüfung. Worst Case verdoppelt sich (max. 6 statt 3 LLM-Calls/Persona/Zyklus: 2 Versuche × 3 Tool-Runden) — greift nur im seltenen Parse-Fehler-Fall, nicht im Normalbetrieb (live verifiziert: HYPE/CONTRA parsen im Normalfall bereits im ersten Versuch, siehe §5). |
| Keine Order ohne persistierte Decision | nein | Unverändert — der Retry passiert vor `_resolve_decision`, ändert nichts an Order-/Persistenz-Pfad. |

**Design-Entscheidungen:**
- **Retry mit frischer Message-Historie, nicht Fortsetzung der fehlgeschlagenen
  Tool-Konversation.** `_run_llm_with_tools` hängt Tool-Call-Turns an die
  übergebene `messages`-Liste an; ein Retry auf Basis der bereits
  fehlgeschlagenen Historie könnte exakt die von F057 behobene
  Tools-Historie-Inkonsistenz erneut erzeugen. Jeder Versuch bekommt eine
  frische Kopie der Basis-Nachrichten (`list(messages)`), `available_ids`
  bleibt über beide Versuche hinweg erhalten (bereits gefundene
  Such-Treffer bleiben gültig).
- **Genau 1 Retry (`_MAX_PARSE_RETRIES = 1`), nicht unbegrenzt** — verhindert
  eine Endlosschleife bei dauerhaft kaputtem Proxy/Modell; nach 2 Versuchen
  greift der bestehende `llm_output_parse_error`-Fallback unverändert.
- **Tokens/Kosten werden über beide Versuche summiert, ein `AgentRun`.**
  Gleiches Muster wie F045s Tool-Runden-Summierung — der bestehende Vertrag
  "genau ein `AgentRun` pro Persona/Zyklus" bleibt erhalten.
- **Parser: `.search()` statt `.match()`, `re.IGNORECASE`, keine Anker.**
  Findet den Codefence-Block irgendwo im Text (tolerant gegenüber
  Prosa davor/danach), erkennt ```JSON groß geschrieben. Bewusst *kein*
  Trailing-Comma-Repair — nicht durch beobachtete Produktionsdaten
  begründet (CLAUDE.md: keine Fehlerbehandlung für Szenarien, die nicht
  auftreten).

**Kosten:** siehe Tabelle oben, begrenzt und geprüft. **Fairness:**
unverändert, gleicher Pfad für alle Personas.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/orchestrator/test_llm_decision_schema.py`:
- `test_empty_content_returns_none` — leerer String (der tatsächlich
  beobachtete Produktionsfall) crasht nicht, liefert `None`.
- `test_parses_json_wrapped_in_uppercase_code_fence` — ```JSON wird erkannt.
- `test_parses_json_wrapped_in_code_fence_with_trailing_prose` — Text nach
  dem schließenden Fence bricht das Parsing nicht mehr.

`tests/orchestrator/test_persona_analysis.py`:
- `test_empty_completion_is_retried_then_succeeds` — erste Antwort leer,
  zweite valide → Decision wird erfolgreich persistiert (kein
  `llm_output_parse_error`), genau 2 HTTP-Calls, genau ein `AgentRun` mit über
  beide Versuche summierten Tokens.
- `test_two_empty_completions_in_a_row_still_reject_with_diagnostics` — beide
  Versuche leer → weiterhin `llm_output_parse_error`-Fallback, aber begrenzt
  auf genau 2 Calls (kein Endlosretry).

## 4. Implementierung

- `src/orchestrator/llm_decision_schema.py`: `_CODE_FENCE_RE` ohne Anker, mit
  `re.IGNORECASE`; `parse_llm_decision` nutzt `.search()` statt `.match()`.
- `src/orchestrator/persona_analysis.py`: neue `_MAX_PARSE_RETRIES = 1`;
  neue Funktion `_run_llm_with_parse_retry` (wrapt `_run_llm_with_tools`,
  wiederholt bei `parsed is None`, summiert Tokens/Kosten); `analyze_persona_cycle`
  ruft jetzt diese Funktion statt `_run_llm_with_tools` direkt auf.
- Kein Alembic-Migrations-Bedarf.

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'` (lokaler Test-Postgres): 538
  passed (5 neue Tests). `ruff check`/`format --check`, `mypy`: clean.
- Deployment: rsync (`persona_analysis.py`, `llm_decision_schema.py`) +
  `docker compose build api scheduler` + `up -d` auf `atlas-ugreen`.
- **Live verifiziert** (echter LiteLLM-Proxy, echte Charter, HYPE + CONTRA,
  in einem per `session.rollback()` verworfenen Test-Zyklus — keine
  Datenbank-Nebenwirkung, `FakeAdapter` verhindert echte Order-Platzierung):
  beide Personas liefern sauber geparste, inhaltlich stimmige Entscheidungen
  auf Anhieb (kein Retry nötig, kein Parse-Fehler):
  - HYPE: `action=BUY`, Begründung zitiert aktienfinder-Empfehlung + MACD/RSI
    (später vom Risk-Gate abgelehnt, weil dieser Test-Zyklus keine echten
    Marktdaten hat — erwartet, nicht Teil dieses Fixes).
  - CONTRA: `action=REJECT_IDEA` mit einer inhaltlich korrekten
    Kontrarian-Begründung ("Momentum/Euphorie widerspricht meiner Strategie").
  Beweist: der deployte Code funktioniert im Normalbetrieb unverändert
  korrekt; der konkrete, seltene Bug (leere Completion) lässt sich nicht
  provoziert reproduzieren (probabilistisches Proxy-Verhalten), aber der
  Retry-Pfad selbst ist durch die Unit-Tests (§3) vollständig abgedeckt.
- **Verbleibende Beobachtung:** die `llm_output_parse_error`-Rate über die
  nächsten Live-Zyklen (ab dem nächsten Krypto-Zyklus 06:00 UTC bzw. dem
  nächsten Aktien-Handelstag) sollte auf 0 oder zumindest deutlich reduziert
  fallen — ein verbleibender einzelner Fall würde jetzt automatisch vom Retry
  aufgefangen, bevor er zu `llm_output_parse_error` eskaliert.
- **Rollback-Pfad:** reiner Code-Revert (kein Schema-Change). Retry lässt
  sich ohne Revert auch durch `_MAX_PARSE_RETRIES = 0` in
  `persona_analysis.py` abschalten — identisch zum Verhalten vor diesem
  Feature.
