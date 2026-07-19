# F077 — Sell/Close-Decision-Pfad

Status: umgesetzt, Live-Smoke-Test am 19.07.2026 (Sonntag) einen echten Bug
gefunden + behoben, Retest bei offenem US-Markt noch ausstehend (siehe §7)
Datum: 2026-07-18
Phase: 5 (Voraussetzung für den Review-Agenten, siehe unten)

## 1. Zieldefinition

Bislang kann jede Persona nur `buy`, `hold` oder `reject_idea` entscheiden —
`_resolve_decision` (`src/orchestrator/persona_analysis.py`) fängt jedes
`sell`/`close` im Fallback als `unsupported_action:sell` ab und lehnt es ab.
Positionen können also nur wachsen, nie geschlossen werden (bereits in
`docs/dod/phase-4.md` als bewusst zurückgestellt vermerkt, F021/F024).

Auslöser: der geplante Review-Agent (ARCHITECTURE.md §8, P5) verlangt
*"jede geschlossene Position hat binnen 7 Tagen ein Review mit Verdict"* —
ohne einen Weg, eine Position zu schließen, hat der Review-Agent nie einen
echten Auslöser für diesen zentralen DoD-Punkt. F077 ist damit die
Voraussetzung, nicht Teil des Review-Agenten selbst (der kommt als
eigenständiges Folge-Feature, sobald echte geschlossene Positionen
existieren).

**Scope dieses Features:** ausschließlich `close` (vollständiger Ausstieg aus
einer Position). `sell` (Teilverkauf/-reduktion) ist laut
`ARCHITECTURE.md §3.6` (`decision.action[buy|sell|hold|close|reject_idea]`)
ein eigener, semantisch anderer Fall — ein Teilverkauf muss den bestehenden
GTC-Stop canceln *und* für die verbleibende Restmenge einen neuen platzieren
(Invariante #4 bleibt für die Restposition in Kraft), während `close` den
Stop nur canceln muss (keine Restposition, kein neuer Stop nötig). `close`
ist die Mindestmenge, um den Review-Agenten zu entsperren, und deutlich
einfacher korrekt umzusetzen. **`sell` (Teilausstieg) ist bewusst
Non-Scope** und folgt als eigenes Feature, falls eine Persona das später
braucht (die Charter-Texte sprechen von "Exit bei Momentum-Bruch" o. Ä., aber
keine Persona-Guardrail verlangt heute explizit einen Teilausstieg).

## 2. Kritische Betrachtung

**Invariante #1 (Risk-Gate deterministisch):** `evaluate_decision`
(`src/risk/gate.py`) hat bereits einen `action: TradeAction`-Parameter mit
`TradeAction.CLOSE` im Enum (`src/risk/models.py`) — nur `_evaluate_buy_only_rules`
wird ausschließlich bei `TradeAction.BUY` aufgerufen. Für `CLOSE` bleiben genau
zwei Prüfungen wirksam: `max_trades_per_day` (unverändert sinnvoll — ein Close
zählt als Trade) und der Circuit Breaker, der für `CLOSE` **nicht** greift
(`if circuit_breaker_triggered and action == TradeAction.BUY` — korrekt so:
der Circuit Breaker soll Schließen *ermöglichen*, nicht verhindern, siehe
Invariante #8 "sell_only"-Modus). Keine Änderung an `evaluate_decision`
nötig, nur ein neuer Call-Site mit `action=TradeAction.CLOSE`.

**Invariante #2 (Privilege Separation):** unverändert — `execute_decision`
(`src/orchestrator/trading.py`) bleibt der einzige Ort, der Orders platziert,
und tut das weiterhin ausschließlich für `APPROVED`-Decisions per DB-ID.

**Invariante #3 (keine Order ohne Decision):** `close` durchläuft denselben
`_persist_decision`-Pfad wie `buy` — Decision zuerst, Order danach, exakt
gleiches Schema.

**Invariante #4 (Stop-Loss als GTC-Order):** das ist der eigentliche Kern
dieses Features. Ein `close` muss den/die bestehenden Stop(s) für dieses
Instrument canceln, *bevor* verkauft wird. Komplikation, durch F071 real
geworden: eine Position kann aus **mehreren Buy-Tranchen** bestehen (Top-up
auf ein bereits gehaltenes Instrument), und jede Tranche hat ihren *eigenen*
Stop-Order (`_resolve_buy_decision` ruft `place_order` pro Buy-Entscheidung
auf, nicht kumulativ). Ein `close` muss also **alle** noch offenen
Stop-Order-IDs für dieses Portfolio+Instrument einsammeln (Query über
`order_record.raw["stop_order_id"]` für alle `BUY`-Decisions desselben
Portfolios/Instruments) und alle canceln, nicht nur die zuletzt platzierte.
Cancel ist **best-effort**: ein Stop, der zwischen Persona-Entscheidung und
Ausführung bereits gefeuert hat (Race), lässt sich nicht mehr canceln — das
wird nicht als Fehler behandelt (analog zum bestehenden
`_is_duplicate_client_order_id`-Muster in `alpaca_paper.py`), weil die
tatsächliche Verkaufsmenge (`decision.quantity`, zum Entscheidungszeitpunkt
festgeschrieben — selbes Muster wie bei `buy`) im schlimmsten Fall beim
echten Broker fehlschlägt und dann wie jeder andere Ausführungsfehler
behandelt wird (`_maybe_execute_decision`s bestehender try/except → `AgentRun
FAILED`, nicht fatal für den Zyklus). Keine neue Fehlerbehandlung nötig, nur
Wiederverwendung des bestehenden Musters.

**Invariante #5 (Paper/Live-Trennung, HITL):** `close` durchläuft denselben
HITL-Gate wie `buy` (`is_hitl_required` + `mark_hitl_pending`), symmetrisch,
keine Sonderbehandlung — ein Close ist genauso eine echte Order wie ein Buy.
Aktuell ist HITL für `paper` ohnehin aus (F072); für `live` bleibt es an.

**Invariante #10 (Fairness):** `close` wird generisch in
`_OUTPUT_SCHEMA_INSTRUCTIONS`/`_TOOL_USAGE_HINT` ergänzt (wie schon
`_TOOL_USAGE_HINT` bei F045) — kein Charter-Text ändert sich, kein
`charter_version`-Bump nötig. Alle 6 Personas bekommen die neue Fähigkeit
gleichzeitig und identisch.

**BrokerAdapter-Protokoll-Erweiterung:** `place_order()` ist laut Docstring
für "Markteintritt plus verpflichtender GTC-Stop" gebaut — für einen
schließenden Verkauf semantisch falsch (kein neuer Stop nötig; die
Implementierung würde sonst einen sinnlosen "Rückkauf-Stop" in der
Gegenrichtung anlegen, siehe `internal_ledger.py`s `_OPPOSITE_SIDE`-Mechanik).
Neue Protocol-Methode `close_position()` statt Überladen von `place_order()`
mit nullable Buy-spezifischen Feldern — klarer Vertrag, kein "None heißt hier
etwas anderes"-Sonderfall in `OrderResult`. Eigener Rückgabetyp
`ClosePositionResult` (kein neuer Stop, kein `stop_loss_price`-Feld, das für
einen Close nie zuträfe).

**Kosten:** keine (kein LLM-Mehraufwand — `close` ersetzt in der Antwort nur
eine der bisherigen drei Optionen, kein zusätzlicher Call).

**Persistenz/Migration:** keine Schema-Änderung — `DecisionAction.CLOSE` und
`TradeAction.CLOSE` existieren bereits in `src/db/models.py`/`src/risk/models.py`.

## 3. Testdefinition (vor Umsetzung)

**`tests/broker/test_internal_ledger.py`** (neu, analog zu den bestehenden
`place_order`-Tests):
1. `close_position` verkauft die volle gehaltene Menge, Cash steigt um
   `qty * last_price`, Position verschwindet aus `get_positions()`.
2. Übergebene `stop_order_ids` werden aus `pending_stops` entfernt.
3. Eine nicht (mehr) existierende `stop_order_id` in der Liste wird
   stillschweigend ignoriert (kein Fehler).
4. Crash-Replay: zweiter Aufruf mit derselben `decision_id` liefert das
   identische `ClosePositionResult`, ohne den Fill erneut anzuwenden
   (spiegelt den bestehenden `place_order`-Idempotenz-Test).
5. Verkauf von mehr als gehalten wirft (bestehendes `_apply_fill`-Verhalten,
   nur über den neuen Call-Pfad verifiziert).

**`tests/broker/test_alpaca_paper.py`** (neu):
1. `close_position` ruft `cancel_order_by_id` für jede übergebene
   `stop_order_id` auf, dann `submit_order` mit einer einfachen
   `MarketOrderRequest` (kein `OrderClass.OTO`, kein `StopLossRequest`).
2. Ein `APIError` beim Canceln einer einzelnen `stop_order_id` (bereits
   gefeuert/nicht mehr vorhanden) bricht den Close nicht ab — die übrigen IDs
   werden trotzdem verarbeitet, der Verkauf wird trotzdem platziert.

**`tests/risk/test_gate.py`** (Ergänzung, kein neuer Testfall nötig falls
schon vorhanden — verifizieren): `evaluate_decision(action=TradeAction.CLOSE,
...)` während `circuit_breaker_triggered=True` liefert `approved=True` (kein
`circuit_breaker_sell_only`-Reject) — falls dieser Fall noch nicht explizit
getestet ist, einen Test ergänzen.

**`tests/orchestrator/test_persona_analysis.py`** (neu, analog zu den
bestehenden `_resolve_buy_decision`-Tests):
1. `action=close` auf einem tatsächlich gehaltenen Instrument →
   `DecisionAction.CLOSE`, `quantity` = exakt die gehaltene Menge,
   risk-approved (kein Circuit-Breaker-Blocker), landet bei HITL aus direkt
   auf `EXECUTED`.
2. `action=close` ohne bestehende Position im selben Instrument →
   `reject_idea`, `rejection_reason="no_open_position"`.
3. `action=close` ohne `instrument` → `reject_idea`,
   `rejection_reason="missing_instrument"` (Symmetrie zu `buy`).
4. `max_trades_per_day` bereits ausgeschöpft → `close` wird trotzdem
   risk-rejected (die einzige Regel, die für `CLOSE` noch greift).

**`tests/orchestrator/test_trading.py`** (neu, analog zu den bestehenden
`execute_decision`-Tests für `buy`):
1. `execute_decision` für eine `CLOSE`-Decision sammelt alle
   `stop_order_id`s aus vorherigen `BUY`-`order_record`s desselben
   Portfolios+Instruments und reicht sie an `close_position()` weiter.
2. Zwei Buy-Tranchen (zwei separate Stop-Order-IDs) → beide IDs landen in
   einem einzigen `close_position()`-Aufruf.
3. `order_record` für den Close wird korrekt persistiert
   (`decision_id`, `status`, `raw={"qty":..., "side": "sell", "closed": true}`).

Zusätzlich: **Paper-Smoke-Test** nach Implementierung — ein reales offenes
Paper-Position (z. B. eine der bestehenden VULTURE/CHARTIST-Positionen auf
`atlas-ugreen`) manuell per `close`-Decision schließen und verifizieren, dass
(a) der/die ursprüngliche(n) Stop(s) im Alpaca-Dashboard tatsächlich
gecancelt sind und (b) die Position auf 0 steht — bevor das live in den
Scheduler-Zyklus geht.

## 4. Implementierung

- `src/broker/protocol.py` — neuer `ClosePositionResult`-Dataclass, neue
  `close_position()`-Methode auf dem `BrokerAdapter`-Protocol.
- `src/broker/internal_ledger.py` — `close_position()`: cancelt die
  übergebenen `stop_order_ids` best-effort (`pending_stops.pop(..., None)`),
  verkauft die volle Menge über das bestehende `_apply_fill` (No-Shorting-Guard
  bleibt unverändert wirksam), gleiche Crash-Idempotenz wie `place_order`
  (F027) über `executed_decisions`.
- `src/broker/alpaca_paper.py` — `close_position()`: cancelt jede
  `stop_order_id` best-effort (`APIError` pro ID abgefangen, nicht fatal),
  platziert danach einen einfachen `MarketOrderRequest` (kein `OrderClass.OTO`,
  `TimeInForce.DAY` für fraktionale Mengen wie in F051), gleiche
  Duplicate-Client-Order-ID-Recovery wie `place_order` (F027).
- `src/orchestrator/persona_analysis.py` — `"close"` in
  `_OUTPUT_SCHEMA_INSTRUCTIONS` ergänzt (generischer Infra-Text, kein
  Charter-Change, kein `charter_version`-Bump). Neue
  `_resolve_close_decision()`: `missing_instrument` bei fehlendem Instrument,
  `no_open_position` wenn `risk_state.positions` keinen passenden Bestand
  zeigt, sonst `evaluate_decision(action=TradeAction.CLOSE, ...)` und derselbe
  HITL-Gate wie bei `buy`. Menge kommt immer aus dem echten Bestand
  (`position.qty`), nie von der LLM-Antwort.
- `src/orchestrator/trading.py` — `execute_decision()` verzweigt für
  `DecisionAction.CLOSE` in `_execute_close()`. Neue
  `_collect_open_stop_order_ids()`: sammelt alle `stop_order_id`s aus
  vorherigen `BUY`-`order_record`s desselben Portfolios+Instruments (F071:
  mehrere Buy-Tranchen → mehrere Stops), reicht sie an `close_position()`
  weiter. `order_record.raw` bekommt `{"qty", "side", "closed": true}`.
- Kein Alembic-Migrations-Bedarf — `DecisionAction.CLOSE`/`TradeAction.CLOSE`
  existierten bereits im Schema.

## 5. Test & Verifikation

- Neue Tests exakt wie in §3 definiert:
  `tests/broker/test_internal_ledger.py` (5 neue),
  `tests/broker/test_alpaca_paper.py` (6 neue),
  `tests/orchestrator/test_persona_analysis.py` (4 neue),
  `tests/orchestrator/test_trading.py` (4 neue). `tests/risk/test_gate.py`
  hatte den Circuit-Breaker-Test für `CLOSE`
  (`test_circuit_breaker_does_not_block_close`) bereits — keine Ergänzung
  nötig.
- `uv run pytest -q` (lokaler Test-Postgres): **625 passed** (607 + 18 neue),
  `-m integration`: **18 passed, 2 skipped** (unverändert). `uv run ruff
  check`/`format --check`, `uv run mypy src` (ganzes Repo): clean.
- **Coverage-Gate** (`tests/risk/ tests/broker/ --cov-fail-under=100`,
  identisch zum CI-Job): weiterhin **100 % Line + Branch** für `src/broker/*`
  und `src/risk/*`.
- **Noch nicht gemacht (Stand vor dem Smoke-Test):** der Paper-Smoke-Test
  gegen eine echte offene Position auf `atlas-ugreen` (§3). Siehe §7 für das
  Ergebnis des ersten Versuchs.

## 6. Rollback-Pfad

Additiv auf allen Ebenen: eine neue Protocol-Methode, eine neue
Decision-Action-Verzweigung, kein Schema-Change. Ein Revert dieses Commits
nimmt der Codebasis nur die Fähigkeit, `close` zu verarbeiten — bestehende
`buy`/`hold`/`reject_idea`-Pfade sind unverändert.

**Vor dem Deploy auf `atlas-ugreen` noch offen (bewusst, Ralfs Entscheidung
nötig):** HITL ist für `paper` seit F072 aus — sobald dieser Code deployt ist,
kann jede Persona im nächsten Scheduler-Zyklus autonom eine echte Position
schließen, ohne dass Ralf vorher zustimmt (nur die Telegram-Trade-Info danach,
wie bei `buy`). Das ist die *erste* Position, die dieses System je real
schließen würde. Empfehlung: vor dem Deploy den in §3 beschriebenen
Paper-Smoke-Test manuell (nicht über den Scheduler) gegen eine echte
Alpaca-Paper-Position fahren und im Dashboard verifizieren, dass Stop(s)
gecancelt und die Position auf 0 sind — erst danach in den laufenden
Scheduler-Zyklus lassen.

## 7. Live-Smoke-Test (19.07.2026, gemeinsam mit Ralf)

**Ablauf:** neues Image nur für `scheduler` gebaut (`docker compose build
scheduler`), **nicht** deployt/neugestartet — der laufende
`atlas-scheduler-1`-Container blieb während des gesamten Tests auf dem alten
Image (kein autonomer Close-Zugriff). Manuelles Einmal-Skript über `docker
compose run --rm scheduler` (frischer Wegwerf-Container auf dem neuen Image,
mit denselben Trading-Credentials wie der Live-Service): echte `CLOSE`-Decision
für VULTURE/KEEL (11 Stück, eine Buy-Tranche, ein Stop) gebaut, direkt
`APPROVED` (kein LLM/HITL — reiner Mechanik-Test), `execute_decision`
aufgerufen.

**Ergebnis erster Versuch — echter Bug gefunden:** der Sell schlug fehl:
`insufficient qty available for order (requested: 11, available: 0),
held_for_orders: 11`, referenzierte den soeben gecancelten Stop
(`e1b1b205-...`). Der Stop stand danach über 30s auf `PENDING_CANCEL`, nicht
`CANCELED`. **Sicherheitslage unkritisch:** die Order-Transaktion wurde beim
Fehler sauber zurückgerollt (kein Waisen-Datensatz), und weil der Cancel nie
bestätigt wurde, blieb der ursprüngliche Stop für KEEL die ganze Zeit faktisch
aktiv — Invariante #4 war zu keinem Zeitpunkt verletzt.

**Root Cause:** `cancel_order_by_id`, das ohne Exception zurückkehrt, heißt
bei Alpaca nur "Cancel angenommen", nicht "Cancel vollzogen" — die Freigabe
der gehaltenen Stückzahl passiert asynchron. Sehr wahrscheinlich verstärkt
(ggf. verursacht) dadurch, dass der Test an einem Sonntag lief (US-Markt zu) —
Alpacas Paper-Matching-Engine scheint Order-State-Übergänge primär während
der Handelszeiten zu verarbeiten.

**Fix:** `AlpacaPaperAdapter.close_position()` wartet jetzt nach einem
akzeptierten Cancel aktiv auf dessen Auflösung (`_wait_for_hold_release`,
Poll alle 2s, Timeout 30s) — akzeptiert `CANCELED`/`EXPIRED`/`REJECTED`/`FILLED`
als "Hold freigegeben", wirft sonst nach Timeout einen klaren `RuntimeError`
statt den Sell überhaupt zu versuchen. Nur für Stop-IDs, deren Cancel-Aufruf
tatsächlich ohne Fehler durchging (ein Cancel, der mit `APIError` fehlschlägt,
z. B. weil der Stop schon gefeuert/weg ist, ist bereits terminal — kein
Warten nötig). `InternalLedgerAdapter` braucht das nicht (Cancel dort ist
synchron, kein Broker-Roundtrip).

6 neue/geänderte Tests in `tests/broker/test_alpaca_paper.py` (Poll-Erfolg
über mehrere `PENDING_CANCEL`-Antworten, Timeout-Pfad, unerwarteter
Response-Typ, `time.sleep` in Tests gemockt). `uv run pytest -q`: **628
passed**. Coverage-Gate `src/risk` + `src/broker`: weiterhin **100 %**.

**Noch offen:** Retest bei tatsächlich offenem US-Markt (werktags, America/
New_York-Handelszeit), um zu bestätigen, dass der Cancel dann tatsächlich
innerhalb der 30s-Timeout auflöst und die ganze Kette (Cancel → Sell →
Position 0) im Live-Fall durchläuft — bislang nur der Bugfix selbst lokal
verifiziert, der eigentliche End-to-End-Beweis mit echtem Broker steht noch
aus. Scheduler auf der Box weiterhin auf altem Image, kein Deploy.
