# F099 — Meta-Review für `reject_idea`

**Status:** Implemented · **Deployed:** 2026-08-01 (s. §7)
**Phase:** 5 (Härtung)
**Abhängigkeiten:** `src/review/meta_agent.py` (neu), `src/db/models.py`,
`src/orchestrator/scheduler.py`, `src/llm/config.py`, `config/llm.yaml`,
Migration `d4e5f6a7b8c9`
Berührt Invarianten **#2** (Privilege Separation), **#7** (Kosten-Caps),
**#9** (Untrusted Content), **#10** (Fairness).

## 1. Zieldefinition

ARCHITECTURE.md §5.1 gibt dem Review-Agenten ausdrücklich auch das „Meta-Review der
Recherche-Qualität" mit; §5.2 verortet es im Sonntagslauf. F084 hat genau diesen
Teil ausgeklammert (F084 §7: *„bewusst nicht mitgebaut, eigener Zuschnitt"*) und
`reject_idea` komplett aus der Fälligkeits-Query gestrichen — mit der richtigen
Begründung, dass eine abgelehnte Idee kein Marktergebnis hat.

Kein Marktergebnis heißt aber nicht kein Erkenntniswert. Zwei echte Ablehnungen aus
dem laufenden Zyklus vom 01.08.2026:

> ABAT: *„Kein konkreter Katalysator … vorhanden; reines technisches
> Überverkauft-Signal ohne Trigger."*

> ALAB: *„**Kein fundamentaler Cross-Check (aktienfinder/Filings) verfügbar**, um
> 'Panik ohne fundamentale Zerstörung' von einem berechtigten strukturellen
> Abverkauf zu unterscheiden."*

Die erste ist eine Aussage über die Aktie. Die zweite ist eine Aussage über
**ATLAS' eigenen Recherche-Pool** — und genau die will F099 systematisch einsammeln.

**Ziel:** eine wöchentliche Stichprobe von `reject_idea`-Decisions bekommt ein
Urteil über die Recherche-Grundlage, nicht über die Aktie.

## 2. Kritische Betrachtung

### 2.1 Warum eine eigene Tabelle und nicht `review`

Der naheliegende Weg wäre, `reject_idea` einfach in `find_due_decisions`
aufzunehmen. **Das wäre falsch, und zwar teuer falsch.**

`review` ist der Datensatz, an dem der 8-Wochen-Wettbewerb gemessen wird. Jede
Auswertung darüber — Leaderboard, Verdict-Zählung je Persona, das F098-Retrieval —
setzt eine Decision voraus, die einen Markt erreicht hat. 90 `reject_idea`-Zeilen
gegen 8 `BUY` in der laufenden Saison: die Meta-Reviews würden jede dieser
Auswertungen dominieren, und `ReviewVerdict` müsste ein Thesen-Urteil über etwas
fällen, das nie eine Position war. `MetaReview` ist deshalb eine eigene Tabelle mit
einem eigenen Enum.

### 2.2 Das Verdict bewertet den Pool, nicht die Entscheidung

Ob eine Ablehnung richtig war, weiß niemand — die Position wurde nie eröffnet, es
gibt keinen Gegenbeweis. Ein Modell danach zu fragen, produziert Hindsight-Prosa.
Beantwortbar ist dagegen: *hatte die Persona genug, um zu entscheiden?* Daraus die
drei Werte:

| Verdict | Bedeutung | Adressat |
|---|---|---|
| `research_sufficient` | Pool trug die Entscheidung | niemand — alles in Ordnung |
| `research_gap` | die Ablehnung war im Kern „mir fehlten Daten" | **Ralfs Ingestion-Backlog** (`missing_source`) |
| `research_ignored` | der Pool hatte relevantes Material, die Persona nutzte es nicht | die Persona |

`research_ignored` ist nur entscheidbar, wenn das Modell **beides** sieht: die
verlinkte Recherche *und* den Pool desselben Zyklus zum selben Instrument. Der
Prompt liefert deshalb zwei getrennte Blöcke. Der Pool-Block ist auf das Instrument
der Decision eingeschränkt — ein Zyklus-Pool hat ~1000 Items, zwölf beliebige davon
wären Rauschen, gegen das das Modell argumentieren müsste.

### 2.3 Stichprobe, nicht Vollerhebung — und fair verteilt

§5.2 sagt „max. 5/Woche". Das ist die einzige relevante Kostenbremse: der Sweep
läuft wöchentlich, also ist `max_per_run` == pro Woche.

Die Auswahl ist **Round-Robin über Personas**, neuester Zyklus zuerst. Ohne das
frisst die ablehnungsfreudigste Persona das Kontingent — CONTRA lehnt weit mehr ab
als es kauft — und eine Stichprobe, in der nur eine Persona vorkommt, trägt keine
Aussage über die anderen. Das ist Invariante #10 dem Sinn nach, keine Optimierung.

Der Abbruch prüft das Limit **vor** dem Anhängen, nicht am Rundenende. F084 hat an
genau dieser Stelle live einen Review verschenkt (`limit=0` lieferte trotzdem eine
Zeile); hier kostet derselbe Fehler echtes Geld.

### 2.4 Lessons sind Fremdtext (Invariante #9)

Die zitierten Research-Items sind potenziell injiziert und reisen in
`<untrusted_research>`-Blöcken, exakt wie in F084. Das Verdict wird streng gegen das
Enum validiert; eine unparsebare Antwort wirft, statt still auf
`research_sufficient` zu fallen — ein erfundenes „alles in Ordnung" würde Ralf
sagen, seine Ingestion-Pipeline sei gesund.

`missing_source` wird verworfen, wenn das Verdict kein `research_gap` ist. Modelle
füllen Schema-Felder gern pflichtschuldig aus; ein Phantom-Eintrag im
Ingestion-Backlog wäre schlimmer als ein leeres Feld.

## 3. Design

| Baustein | Entscheidung |
|---|---|
| Tabelle | `meta_review`, unique auf `decision_id` (Idempotenz als DB-Constraint) |
| Auswahl | `reject_idea` + `archived_at IS NULL` + noch kein `meta_review` + kein deterministischer Ablehnungsgrund (§3.1) → Round-Robin je Persona, max. 5 |
| Rolle | dieselbe `review`-Rolle (Sonnet, shared) — ARCHITECTURE.md §5.1 führt das Meta-Review unter derselben Rolle |
| Zeitpunkt | Sonntag 18:30 ET, eine Stunde nach dem täglichen Review-Sweep |
| Thinking | `disabled` (F073/F084 — Sonnet 5 verbrennt sonst das Completion-Budget im internen Denkblock) |
| Embedding | wird geschrieben, aber noch nicht gelesen (§6) |
| Rollback | `meta_review.enabled: false` in `config/llm.yaml` |

Die Zustandsfreiheit der Kandidaten-Query ist dieselbe Konstruktion wie in F084: ein
Lauf, der auf halber Strecke stirbt, macht beim nächsten Mal weiter, und ein
Wiederholungslauf dupliziert nie.

### 3.1 Deterministische Ablehnungen gehören nicht in die Stichprobe

Befund aus dem Dry-Run auf der Box (01.08.2026, ohne LLM-Call): von den ersten fünf
gezogenen Kandidaten waren **zwei** `position_too_small_for_whole_share` und
`insufficient_price_history`. Das sind keine Urteile, das ist Arithmetik —
`persona_analysis` schreibt sie deterministisch, wenn die Positionsgröße unter eine
ganze Aktie fällt oder die Kurshistorie zu kurz ist. Die Recherche hat daran keinen
Anteil, das einzig mögliche Verdict wäre „der Pool war irrelevant" — für einen
Sonnet-Call und einen von fünf Wochen-Slots. 40 % des Kontingents für Nicht-Befunde.

`find_meta_review_candidates` filtert deshalb neun Maschinen-Codes heraus
(`_DETERMINISTIC_REJECTION_REASONS` plus den Präfix `unsupported_action:`).
Drin bleibt `"not specified"` — das ist der Fallback für eine **LLM**-Ablehnung, die
keinen Grund genannt hat, also eine echte Urteilsentscheidung, deren These und
Research-Verknüpfung sehr wohl bewertbar sind.

Zwei Fallen dabei, beide getestet:

* **`NULL NOT IN (...)` ist NULL, nicht true.** Ohne den expliziten
  `rejection_reason IS NULL`-Zweig hätte der Filter genau die Decisions
  herausgeworfen, die gar keinen Grund tragen — das Gegenteil der Absicht.
* **Drift.** Ein neuer Maschinen-Code in `persona_analysis` würde still anfangen,
  Kontingent zu fressen. `test_every_deterministic_rejection_reason_is_excluded`
  parst die Datei per `ast` und schlägt an, sobald ein `rejection_reason="…"`-Literal
  auftaucht, das im Deny-Set fehlt.

## 4. Tests

| Test | Sichert |
|---|---|
| `test_the_sample_is_spread_across_personas` | §2.3, die Fairness der Stichprobe |
| `test_archived_seasons_are_not_sampled` | F096-Logik gilt auch hier |
| `test_the_cap_holds_mid_round` / `test_limit_zero_samples_nothing` | jede Stichprobe zu viel ist ein bezahlter Call |
| `test_deterministic_rejections_are_not_sampled` | §3.1 — kein Wochen-Slot für Arithmetik |
| `test_a_decision_without_a_rejection_reason_is_still_sampled` | die `NULL NOT IN`-Falle |
| `test_every_deterministic_rejection_reason_is_excluded` | Drift-Wächter gegen neue Maschinen-Codes |
| `test_the_prompt_separates_used_research_from_the_available_pool` | §2.2 — ohne beide Blöcke ist `research_ignored` nicht entscheidbar |
| `test_missing_source_is_dropped_unless_the_verdict_is_a_gap` | §2.4, keine Phantom-Einträge im Backlog |
| `test_parse_raises_instead_of_defaulting` | kein erfundenes „alles in Ordnung" |
| `test_a_budget_stop_defers_instead_of_dropping` | Invariante #7 |
| `test_an_embedding_failure_does_not_cost_the_meta_review` | F098-Vertrag: die Zeile ist das Wertvolle |

**Ergebnis:** 828 passed (792 vor F098), Coverage 90,11 %, `ruff` und `mypy` sauber.

## 5. Nebenfunde (mitgefixt, nicht Teil des Zuschnitts)

**CI war seit F098 rot.** `uv run mypy src` scheiterte auf `main` mit 4 Fehlern
(Runs 30693326585 und 30693348867). Ohne die Fixes wäre auch dieser Commit rot:

1. **`scheduler.py` las `result.deferred`, das Feld heißt `deferred_budget`.** Der
   Zugriff steht in der `or`-Kette der Summary-Zeile des Review-Sweeps: sobald
   `reviewed == 0` — der Normalfall, sobald der Rückstand abgearbeitet ist —
   wurde er ausgewertet, warf `AttributeError`, und der umgebende `except`
   loggte **„review sweep failed"** samt Traceback für einen Lauf, dem schlicht
   nichts fällig war. mypy hatte das gemeldet, kein Test deckte es ab. Jetzt gibt es
   einen (`test_review_sweep_job_stays_quiet_when_nothing_was_due`).
2. **`graph.py:82`** deklarierte `embedding_provider: object | None` und reichte das
   an einen Parameter mit `EmbeddingProvider | None` weiter — F098-Verdrahtung, jetzt
   korrekt typisiert.
3. **`research_agents.py:208`** nutzte den `seen.add(...) or`-Dedup-Trick, den mypy
   zu Recht ablehnt (`set.add` gibt `None` zurück). Ersetzt durch
   `dict.fromkeys` — gleiche Semantik, gleiche Reihenfolge.

## 6. Ausgeklammert — mit Begründung

**Der Rückfluss der Meta-Lessons in `persona_analysis`.** Die Spalte
`lessons_embedding` wird von Anfang an geschrieben, gelesen wird sie nicht: das
F098-Retrieval (`find_lessons_for_persona`) fasst weiterhin nur `review` an.

Grund: das würde ändern, **was die Personas mitten in der laufenden Saison sehen**.
Ein Rückfluss von „du hast damals abgelehnt, obwohl der Katalysator im Pool stand"
kann das Ablehnungsverhalten in beide Richtungen verschieben — und der 8-Wochen-
Vergleich läuft. Das ist dieselbe Klasse von Eingriff wie die Scheduler-Aktivierung
(F032) und gehört Ralf vorgelegt, nicht nebenbei mitgeliefert. Weil die Spalte
mitläuft, ist die Freischaltung später eine Query-Änderung, kein Backfill.

**Kein UI.** Die Auswertung läuft bis auf Weiteres über SQL:

```sql
SELECT m.verdict, m.missing_source, count(*)
FROM meta_review m
GROUP BY 1, 2
ORDER BY 3 DESC;
```

## 7. Deployment

**Deployt am 01.08.2026, 14:56 MESZ.** Rollback-Anker vorher: ZFS-Snapshots
`apps/docker@pre-f099-20260801` **und** `apps/ix-apps/docker@pre-f099-20260801` —
das zweite ist das relevante, weil das Named Volume `atlas_postgres-data` unter
`/mnt/.ix-apps/docker/volumes/` liegt und damit *nicht* auf dem täglich
gesnapshotteten `apps/docker`.

Ablauf wie in `TRUENAS_HOMELAB.md` §5.2: rsync (88 Dateien) → `docker compose build
api web scheduler telegram-bot` → `up -d` → `alembic upgrade head`
(`c3d4e5f6a7b8 → d4e5f6a7b8c9`).

Verifiziert direkt nach dem Deploy:

| Prüfpunkt | Ergebnis |
|---|---|
| Container | alle 6 Up, `postgres`/`litellm`/`api` healthy |
| Migration | `alembic current` = `d4e5f6a7b8c9 (head)`, Tabelle `meta_review` mit `vector(1024)` + Unique-Constraint |
| Scheduler | `_meta_review_sweep_job` registriert, 0 Errors im Log |
| LAN-Health | `:8000/health` ok, `:3001/` 200, `:4000/health/liveliness` ok |
| Kandidaten-Query (Dry-Run, kein LLM-Call) | 5 Kandidaten aus 5 verschiedenen Portfolios — der Round-Robin greift. Beifang: die 2 deterministischen Ablehnungen, die zu §3.1 geführt haben |

Erster regulärer Lauf: Sonntag 18:30 ET. Sofortiger Probelauf ginge über
`run_meta_review_sweep` in einer `docker compose exec`-Shell — kostet dann echte
LLM-Calls.

**Der §3.1-Filter ist im obigen Deploy noch nicht enthalten** (er ist der Befund
*aus* dessen Verifikation) und braucht einen zweiten rsync + Rebuild vor Sonntag,
ohne Migration.
