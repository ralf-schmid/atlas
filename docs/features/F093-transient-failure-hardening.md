# F093 — Härtung gegen transiente Fehler in Ingestion & Fehler-Diagnose

**Status:** Implemented
**Phase:** 5 (Härtung)
**Deployed:** 2026-07-31
**Abhängigkeiten:** `src/ingestion/edgar_rss.py`, `src/ingestion/coingecko_global.py`,
`src/ingestion/aktienfinder_grabbing.py`, `src/llm/client.py`,
`src/orchestrator/scheduler.py`
Berührt keine Invariante — reine Robustheits-/Diagnose-Änderung, kein Risk-,
Order- oder HITL-Pfad.

## 1. Zieldefinition

Ralf bekam am 30./31.07.2026 weiterhin Telegram-Alarme („2x in Folge
fehlgeschlagen"), obwohl deutlich weniger als zuvor. Auswertung der Logs auf
`atlas-ugreen` (`docker logs atlas-scheduler-1 --since 30h`) ergab **vier**
unterschiedliche Ursachen, von denen drei transiente Upstream-Fehler sind, die
ATLAS unnötig zu Job-Fehlern eskaliert, und eine ein reines Diagnose-Problem ist.

Ziel: transiente Upstream-Fehler nicht mehr als Job-Fehler behandeln, und bei
echten Fehlern die Ursache **im Alarm** sichtbar machen statt nur im Container-Log.

## 2. Befund (Ist-Zustand, live gemessen 30.–31.07.2026)

| # | Job | Häufigkeit | Fehler | Bewertung |
|---|-----|-----------|--------|-----------|
| 1 | Alle Zyklen | 11/11 in 30h | `httpx 400` von LiteLLM | **kein Code-Bug** |
| 2 | `edgar_rss` | 12 in 30h (~20 %) | `httpx.ReadTimeout` | transient |
| 3 | `aktienfinder` | 2/2 Tage (100 %) | Playwright-Navigations-Timeout | Design-Fehler |
| 4 | `coingecko` | 2 in 30h | HTTP 503 und 400 | transient |

### 2.1 Befund #1 — Anthropic-Guthaben erschöpft (kein Code-Bug)

Seit **2026-07-30 06:00 UTC** beantwortet die Anthropic-API jeden Call mit:

```
{"type":"error","error":{"type":"invalid_request_error",
 "message":"Your credit balance is too low to access the Anthropic API."}}
```

216 Vorkommen in den LiteLLM-Logs. Jeder `persona_analysis`-Node scheitert daran,
LangGraph propagiert das, `run_one_cycle` wirft, der Zyklus gilt als
fehlgeschlagen. **Seither ist praktisch jeder Zyklus (Aktien + Krypto)
ausgefallen.** Behebung liegt bei Ralf (Guthaben aufladen), nicht im Code.

Was hier ein *echter* Mangel war: `LiteLLMClient.complete` rief nur
`response.raise_for_status()`, der Body ging verloren. Im Log stand 34 Stunden
lang ausschließlich `Client error '400 Bad Request'` — die eigentliche Aussage
stand im Body, den niemand sah. Siehe §3.4.

### 2.2 Befund #2 — EDGAR-RSS Read-Timeout

`HttpEdgarFeedProvider.fetch_current_filings` nutzte `timeout=10.0` ohne Retry.
Der Feed ist eine Live-Abfrage gegen den kompletten SEC-Filing-Index und braucht
regelmäßig länger. Bei 30-Minuten-Intervall = ~60 Läufe/Tag traf es 12 —
jeder einzelne davon wäre beim nächsten Lauf erfolgreich gewesen.

### 2.3 Befund #3 — aktienfinder `networkidle` (der teuerste)

```
page.goto(f"{_BASE_URL}/dividenden-profil/{isin}",
          wait_until="networkidle", timeout=30_000)
```

`networkidle` gilt als erreicht, wenn 500 ms lang keine Netzwerk-Anfrage läuft.
Die aktienfinder-Profilseiten halten Hintergrund-Traffic (Charts, Analytics) am
Leben — diese Bedingung wird nicht zuverlässig erreicht, der Timeout ist damit
Glückssache und nicht an die tatsächliche Bereitschaft der Seite gekoppelt.

Verschärfend: `run_daily_grab_live` baute die Snapshots per List-Comprehension.
Eine Exception bei *einem* ISIN riss den kompletten Tageslauf ab — an beiden
Tagen 0 statt 6 Snapshots:

```
snapshot_date | count      2026-07-29 | 6     ← letzter erfolgreicher Tag
--------------+------      2026-07-30 | —     ← SAP timeout, alle 6 verloren
                           2026-07-31 | —     ← Microsoft timeout, alle 6 verloren
```

### 2.4 Befund #4 — CoinGecko Free-Tier-Drosselung

`/api/v3/global` antwortete einmal mit 503 und einmal mit 400. Der Endpunkt
nimmt **keine** Request-Parameter entgegen — ein 400 kann dort kein echter
Client-Fehler sein, sondern ist Edge-Drosselung mit falschem Status-Code.
Manuelle Nachprüfung aus dem Container: 3/3 Anfragen HTTP 200.

## 3. Design

### 3.1 `src/ingestion/http_retry.py` (neu)

```python
def get_with_retry(send, *, label, retryable_statuses=RETRYABLE_STATUSES,
                   backoff_seconds=(2.0, 5.0)) -> httpx.Response
```

- Nimmt ein `send`-Callable statt selbst `httpx.get` zu rufen. Jeder Caller
  behält seinen eigenen Request-Aufbau (URL, Header, Timeout) — und die
  bestehenden Tests, die `src.ingestion.<modul>.httpx.get` patchen, bleiben gültig.
- Retry-fähig: alle `httpx.TransportError` (Read-/Connect-Timeout, Connect-Error)
  plus `RETRYABLE_STATUSES = {429, 500, 502, 503, 504}`.
- **4xx ist bewusst nicht dabei** — ein echter Client-Fehler wiederholt sich
  ewig, ein Retry verzögert nur den Alarm, den Ralf tatsächlich braucht.
- 3 Versuche, 2 s + 5 s Wartezeit. Bewusst kurz: die Jobs laufen in 30–60-Minuten-
  Intervallen, ein paar Sekunden Retry-Fenster sind gratis, ein langes würde den
  nächsten Lauf überlappen.
- Scheitern alle Versuche, propagiert die **letzte** Exception unverändert —
  der Failure-Alert des Schedulers sieht weiterhin den echten Upstream-Fehler.

### 3.2 EDGAR

Timeout 10 s → **30 s**, Aufruf über `get_with_retry`.

### 3.3 CoinGecko

Timeout 10 s → 20 s, Aufruf über `get_with_retry` mit
`retryable_statuses = RETRYABLE_STATUSES | {400}` (Begründung §2.4, im Code
kommentiert).

### 3.4 aktienfinder

Zwei getrennte Änderungen:

**(a) Deterministisches Warten statt `networkidle`.** `wait_until=
"domcontentloaded"` + `page.wait_for_selector(...)` auf genau das Element, das
der Extractor danach liest:

- Profilseite: `li.stockprofile-tiles__list-item` — daran hängt jeder Eintrag
  aus `aktienfinder.field_selectors`.
- Dividendenseite: `table tbody tr` — genau der Selector, den
  `extract_dividend_history` per `eval_on_selector_all` auswertet.

Navigations-Timeout 30 s → 45 s. Die Selektoren stehen als Modul-Konstanten im
Code (nicht in der Config), damit die Kopplung an den Extractor explizit ist und
nicht still von der YAML-Reihenfolge abhängt.

**(b) Pro-ISIN-Isolation.** Neue Funktion `_grab_isins`: ein fehlschlagender ISIN
wird geloggt und übersprungen, der Rest des Tages wird persistiert. Gleiche
Begründung wie die schon dokumentierte Toleranz von `extract_snapshot` gegenüber
fehlenden Selektoren — ein Teiltag schlägt keinen Tag. Scheitern **alle** ISINs,
fliegt der Fehler weiterhin: ein echter Ausfall (Seite down, Login kaputt) muss
den Failure-Alert auslösen und darf nicht still 0 Zeilen schreiben.

### 3.5 LiteLLM-Fehler-Body

`_raise_for_status_with_body` hängt den Response-Body an die Exception-Message,
Typ (`httpx.HTTPStatusError`), `request` und `response` bleiben unverändert —
bestehende Handler sind nicht betroffen. Auf 1 000 Zeichen gekürzt, weil ein
Provider-Fehler den ganzen Request zurückspiegeln kann und das Ergebnis in
Logzeile und Telegram-Alarm landet. Leerer Body → ursprüngliche Exception.

### 3.6 Zyklus-Alarm mit Ursache

`format_cycle_failure_cause(exc)` läuft die `__cause__`/`__context__`-Kette bis
zur innersten Exception (LangGraph verpackt den echten Fehler) und hängt eine
einzeilige, auf 400 Zeichen gekürzte Fassung an den Alarmtext:

```
⚠️ ATLAS-Zyklus us_equity-1 ist 2x in Folge fehlgeschlagen.
Ursache: HTTPStatusError: Client error '400 Bad Request' ... Response body:
{"error":{"message":"Your credit balance is too low ...
```

Zyklenschutz über eine `seen`-Menge — `raise X from X` würde sonst endlos laufen.

## 4. Testdefinition (vor der Umsetzung festgelegt)

| # | Test | Datei |
|---|------|-------|
| 1 | Erfolg beim 1. Versuch → kein Sleep | `tests/ingestion/test_http_retry.py` |
| 2 | `ReadTimeout`, dann 200 → Erfolg | ebd. |
| 3 | Jeder Status aus `RETRYABLE_STATUSES` wird retried (parametrisiert) | ebd. |
| 4 | 404 → sofort, kein Retry | ebd. |
| 5 | Zusätzlicher Status (400) wird honoriert | ebd. |
| 6 | Alle Versuche scheitern → letzter Fehler, 2 Sleeps | ebd. |
| 7 | Transport-Fehler erschöpft → Original-Exception | ebd. |
| 8 | `backoff_seconds` bestimmt Versuchszahl | ebd. |
| 9 | EDGAR retried `ReadTimeout` | `test_edgar_rss.py` |
| 10 | EDGAR nutzt Timeout 30 s | ebd. |
| 11 | CoinGecko übersteht 503 → 400 → 200 | `test_coingecko_global.py` |
| 12 | Ein fehlschlagender ISIN wird übersprungen, Rest bleibt | `test_aktienfinder_grabbing.py` |
| 13 | Screener-Felder werden in die verbleibenden Snapshots gemerged | ebd. |
| 14 | Scheitern alle ISINs → Exception fliegt weiter | ebd. |
| 15 | 400-Body landet in der Exception-Message | `tests/llm/test_client.py` |
| 16 | Body wird gekürzt | ebd. |
| 17 | Leerer Body → Original-Exception | ebd. |
| 18 | Alarm enthält `Ursache: RuntimeError: x` | `tests/orchestrator/test_scheduler.py` |
| 19 | Innerste Ursache aus verschachtelter Kette | ebd. |
| 20 | Ursache einzeilig + gekürzt | ebd. |
| 21 | Selbstreferentielle `__cause__`-Kette terminiert | ebd. |
| 22 | Angereicherte Message übersteht den Cause-Walk (§5.1) | `tests/llm/test_client.py` |

**Ergebnis:** 727 passed, 26 deselected. `ruff check` sauber,
`mypy src/risk src/broker` sauber.

## 5. Verifikation live (31.07.2026, `atlas-ugreen`)

Deployt per `scp` der sechs Quelldateien (jede einzeln mit vollem Zielpfad,
SHA-256 gegengeprüft) + `docker compose build api scheduler telegram-bot` +
`up -d`. Keine Compose-/Port-/Env-Änderung, daher **keine** Nachführung in
`ugreen-Box/Informationen/TRUENAS_HOMELAB.md` nötig.

**aktienfinder — der eigentliche Nachweis.** Job manuell im Container gestartet:

```
SNAPSHOTS: 6
 snapshot_date | count        symbol    | div_rows |   price
---------------+------     -------------+----------+------------
 2026-07-31    |     6      DE0007164600 |        8 | 158.22 EUR
 2026-07-29    |     6      DE0008430026 |        8 | 522.40 EUR
 2026-07-27    |     6      US0378331005 |        8 | 258.79 EUR
```

6/6 ISINs, jeweils mit echtem Kurs und 8 Dividendenzeilen — die Selector-Waits
liefern also vollständige Daten, nicht bloß leere Felder. 30./31.07. waren zuvor
0/6. Die Lücke vom 30.07. bleibt bestehen (nicht rückwirkend nachholbar).

**EDGAR / CoinGecko** gegen die echten Upstreams im neuen Image:

```
EDGAR new filings: 3
CoinGecko rows: 1
```

**Fehler-Diagnose** — im Container gegen den real fehlschlagenden LiteLLM-Call:

```
ALERT WOULD SAY -> HTTPStatusError: Client error '400 Bad Request' for url
'http://litellm:4000/chat/completions' ... Response body: {"error":{"message":
"litellm.BadRequestError: AnthropicException - ... Your credit balance is too low
```

### 5.1 Beim Live-Test gefunden und behoben

Die erste Fassung von §3.5 und §3.6 hoben sich gegenseitig auf: der Body wurde per
`raise httpx.HTTPStatusError(...) from exc` an eine **neue** Exception gehängt,
während `format_cycle_failure_cause` bis zur innersten `__cause__` läuft — und
damit genau an der Anreicherung vorbei, zurück auf die nackte Originalmeldung.
Der erste Live-Lauf zeigte weiterhin nur `Client error '400 Bad Request'`.

Behoben, indem `_raise_for_status_with_body` die **bestehende** Exception per
`exc.args` anreichert und mit blankem `raise` weiterwirft — keine neue Exception,
keine Kettenänderung. Regressionstest
`test_error_body_survives_the_cycle_alert_cause_walk` deckt genau dieses
Zusammenspiel ab (Test 22).

## 6. Rollback

Reiner Code-Rollback (`git revert` + Image-Rebuild). Kein Config-Flag, keine
Migration, kein Datenmodell berührt. Die Änderungen sind additiv-defensiv: im
schlimmsten Fall verhält sich das System wie vorher, nur mit längeren Timeouts.

## 7. Offen / Nicht Teil dieses Features

- **Anthropic-Guthaben** (Befund #1) — Ralfs Aufgabe, kein Code.
- Ein Zyklus scheitert weiterhin komplett, wenn *eine* Persona am LLM-Call
  scheitert. Eine Pro-Persona-Isolation analog §3.4(b) wäre denkbar, berührt
  aber die Fairness-Invariante (#10: eine Persona, die einen Zyklus überspringt,
  hat einen anderen Informationsstand) — bewusst nicht ohne Ralfs Entscheidung.
