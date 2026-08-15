# F105 — Alpaca News + Screener als geteilte Research-Quellen

Status: live auf der Box (15.08.2026), Entitlement-Prüfung am ersten Lauf offen (§5)
Datum: 2026-08-11
Phase: 3-Nachzügler (Ingestion), wirkt auf den Pool aller Personas

## 1. Zieldefinition

Der geteilte Research-Pool hat zwei Lücken, die `alpaca-py` (bereits Dependency)
ohne neue Credential schließt — beide in ADR-0015 als Folgearbeit festgehalten:

1. **News ohne Symbolbezug.** `market_news_headline` speist sich aus Yahoos
   Top-Stories-RSS (F058). Der Feed liefert Schlagzeile, Quelle, URL — aber
   **kein Instrument-Tagging**. Die daraus gebauten `research_item`-Zeilen haben
   `instruments = []`, tauchen also in keiner symbolbezogenen Suche auf
   (`search_research_pool`, F045) und lassen sich einer Position nicht zuordnen.
   Alpacas News-Endpoint liefert dieselbe Art Meldung **mit `symbols`**.
2. **Keine Tagesauffälligkeiten.** Es gibt keinen Kanal für „was bewegt sich
   heute überhaupt". VULTUREs Screener filtert hart auf Penny-Stocks
   (`max_price`), die aktienfinder-Discovery liefert Qualitätswerte — beides
   bewusst eng. Alpacas Screener-Endpoints (Most Actives, Gainer/Loser) sind
   genau der breite, tagesaktuelle Impuls, den HYPE (Narrativ/Momentum) und
   CONTRA (Gegenbewegung nach Ausschlägen) laut Charter suchen.

**Scope:** zwei Ingestion-Jobs (`alpaca_news`, `alpaca_screener`), Instrument-
Tagging an `market_news_headline`, neue Tabelle `market_mover`, Synthese in den
geteilten Pool, Config + Scheduler-Einträge.
**Non-Scope:** Ablösung der Yahoo-Quelle (läuft parallel weiter), Volltext-/
Content-Ingestion (siehe §2), Options-/Forex-/Index-Daten, persona-spezifische
Filter auf den neuen Quellen.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, geprüft | Beide Quellen landen ausschließlich als `research_item` im **geteilten** Pool, identisch sichtbar für alle sechs Personas. Kein Filter, kein Persona-Bezug in der Ingestion. Dass HYPE/CONTRA/VULTURE mit Movern mehr anfangen können als GUARDIAN, ist Charter-Wirkung, kein Informationsvorsprung — GUARDIAN sieht dieselben Zeilen. |
| #9 Untrusted Content | ja, zentral | News-Schlagzeilen sind Fremdtext und potenziell feindlich (Prompt Injection). Sie gehen denselben Weg wie F058: als getaggter Datenblock über `research_item.summary` in die Persona-Prompts, nie in einen System-Prompt. **`include_content=False`** — Alpacas Volltext (Benzinga) wird gar nicht erst geholt, gespeichert werden Schlagzeile, Quelle, URL, Symbole, Zeitstempel. Damit gilt die „keine Volltexte in Repo/UI"-Regel aus CLAUDE.md unverändert. |
| Kosten | ja, gedeckelt | **Der eigentliche Kostenhebel dieses Features**: jede zusätzliche `research_item`-Zeile vergrößert den Persona-Prompt in *jedem* der 4 Zyklen × 6 Personas. Deshalb harte Config-Obergrenzen: `alpaca_news.limit` (Default 50 je Lauf) und `alpaca_screener.top` (Default 10 je Kategorie). Die Ingestion selbst kostet nichts (keine LLM-Calls). Rechnung und Rollback in §6. |
| #2 Privilege Separation | nein | Reine Ingestion, kein Order-Pfad, keine Order-Fähigkeit. |
| #6 Secrets | nein | Derselbe `ALPACA_MARKET_DATA_*`-Key wie F008/F010, keine neue Env-Var. |

**Design-Entscheidungen:**

1. **News in die bestehende Tabelle, nicht in eine neue.** Eine Alpaca-Meldung
   ist strukturell dasselbe wie eine Yahoo-Meldung; `market_news_headline`
   bekommt lediglich die fehlende Spalte `instruments`. Damit bleibt es ein
   `source_type` (`market_news`) für Personas und die Suche, und die Yahoo-Zeilen
   (leeres Array) funktionieren unverändert weiter. Provenienz steckt im
   `guid`-Präfix (`alpaca:<id>`), das zugleich der Idempotenz-Schlüssel ist.
2. **Mover in eine eigene Tabelle.** `screener_result` gehört semantisch VULTURE
   („VULTURE-Screener-Kandidat", F010) — Mover dort einzumischen würde die
   Summary-Texte und die Kandidatenliste verfälschen. `market_mover` trennt
   Kategorie (`most_active`/`gainer`/`loser`), Markt (`stocks`/`crypto`) und
   Rang sauber.
3. **Krypto-Mover von Anfang an mit.** Ein Config-Eintrag mehr, kein zusätzlicher
   Code — und CRYPTOR bekommt denselben Impulstyp wie die Aktien-Personas
   (Parität, nicht Bevorzugung).
4. **News ohne Symbol-Filter abfragen.** Das Universum umfasst je nach Tag
   200–400 Ticker; die alle in einen `symbols`-Query zu packen wäre eine
   fragile Riesen-URL. Der ungefilterte Feed liefert dieselben Meldungen samt
   `symbols`-Tagging, gedeckelt über `limit`.
5. **Idempotenz wie überall:** News per `guid`-Unique (`alpaca:<id>`), Mover per
   `(market, category, symbol, screened_at)`, wobei `screened_at` der
   `last_updated`-Zeitstempel der API-Antwort ist. Ein doppelter Lauf
   überschreibt, er dupliziert nicht.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/ingestion/test_alpaca_news.py`:

1. `test_provider_maps_news_to_headline` — API-Antwort → `Headline` inkl.
   `symbols`; `guid` bekommt das `alpaca:`-Präfix.
2. `test_provider_requests_headlines_without_content` — `include_content` ist
   `False` und `exclude_contentless` ist `True` (Invariante #9 / kein Volltext).
3. `test_sync_is_idempotent` — derselbe Lauf zweimal ⇒ eine Zeile, aktualisiert.
4. `test_sync_respects_configured_limit` — `limit` aus der Config landet im
   Request (Kostendeckel).

`tests/ingestion/test_alpaca_screener.py`:

5. `test_sync_writes_most_actives_with_rank` — Rang folgt der API-Reihenfolge.
6. `test_sync_writes_gainers_and_losers` — beide Kategorien, korrekt getrennt.
7. `test_sync_covers_configured_market_types` — `stocks` + `crypto`.
8. `test_sync_is_idempotent` — Wiederholung mit gleichem `last_updated` ⇒ keine
   Duplikate.

`tests/orchestrator/test_research_synthesis.py`:

9. `test_market_news_research_item_carries_instruments` — die Symbole der
   Meldung landen in `research_item.instruments` (der eigentliche Zweck von
   Baustein 1).
10. `test_market_mover_research_items` — je Kategorie eine Zeile mit
    `source_type='market_mover'`, Symbol in `instruments`, lesbarer deutscher
    Summary-Text.
11. `test_market_movers_outside_window_are_skipped` — Fensterlogik wie bei allen
    anderen Quellen (`synced_at`).

`tests/ingestion/test_scheduler.py`:

12. Job-Registrierung um `ingestion-alpaca-news` und `ingestion-alpaca-screener`
    erweitert (bestehender Set-Vergleich).

## 4. Implementierung

- `src/db/models.py`: `MarketNewsHeadline.instruments` (ARRAY(String),
  Default `[]`), neue Tabelle `MarketMover`.
- Alembic `c9e8d7f6a5b4`: `add_column` + `create_table`, Unique-Constraint
  `uq_market_mover_market_category_symbol_screened`.
- `src/ingestion/alpaca_news.py`: `AlpacaNewsProvider` (Protocol +
  `alpaca-py`-Implementierung), `sync_news_headlines`, `run_alpaca_news_sync`.
- `src/ingestion/alpaca_screener.py`: `AlpacaScreenerProvider`,
  `sync_market_movers`, `run_alpaca_screener_sync`.
- `src/orchestrator/research_synthesis.py`: `instruments` aus der News-Zeile
  durchreichen; `_research_items_from_market_movers` ergänzt.
- `src/ingestion/scheduler.py`: zwei Jobs (Intervall, Default 60 Min) mit dem
  bestehenden Fehler-Alert-Wrapper.
- `config/ingestion.yaml`: Sektionen `alpaca_news`, `alpaca_screener`,
  Schedule-Einträge.

## 5. Test & Rollout

- `uv run pytest`: **948 passed, 26 deselected** (Stand 11.08.2026; 937 nach
  F104). `ruff check` / `ruff format --check` / `mypy src`: clean.
- **Deployment (Ralf, auf der Box):** `alembic upgrade head`, dann
  `docker compose build api scheduler` + `up -d api scheduler`.
- **Vor dem Rollout zu prüfen — Entitlement:** der Marktdaten-Key hat nur
  IEX-Entitlement (kein SIP, siehe `market_data_sync.py`). Ob die
  Screener-Endpoints (`most-actives`, `movers`) und der News-Endpoint auf dieser
  Stufe freigeschaltet sind, ließ sich hier ohne Credentials **nicht**
  verifizieren. Erster Lauf beobachten: bei fehlendem Entitlement schlägt der
  Job mit einem Alpaca-`APIError` fehl und meldet sich nach zwei Fehlläufen per
  Telegram (bestehender `_run_with_failure_alert`-Pfad) — kein anderer Job und
  kein Zyklus wird dadurch beeinträchtigt. Falls nur eine der beiden Quellen
  entitled ist, den anderen Schedule-Eintrag auf `enabled: false` setzen.
- **Nach dem ersten Lauf verifizieren** (hier nachtragen): Zeilenzahl in
  `market_news_headline` mit `guid LIKE 'alpaca:%'` und in `market_mover`;
  danach im nächsten Zyklus stichprobenhaft ein `research_item` mit
  `source_type='market_mover'` und eines mit gefülltem `instruments` in der UI
  (Decision Journal / Agent Trace) ansehen.
- **Rollback-Pfad:** `schedule.alpaca_news.enabled: false` bzw.
  `schedule.alpaca_screener.enabled: false` in `config/ingestion.yaml` — die
  Jobs werden dann gar nicht erst registriert, die Synthese findet nichts Neues
  und der Pool sieht aus wie vorher. Kein Deploy, kein Schema-Rückbau nötig.

## 6. Kostenabschätzung und offene Punkte

- **Prompt-Wirkung:** bei Defaults kommen pro Tag grob 50 News-Zeilen (à ~1
  Summary-Zeile) und 3 Kategorien × 10 Mover × 2 Märkte = 60 Mover-Zeilen dazu.
  Ein Zyklus sieht davon nur das Delta seit dem letzten Zyklus. Grobe Hausnummer:
  einige Tausend zusätzliche Prompt-Token je Persona und Zyklus — spürbar, aber
  weit unter dem Kopf des 1-$-Caps je Persona/Tag (ADR-0008), und der
  Cost-Guard greift ohnehin doppelt (`src/llm/cost_guard.py`). **Nach dem ersten
  vollen Tag `cost_ledger` gegenprüfen** und bei Bedarf `limit`/`top` senken —
  das ist der feinere Regler als der Aus-Schalter.
- Mover-Zeilen ohne Kursbezug zum eigenen Portfolio sind für GUARDIAN
  wahrscheinlich Rauschen. Bewusst nicht gefiltert: eine Persona-abhängige
  Vorauswahl wäre genau der Fairness-Verstoß, den Invariante #10 ausschließt.
  Wenn sich das im Review als Problem zeigt, gehört die Konsequenz in die
  Charter, nicht in die Ingestion.
- Der News-Endpoint liefert auch ein `summary`-Feld. Es wird bewusst nicht
  gespeichert (Fremdtext-Minimierung); falls die Schlagzeile allein zu dünn ist,
  wäre das eine eigene, dokumentierte Entscheidung.
