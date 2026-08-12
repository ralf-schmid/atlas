# F107 — Namensabgleich: Klartext-Firmennamen → handelbare Symbole

Status: umgesetzt (Deploy offen, siehe §5)
Datum: 2026-08-11
Auslöser: Ralf, nach dem Befund aus F106 §3b

## 1. Zieldefinition

Drei Quellen im geteilten Pool nennen Unternehmen als **Klartext im Fließtext** und
liefern deshalb `research_item.instruments = []`:

| Quelle | Lage vor F107 |
|---|---|
| Newsletter (cryptocrunch, materialscrunch, marketscrunch) | nur `$TICKER` wurde erkannt — in den Ausgaben vom 11.08.2026 vier Ticker gegen dutzende Klartextnamen (F106 §3b) |
| Zeitschriften-Artikel (`publication_article`) | `instruments=[]` war fest verdrahtet |
| Marktnews aus dem Yahoo-RSS (`market_news`) | der Feed trägt keine Symbole; Alpacas Meldungen sind seit F105 getaggt, die Yahoo-Zeilen nicht |

Ein Impuls ohne `instruments` liegt zwar im Pool, ist aber über die Symbolsuche
(`search_research_pool`, F045) nicht auffindbar und lässt sich keiner Position
zuordnen — er erreicht die Persona nur, wenn er zufällig im Zyklus-Fenster steht.

**Ziel:** ein deterministischer Abgleich Klartextname → Symbol, gepflegt in einer
gemeinsamen Liste, angewendet auf genau diese drei Quellen.

**Scope:** `config/instrument_names.yaml`, Matcher-Modul, Einbau an den drei Stellen.
**Non-Scope:** Fuzzy-Matching/NLP, automatische Ableitung aus Alpacas Asset-Liste
(Begründung §2), Tagging von EDGAR-Filings (die haben `company_name` als eigenes Feld
und einen anderen Weg), LLM-gestützte Entity-Erkennung (CLAUDE.md: Kennzahlen und
Zuordnungen gehören in Code).

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, geprüft | **Eine** Liste für alle Quellen und alle Personas, geladen einmal je Synthese-Lauf. Ein persona-spezifischer Eintrag wäre ein Informationsvorsprung — die Pflegeregeln in der Datei sagen das ausdrücklich. |
| #9 Untrusted Content | nein, entschärfend | Der Abgleich liest Fremdtext, erzeugt aber nur ein Symbol aus einer **kuratierten Allowlist**. Kein Fremdtext bestimmt, was in `instruments` landen kann. |
| #3 kein Pfad zur Order | nein | `instruments` ist eine Research-Referenz. Orders entstehen ausschließlich aus einer `approved` Decision per DB-ID (ADR-0012). |
| Kosten | nein | Regex über bereits vorhandenen Text, keine LLM-Calls, keine zusätzlichen `research_item`-Zeilen. |

**Design-Entscheidungen:**

1. **Kuratierte Liste statt abgeleitetem Index.** Naheliegend wäre, die Namen aus
   Alpacas ~11.000 Assets zu ziehen. Dagegen spricht die Fehlerrichtung: ein
   Namensindex dieser Breite macht aus Alltagswörtern Instrument-Referenzen
   („Gold", „American", „Nu"), und **ein falscher Tag ist schlimmer als ein
   fehlender** — er schickt eine Persona zu einem Symbol, über das der Text nie
   gesprochen hat. Die Liste startet bewusst klein und wächst nach Bedarf.
2. **Groß-/Kleinschreibung wird exakt genommen.** Firmennamen stehen kapitalisiert;
   deutsche Prosa ist voll von Wörtern, die sich nur dadurch unterscheiden
   („Meta-Ebene", „ein Block"). Das ist der billigste wirksame Falsch-Treffer-Schutz.
3. **Mindestens vier Zeichen je Alias, hart erzwungen.** Kürzeres kollidiert zu oft
   („BP", „HD", „KO" lesen sich als Prosa). Ein zu kurzer Eintrag lässt
   `load_instrument_aliases` mit `ValueError` scheitern statt ihn still zu
   überspringen — sonst sieht ein bewusst gesetzter Alias später wie ein Bug aus.
   Kurzformen dieser Art gehören in die `ticker_map` des Newsletters, die nur die
   `$BP`-Schreibweise trifft.
4. **Längster Alias gewinnt, ein Symbol nur einmal.** „Berkshire Hathaway" schlägt
   „Berkshire"; das Ergebnis ist nach erstem Auftreten im Text sortiert.
5. **Ticker vor Namen.** Bei den Newslettern steht ein explizites `$LLY` vor einem
   beiläufig erwähnten Namen — die Reihenfolge in `instruments` bildet das ab.
6. **Verlags-Tagging schlägt die Liste.** Eine Alpaca-News-Zeile mit eigenen
   `symbols` (F105) behält sie; der Namensabgleich ist der Ersatz für Feeds ohne
   Tagging, keine zweite Meinung.
7. **Zeitschriften: Titel + Excerpt, nicht der ganze Artikel.** Getaggt wird, was die
   Persona tatsächlich zu lesen bekommt (`raw["excerpt"]`, 600 Zeichen) — sonst
   verweist der Tag auf eine Firma, die auf Seite drei einmal vorkam.
8. **Modul in `src/orchestrator/`, nicht in `src/ingestion/`.** Beide Schichten
   nutzen es; die im Repo bereits etablierte Richtung ist ingestion → orchestrator
   (`scheduler.py` importiert `symbol_universe`), und `instrument_names` ist der
   direkte Verwandte von `symbol_universe`.

## 3. Testdefinition (vor Implementierung geschrieben)

`tests/orchestrator/test_instrument_names.py`:

1. `test_matches_a_company_name_in_prose` — Grundfall.
2. `test_reports_each_company_once_even_with_several_aliases` — längster Alias
   gewinnt, Symbol erscheint einmal.
3. `test_orders_symbols_by_first_appearance` — stabile, nachvollziehbare Reihenfolge.
4. `test_requires_word_boundaries` — „Alphabetisierung" ist nicht Alphabet.
5. `test_is_case_sensitive_to_keep_everyday_words_out` — der Falsch-Treffer-Schutz.
6. `test_empty_inputs_yield_nothing`.
7. `test_live_config_is_loadable_and_maps_known_names` — gegen die echte Datei, damit
   ein gelöschter Alias hier auffällt.
8. `test_live_config_holds_no_collision_prone_short_aliases`.
9. `test_short_alias_is_rejected_loudly`.

`tests/ingestion/test_crypto_newsletter.py`:

10. `test_company_names_are_tagged_alongside_tickers` — beide Mechanismen zusammen.
11. `test_explicit_alias_map_overrides_the_shared_one` — Injektion für Tests.

`tests/orchestrator/test_research_synthesis.py`:

12. `test_publication_article_is_tagged_with_company_names`.
13. `test_yahoo_headline_is_tagged_with_company_names`.
14. `test_publisher_symbol_tagging_wins_over_the_name_map`.

## 4. Implementierung

| Datei | Änderung |
|---|---|
| `config/instrument_names.yaml` | neu: 24 Aliase auf 21 Symbole, mit den Pflegeregeln im Kopf |
| `src/orchestrator/instrument_names.py` | neu: `load_instrument_aliases`, `match_instruments` |
| `src/ingestion/crypto_newsletter.py` | `_resolve_instruments` ergänzt den Namensabgleich; `parse_newsletter` nimmt optional eine Alias-Map |
| `src/orchestrator/research_synthesis.py` | Alias-Map einmal je Lauf geladen, an Zeitschriften- und Marktnews-Mapping durchgereicht |

## 5. Test & Rollout

- `uv run pytest`: **970 passed, 26 deselected** (956 nach F106). `ruff check` /
  `ruff format --check` / `mypy src`: clean.
- **Gegen die echten Ausgaben vom 11.08.2026 verifiziert** (Einmal-Lauf im
  Scratchpad, nicht im Repo):
  - materialscrunch: 3 von 13 Impulsen mit Instrument (vorher 2) — `BP`, `TSLA`
    (aus dem SpaceX-Block, der Tesla mit Ticker nennt), `XOM` **neu über den
    Namensabgleich**.
  - marketscrunch: `MARKET MOVER` bekommt jetzt `['BRK.B', 'GOOGL']` statt nichts —
    genau der Impuls, um den es Ralf ging (Berkshire stockt bei Alphabet auf).
- **Bei dir:** nur `docker compose build api scheduler` + `up -d` (kann mit dem
  ohnehin anstehenden Deploy zusammenfallen). Kein Schema-Change, keine Migration,
  keine neue Env-Var.
- **Rollback:** `aliases:` in `config/instrument_names.yaml` leeren — der Matcher
  liefert dann nichts und alles verhält sich wie vor F107. Die Datei muss existieren
  bleiben.

## 6. Pflege und Folgearbeit

- **Die Liste ist bewusst klein** (Watchlist-Large-Caps, die real vorgekommenen
  Namen, BTC/ETH/SOL im Klartext). Wenn dir im Decision Journal ein Impuls ohne Tag
  auffällt, ist ein Eintrag in `config/instrument_names.yaml` die ganze Arbeit —
  Pflegeregeln stehen im Kopf der Datei.
- **Deutsche Nebenwerte bleiben draußen** (Salzgitter, Uniper aus dem
  Earnings-Kalender): Alpaca handelt sie nicht, ein Tag wäre eine Referenz ins Leere.
- Noch nicht angeschlossen: `reddit_post` und `aktienfinder_blog_post`. Beide nennen
  Firmen ebenfalls im Klartext; das wäre je eine Zeile plus Test, wenn du es willst.
