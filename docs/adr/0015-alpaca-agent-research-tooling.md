# ADR-0015: Alpaca Agent-Research-Tooling (CLI, MCP-Server, Skills Library) — Abgrenzung und selektive Übernahme

* Status: accepted — angenommen von Ralf am 15.08.2026. Die drei Folgearbeiten
  sind seitdem umgesetzt und live (F103 Bar-Adjustment inkl. Backfill, F104
  gemessener Spread, F105 News/Screener). Mit derselben Freigabe ist das unten
  „geparkte" Backtest-Modul **beauftragt** — als deterministisches Code-Modul im
  Review-Zweig, mit eigenem Feature-Dokument; die Ablehnung von CLI, MCP-Server
  und LLM-geschriebenem Simulationscode im Zyklus bleibt davon unberührt.
* Deciders: Ralf Schmid
* Datum: 2026-08-11
* Betrifft Invariante(n): **#2** (Privilege Separation), **#9** (Untrusted Content),
  **#10** (Fairness) — keine wird aufgeweicht, sie sind die Ablehnungsgründe
* Betrifft ARCHITECTURE.md **§3.5** (Datenquellen), **§5.1** (Rollenmodell), **§8** (Phasen)

## Kontext und Problemstellung

Ralf verweist auf einen Alpaca-Learn-Artikel („How I use AI to research and test
trading ideas with Alpaca") und fragt, wie „die neue Research-API" in den
Agenten-Ablauf integriert werden kann.

**Quellenlage:** `alpaca.markets` ist vom Egress-Proxy dieser Session geblockt, der
Artikel selbst war nicht lesbar. Die Bewertung stützt sich deshalb auf die
Primärquellen des Ökosystems (öffentliche Repos, live abgerufen 2026-08-11):

* `github.com/alpacahq/alpaca-skills` — Skills Library, Apache-2.0, erste
  Trading-API-Skill `alpaca-trading-backtest` (`SKILL.md` vollständig gelesen)
* `github.com/alpacahq/cli` — Alpaca CLI, **Alpha Preview**, Go-Binary, aus den
  OpenAPI-Specs generiert
* `github.com/alpacahq/alpaca-mcp-server` — MCP-Server v2 (FastMCP/OpenAPI,
  Toolset-Filter über `ALPACA_TOOLSETS`)

**Zentrale Feststellung: Es gibt keine neue Research- oder Backtest-API.** Neu sind
drei Agenten-Werkzeuge über den bestehenden Endpoints:

1. **CLI** — `alpaca data bars|quotes|screener|news|meta`, `alpaca corporate-action`,
   dazu der volle Trading-Bereich (`order`, `position`, `locate`).
2. **MCP-Server v2** — dieselben Endpoints als MCP-Tools.
3. **Skills Library** — Markdown-Arbeitsanweisungen für Coding-Assistants. Die
   Backtest-Skill ist **kein Service**: sie beschreibt einen Ablauf, in dem der
   Agent Bars per CLI zieht, im Workspace ein `run.py` schreibt, lokal simuliert und
   Artefakte (`notes.md`, `strategy_spec.json`, `config.json`, `raw/`, `normalized/`,
   Data-Fingerprint, Pflicht-Disclaimer) ablegt.

Die Datenbasis dahinter ist exakt die Market-Data-API, die ATLAS über `alpaca-py`
(0.43.5, bereits Dependency) schon nutzt.

## Entscheidungstreiber

* Der Order-Pfad ist deterministisch und exklusiv (Invariante #2, ADR-0012) — jedes
  zusätzliche Werkzeug mit Order-Fähigkeit vergrößert die Angriffsfläche.
* Kennzahlen gehören in Code, nicht in LLM-Output (CLAUDE.md „Was Claude Code NICHT
  tun darf").
* Kosten je Persona-Zyklus sind hart gedeckelt (1 $/Persona/Tag, 10 $/Tag System).
* Phasenmodell: Backtesting kommt in ARCHITECTURE.md §8 in **keiner** Phase vor —
  Vorziehen nur auf explizite Anforderung.
* Fairness: neue Daten dürfen nur über den Shared Research Pool eintreten.

## Betrachtete Optionen

* **A** — Backtest-Skill in den Agenten-Zyklus einbauen (Persona ruft Backtest auf)
* **B** — Alpaca MCP-Server als Tool-Layer für die Agenten
* **C** — CLI als Ingestion-Werkzeug (statt/neben `alpaca-py`)
* **D** — Nichts übernehmen
* **E** — Selektive Übernahme: kein CLI/MCP im Laufzeitpfad, aber die von der Skill
  offengelegten Datenlücken über das bestehende SDK schließen

## Entscheidung

Gewählt: **Option E**.

**Nicht integriert werden CLI, MCP-Server und die Backtest-Skill als Laufzeit-Bausteine:**

* **A (Skill im Zyklus): abgelehnt.** Der Ablauf setzt voraus, dass ein LLM
  Simulationscode schreibt und ausführt. Das verlagert Finanzkennzahlen (Return,
  Drawdown, Fills) in LLM-generierten Ad-hoc-Code im Trading-Container, ist nicht
  reproduzierbar, läuft an `cost_ledger` vorbei und braucht Shell-Zugriff auf eine
  CLI, die `position close-all` und `order cancel-all` ohne Rückfrage ausführt —
  direkter Bruch von Invariante #2. Zusätzlich: pro Persona und Zyklus ein
  Code-schreibender Agent sprengt die Kosten-Caps und wäre bei ungleicher
  Laufzeit/Abbruchquote ein Fairness-Problem (#10).
  *Unbedenklich* ist die Skill als Werkzeug auf Ralfs Arbeitsrechner (eigener
  Paper-Key, außerhalb des Repos und des Zyklus).
* **B (MCP): abgelehnt, kein Bedarf.** Der Order-Pfad ist über `BrokerAdapter`
  abgedeckt und bewusst LLM-frei; ein MCP-Server öffnet einen zweiten
  Credential- und Order-Pfad, dessen einzige Begrenzung eine Server-Env-Variable
  (`ALPACA_TOOLSETS`) ist — Konfiguration, keine harte Grenze. Für reine Marktdaten
  bringt er gegenüber dem SDK nichts.
* **C (CLI in Ingestion): abgelehnt, unnötig.** Alpha Preview mit ausdrücklich
  instabilen Flags/Outputs, zusätzlicher Go-Toolchain im Container, zweiter
  Credential-Pfad (`~/.config/alpaca/profiles/`) — für Endpoints, die `alpaca-py`
  bereits typisiert abdeckt.

**Übernommen wird der inhaltliche Ertrag** — die Run-Considerations-Checkliste der
Skill zeigt drei konkrete Lücken in ATLAS, alle deterministisch und alle unabhängig
von Backtesting wertvoll:

1. **Bar-Adjustment / Corporate Actions (Bug-Charakter).**
   `src/ingestion/market_data_sync.py:65` setzt kein `adjustment` → es gilt der
   API-Default `raw`. Splits erzeugen damit künstliche Sprünge in den Tages-Closes
   und verfälschen RSI/MACD/Bollinger/SMA-Crossover (F036) — also genau die
   Research-Items, auf denen CHARTIST arbeitet. Fix: `adjustment` explizit setzen
   plus Re-Backfill des 90-Tage-Fensters; `alpaca-py` hat zusätzlich einen
   `CorporateActionsClient` für die Nachvollziehbarkeit.
2. **Gemessener Spread statt Pauschale.** `src/review/slippage.py:84` nimmt
   `spread_bps` aus der Config (Default 5 bps je Asset-Klasse). `vulture_screener.py`
   holt bereits `StockSnapshotRequest`, das den letzten Quote (Bid/Ask) enthält —
   ein real gemessener Spread ist fast gratis und macht den Slippage-Malus
   belastbarer (die in ARCHITECTURE.md §7.8 für P5 vorgesehene Feinjustierung).
3. **Alpaca News + Screener als zusätzliche Pool-Quellen.** `alpaca-py` bietet
   `NewsClient` (symbolgetaggte Headlines) und `ScreenerClient`
   (`ScreenerRequest`/`MarketMoversRequest` → Most Actives, Movers). Das ergänzt die
   Yahoo-RSS-Quelle (F058) um symbolbezogene Treffer und liefert HYPE/CONTRA
   tagesaktuelle Auffälligkeiten. Eintritt ausschließlich als `research_item` im
   Shared Pool (#10); Fremdtext bleibt getaggter Datenblock (#9).

**Der Artefakt-Kontrakt der Skill wird als Vorlage geparkt**, nicht implementiert:
`strategy_spec.json` + `config.json` + Data-Fingerprint + Run-Lineage („was wurde
gegenüber dem Vorlauf geändert") + Pflicht-Disclaimer ist genau die Lineage-Disziplin,
die ATLAS für Decisions schon hat. Falls Backtesting je gewünscht wird, gehört es als
**deterministisches Code-Modul in den Review-Zweig (P5+)**, nicht in den
Persona-Pfad — sonst entstehen Kosten- und Fairness-Asymmetrien.

### Konsequenzen

* Gut, weil kein neues Deployment-Artefakt entsteht: keine Änderung an
  `docker-compose.yml`, keine neuen Secrets, keine Go-Toolchain → die
  `ugreen-Box`-Homelab-Doku bleibt unberührt.
* Gut, weil der gesamte Nutzen über eine bereits vorhandene, typisierte Dependency
  gehoben wird und im Laufzeitpfad deterministisch bleibt.
* Schlecht, weil das „AI-Backtesting" aus dem Artikel damit bewusst nicht ins System
  kommt — Strategie-Hypothesen bleiben unbacktestet, der Wettbewerb bleibt der
  einzige Erkenntnisweg (so ist das Projekt aber auch angelegt).
* Folgearbeit (Reihenfolge nach Nutzen/Risiko, jeweils eigenes Feature-Dokument nach
  §10, **erst nach Ralfs Freigabe**):
  1. `F103` Bar-Adjustment + Backfill (Datenqualität, wirkt direkt auf F036) — Bug,
     sollte vor dem Wettbewerbsstart laufen.
  2. `F104` Gemessener Bid/Ask-Spread im Slippage-Malus (P5-Aufgabe).
  3. `F105` Alpaca-News-/Screener-Ingestion (P3-Nachzügler). Vor Umsetzung
     Kostenwirkung prüfen: mehr `research_item`-Zeilen ⇒ größerer Persona-Prompt je
     Zyklus gegen den 1-$-Cap.
* ~~Backtest-Modul: geparkt.~~ **Beauftragt am 15.08.2026** (Ralf). Umsetzung
  entlang der hier gesetzten Leitplanken: deterministisches Code-Modul im
  Review-Zweig, kein Zugriff aus dem Persona-Pfad, Artefakt-Kontrakt der Skill
  als Vorlage. Auftragsdokument:
  [F111](../features/F111-backtest-modul.md) — dort stehen auch die fünf
  Punkte, die vor der Implementierung zu klären sind.

## Pro/Contra der Optionen

### A — Backtest-Skill im Agenten-Zyklus

* Gut, weil Personas ihre Regeln vor dem Einsatz an Historie prüfen könnten.
* Schlecht, weil LLM-geschriebener Simulationscode im Trading-Container läuft
  (Invariante #2, „keine Kennzahlen vom LLM"), nicht reproduzierbar ist, die
  Kosten-Caps sprengt und die Fairness zwischen Personas nicht garantierbar macht.

### B — MCP-Server als Tool-Layer

* Gut, weil Tool-Anbindung per MCP in ARCHITECTURE.md §3.4 grundsätzlich vorgesehen
  ist und der Server v2 Toolset-Filter kennt.
* Schlecht, weil er einen zweiten Order-fähigen Pfad neben `BrokerAdapter` schafft,
  dessen Begrenzung nur Konfiguration ist; für Marktdaten kein Mehrwert gegenüber
  dem SDK.

### C — CLI in der Ingestion

* Gut, weil aus OpenAPI generiert und damit immer aktuell zur API.
* Schlecht, weil Alpha Preview (Flags/Outputs ändern sich ohne Vorwarnung), JSON-
  statt Typ-Parsing, zweiter Credential-Pfad, zusätzliche Container-Abhängigkeit.

### D — Nichts übernehmen

* Gut, weil null Aufwand und null Risiko.
* Schlecht, weil drei real vorhandene Datenlücken (Adjustment, Spread, News/Screener)
  offen bleiben — die erste davon verfälscht heute schon CHARTISTs Research.

### E — Selektive Übernahme (gewählt)

* Gut, weil der Ertrag ohne neue Angriffsfläche, ohne neues Deployment und mit
  bestehender Dependency gehoben wird.
* Schlecht, weil es Handarbeit in drei kleinen Features ist statt „Skill
  installieren und fertig".
