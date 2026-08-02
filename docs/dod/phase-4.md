# Phase 4 — Agenten-Core: Definition of Done

Checkliste aus ARCHITECTURE.md §8.

**Status:** gestartet 2026-07-07, nicht abgeschlossen. Voraussetzung aus Phase 3 (die
zwei noch offenen Live-Nachweise ohne Scheduler-Abhängigkeit) vorab geklärt, siehe
`docs/dod/phase-3.md` Update 2026-07-07.

**Update (2026-07-07):** alle 11 geplanten Features (F015–F025) umgesetzt und live
verifiziert (Ausnahme: F025s Scheduler-Code steht, läuft aber nicht — siehe unten).

**Update (2026-07-07, Scheduler-Aktivierung):** Ralf hat das ausdrückliche Go
gegeben. [F032](../features/F032-scheduler-activation.md) verdrahtet den
Scheduler als eigenen Docker-Compose-Service auf der UGREEN — läuft ab jetzt
dauerhaft automatisiert. Die unten verbleibenden DoD-Punkte (5-Tage-Dauerlauf,
Crash-Recovery, Kosten-Cap-Stichprobe, täglicher Digest, HITL-Timeout-Sweep)
brauchen jetzt nur noch die Zeit, um sich live zu erhärten — kein
Coding-Aufwand mehr offen. Sicherheitsnetze vor der Aktivierung geprüft: HITL
an (`config/hitl.yaml`), HITL-Timeout-Sweep (F030) und Scheduler-Fehler-Alert
(F029) beide am selben Tag gebaut, Kosten-Caps doppelt durchgesetzt (F028
schließt die Budget-Race).
Der komplette Pfad Research → Persona-Analyse → Risk-Gate → HITL → Order →
Reporting ist einmal durchgängig mit echten Daten/Calls/Order bewiesen. Was fehlt,
ist ausschließlich der **mehrtägige, unbeaufsichtigte Betrieb** — der beginnt erst,
wenn Ralf den Scheduler bewusst startet (`scripts/run_scheduler.py`).

- [x] Vollständiger Zyklus läuft automatisch für alle 6 Portfolios; jede Persona
      erzeugt decisions inkl. `reject_idea`; `input_research_ids`-Pflicht wird
      DB-seitig validiert
      **Erledigt (02.08.2026):** drei Sonderläufe auf der Box, je 6/6 Personas mit
      `hold`/`reject_idea`/`buy`, Constraint-Probe live — siehe „Update
      2026-08-02" unten.
      **Vorgeschichte (teilweise):** [F015](../features/F015-persona-portfolio-seed.md) — die 6
      echten `persona`/`portfolio`-Zeilen existieren jetzt (idempotenter Seed, live
      gegen die lokale DB verifiziert: native Personas mit den echten
      Alpaca-Paper-Account-IDs aus ADR-0001, virtuelle Personas mit
      `internal_ledger`). [F016](../features/F016-orchestrator-graph-skeleton.md) —
      echter LangGraph-`StateGraph` mit Postgres-Checkpointer: legt einen `cycle` an,
      fanoutet per `Send` parallel über alle 6 aktiven Portfolios (je ein
      `agent_run`). Live verifiziert (2026-07-07): 1 `cycle`, 6 `agent_run`, 7 echte
      Checkpoint-Zeilen. [F017](../features/F017-shared-research-synthesis.md) —
      ersetzt F016s Platzhalter durch echte Synthese von `research_item`-Zeilen aus
      EDGAR/Screener/Publikationen/aktienfinder/Musterdepot, inkrementell seit dem
      letzten Cycle derselben `market_session`. Live verifiziert: 49 echte
      EDGAR-Filings → 49 `research_item`-Zeilen mit echten Titeln/Zeitstempeln.
      [F018](../features/F018-persona-charters.md) — Charter-Prompts für alle 6
      Personas. [F019](../features/F019-cost-ledger-enforcement.md) —
      Kosten-Bremse (Invariante 7) vor dem ersten echten LLM-Call.
      [F020](../features/F020-portfolio-risk-inputs.md) — echter Broker-Kontostand
      als Risk-Gate-Eingabe. [F021](../features/F021-persona-analysis-agent.md) —
      **erste echte `decision`-Zeilen.** Persona-Analyse-Agent mit echten LLM-Calls,
      Risk-Gate-Anbindung für `buy` (Sizing per LLM-Konfidenz × `max_position_pct` ×
      Equity), `hold`/`reject_idea` ohne Risk-Gate. Live verifiziert
      (voller lokaler Stack inkl. echtem LiteLLM-Proxy): alle 6 Personas mit echtem
      Sonnet-Call, plausible charaktertypische `hold`-Decisions, 0,13 USD
      Gesamtkosten, korrekte `cost_ledger`-Zeilen.
      [F022](../features/F022-hitl-flow.md) — risk-approved `buy` pausiert jetzt
      korrekt per echtem LangGraph-`interrupt()`, statt direkt `APPROVED` zu setzen
      (schließt eine Sicherheitslücke aus F021 — HITL ist laut ARCHITECTURE.md §5.3
      aktuell für Paper Pflicht). [F023](../features/F023-trading-agent.md) —
      Handels-Agent: `APPROVED`-Decisions (direkt oder nach HITL-Resume) werden über
      `BrokerAdapter.place_order()` ausgeführt, `order_record` persistiert,
      `decision.status → EXECUTED`. Dabei eine echte Sicherheitslücke gefunden und
      behoben: `graph.py` konstruierte Broker-Adapter fest über die echte Registry —
      ein Test, der einen `buy`-Interrupt auf "approved" resumt, hätte sonst eine
      echte Alpaca-Paper-Order ausgelöst. Jetzt injizierbar
      (`adapter_factory`-Parameter). Live verifiziert (mit Ralfs Zustimmung): echte
      1×-AAPL-Order + GTC-Stop über den echten `AlpacaPaperAdapter` platziert,
      `buying_power` sank real um den reservierten Betrag.
      [F024](../features/F024-reporting-agent.md) — Reporting-Agent:
      `generate_portfolio_snapshot` schreibt `portfolio_snapshot` +
      `position_snapshot` aus dem echten Broker-Kontostand, für jede Persona am Ende
      jedes Analyse-Laufs (auch bei `hold`). Live verifiziert gegen VULTUREs echten
      Alpaca-Paper-Account. **Offen:** `sell`/`close` (siehe F021 §1); `pnl_realized`
      bleibt `0` und `benchmark_value` `NULL`, bis es einen Order-Abschluss- bzw.
      SPY-Benchmark-Pfad gibt (P5).
- [x] Risk-Gate: beide Regelebenen implementiert, 100 % Branch-Coverage der
      Regellogik; **Unit-Test-Nachweis je Regelklasse plus mindestens ein echter
      Live-Reject je im Live-Pfad erreichbarer Klasse**
      *(Formulierung angepasst am 02.08.2026, Ralfs Entscheidung — Original:
      „je Regelklasse mindestens ein echter Reject im Testlauf dokumentiert".)*
      **Begründung:** über die gesamte Live-DB hat bisher ausschließlich
      `stop_loss_policy` ausgelöst (11 Rejects, davon 5 im Wettbewerb — Analyse
      [F101](../features/F101-trade-activity-root-cause.md) §2 U3).
      `max_position_pct`, `max_open_positions`, `max_trades_per_day`,
      `min_cash_pct`, `no_margin` und `circuit_breaker` sind aus dem Live-Pfad
      strukturell kaum erreichbar: die Sizing-Schicht rechnet die Position
      bereits innerhalb dieser Grenzen aus, und der Circuit Breaker verlangt
      >15 % Drawdown. Ein künstlich provozierter Verstoß wäre kein echter
      Nachweis, sondern ein manipulierter Testfall — deshalb zählt hier der
      Unit-Test-Nachweis mit 100 % Branch-Coverage
      ([F004](../features/F004-risk-gate.md), `tests/risk/test_gate.py`, live
      gemessen 02.08.2026: `src/risk/gate.py` 74 Stmts / 28 Branches, 100 %).
      **Erledigt:** Regellogik + Coverage aus Phase 2, Live-Reject für die
      erreichbare Klasse `stop_loss_policy` dokumentiert.
- [ ] HITL: Approve, Reject und Timeout alle drei end-to-end nachgewiesen;
      `/hitl off` wirkt ohne Neustart
      **Teilweise:** [F022](../features/F022-hitl-flow.md) — Approve/Reject
      end-to-end über echte `interrupt()`/`Command(resume=...)`-Mechanik verifiziert
      (inkl. mehrerer gleichzeitiger Interrupts, gezieltes Resume per Interrupt-ID).
      `/hitl off` wirkt sofort (`config/hitl.yaml`, kein Deploy nötig). **Offen:**
      kein automatischer 30-Minuten-Timeout-Sweep — die Prüf-Logik existiert
      (F005), aber es gibt noch keinen Scheduler, der sie proaktiv auf nie
      beantwortete Anfragen anwendet (kommt mit dem letzten P4-Feature,
      Zyklen-Scheduling). Fail-closed in der Zwischenzeit: eine unbeantwortete
      Anfrage bleibt `HITL_PENDING`, nie `APPROVED`.
- [x] 5 Handelstage in Folge: alle geplanten Zyklen (4/Tag Aktien +
      CRYPTOR-Plan) gelaufen, 0 unbehandelte Exceptions; Crash-Recovery getestet
      (Container-Kill mitten im Zyklus → Resume via Postgres-Checkpointer)
      **Erledigt:** 8 Handelstage Dauerlauf (15.–24.07.) ohne
      Restart/unbehandelte Exception (Update 25.07.2026 unten) **und**
      Crash-Recovery nachgewiesen (Update 26.07.2026 unten) — beide Teile stehen.
      **Teilweise:** [F025](../features/F025-cycle-scheduling.md) —
      `config/cycles.yaml` + `build_scheduler` (APScheduler, alle 4 Aktien-Zyklen +
      CRYPTOR Werktags-/Wochenend-Zeiten) fertig und getestet (Job-Registrierung,
      Zeitzonen, abschaltbare Zyklen). **Bewusst nicht gestartet** — ein laufender
      Scheduler löst automatisiert, unbeaufsichtigt echte Zyklen aus (Kosten, ggf.
      echte Orders); Aktivierung erfordert Ralfs ausdrückliches Go (siehe F025 §6).
      Ohne laufenden Scheduler kein 5-Tage-Dauerlauf, kein Crash-Recovery-Test.
- [x] Tageskosten ≤ Cap; `cost_ledger` stimmt stichprobenhaft mit
      LiteLLM-Abrechnung überein
      **Erledigt (25.07.2026):** siehe Update unten — LiteLLM läuft bewusst ohne
      eigene Datenbank und hat daher keine gespeicherte Abrechnung; der Nachweis
      wurde deshalb (mit Ralfs Zustimmung) als unabhängige Nachrechnung
      Tokens × offizielle Anthropic-Preisliste geführt. Übereinstimmung
      < 0,1 % im Tages-Aggregat, 0,0000 USD Differenz je Einzel-Call; alle
      Tages- und Persona-Caps eingehalten.
- [ ] Telegram-Tagesdigest kommt täglich; Zahlen gegen DB-Query verifiziert

## Geplante Feature-Reihenfolge (Stand 2026-07-07, kann sich ändern)

1. ~~F015 — Persona/Portfolio-Seed~~ ✅ erledigt.
2. ~~F016 — LangGraph-Graph-Grundgerüst~~ ✅ erledigt: echter `StateGraph` +
   Postgres-Checkpointer, `cycle`-Lebenszyklus, Send-Fanout über die 6 echten
   Portfolios, Platzhalter-`agent_run` je Persona — bewusst noch ohne
   `decision`-Zeilen (siehe F016 §1 Non-Scope), ohne Order-Pfad, ohne HITL.
3. ~~F017 — Shared-Research-Synthese~~ ✅ erledigt: `research_item`-Zeilen aus den
   bestehenden Ingestion-Tabellen (F009–F012, F014) statt dem F016-Platzhalter;
   `market_bar` bewusst ausgeschlossen (siehe F017 §1 Non-Scope).
4. ~~F018 — Persona-Charter-Prompts~~ ✅ erledigt: `src/personas/charters.py`,
   Philosophie/Universum/Signale wörtlich aus ARCHITECTURE.md §4.1–4.6, Guardrail-
   Zahlen live aus `config/personas/<name>.yaml`. Noch kein LLM-Call.
5. ~~F019 — Cost-Ledger-Enforcement~~ ✅ erledigt: `guarded_complete` prüft
   System-/Persona-Tagesbudget aus echten `cost_ledger`-Summen **vor** jedem
   LiteLLM-Call, schreibt danach den Ledger-Eintrag; `BLOCKED` verhindert den Call
   komplett. Musste vor dem ersten echten LLM-Call stehen (Invariante #7) — daher
   vorgezogen vor den Persona-Analyse-Agenten selbst.
6. ~~F020 — Portfolio-Risk-Gate-Eingaben~~ ✅ erledigt: `read_portfolio_risk_state`
   liest Equity/Cash/offene Positionen live über den echten `BrokerAdapter`
   (F001/F002), Peak-Equity aus der `portfolio_snapshot`-Historie (Kaltstart-Fallback:
   aktuelle Equity), Trades heute aus `order_record`/`decision`.
7. ~~F021 — Persona-Analyse-Agent~~ ✅ erledigt: echte LLM-Calls über
   `guarded_complete`, nutzt F018s Charter + F017s Research-Pool + F020s
   Risk-Inputs; `hold`/`reject_idea` direkt, `buy` durchs Risk-Gate (Sizing-Formel
   mit Ralf abgestimmt: `conviction × max_position_pct × equity`). `sell`/`close`
   bewusst zurückgestellt bis der Handels-Agent echte Positionen erzeugt.
8. ~~F022 — HITL-Flow~~ ✅ erledigt: risk-approved `buy` pausiert per echtem
   LangGraph-`interrupt()` (statt F021s direktem `APPROVED`), Telegram-Callback
   resumed gezielt per Interrupt-ID (`Command(resume={id: outcome})`); mehrere
   gleichzeitige Interrupts verifiziert unabhängig voneinander. Offen: kein
   automatischer Timeout-Sweep ohne Scheduler (siehe oben, DoD-Punkt 2).
9. ~~F023 — Handels-Agent~~ ✅ erledigt: `execute_decision` nimmt ausschließlich
   bereits `APPROVED`-Decisions (nie Freitext) entgegen, ruft `place_order()`
   (OTO-Bracket mit Pflicht-Stop, F001), persistiert `order_record`. Aufgerufen aus
   `persona_analysis.py` direkt nach jeder Stelle, an der eine Decision `APPROVED`
   wird — kein separater Graph-Knoten (State-Channel-Kollisionsgefahr bei
   parallelem `Send`, siehe F023 §2).
10. ~~F024 — Reporting-Agent~~ ✅ erledigt: `generate_portfolio_snapshot` liest
    Equity/Cash/Positionen live über denselben `BrokerAdapter`, den
    `analyze_persona_cycle` ohnehin schon hat — kein zusätzlicher Credential-Zugriff.
    `pnl_realized=0`/`benchmark_value=None` bewusst dokumentierte Non-Scope-Werte
    (siehe F024 §1).
11. ~~F025 — Zyklen-Scheduling~~ ✅ Code fertig, **nicht als laufender Prozess
    gestartet** (bewusst, siehe F025 §1/§6 — Aktivierung ist Ralfs Entscheidung).
    `scripts/run_scheduler.py` existiert als Einstiegspunkt für den Tag, an dem
    das gewünscht ist. Schließt formal noch nicht die drei offenen
    Phase-3-Punkte (täglicher aktienfinder-/Screener-Lauf, 5-Tage-Dauerlauf,
    PDF-Fallback-Poller) — die brauchen den tatsächlich laufenden Scheduler, nicht
    nur den Code dafür.

Damit ist Phase 4 inhaltlich vollständig — die Aktivierung des Schedulers ist der
einzige verbleibende, bewusst zurückgestellte Schritt (siehe F025 §6). Alle
übrigen offenen DoD-Punkte (5-Tage-Dauerlauf, Crash-Recovery, Kosten-Cap-
Stichprobe, täglicher Digest, HITL-Timeout-Sweep) hängen an dieser einen
Aktivierung.

**Update (10.07.2026):** Scheduler läuft seit der Aktivierung durchgängig,
inklusive mehrerer außerplanmäßiger Verifikations-Zyklen. Der
Mehrtage-Dauerlauf-Nachweis (DoD-Punkt 4) startet seinen Zähler neu: am
09.07.2026 sind mehrere automatische Zyklen wegen eines erschöpften
Anthropic-Guthabens komplett fehlgeschlagen (behoben — Guthaben aufgeladen,
siehe F046). Dabei zwei echte, unabhängig vom Guthaben-Vorfall bestehende
Pipeline-Bugs gefunden und behoben, die den DoD-Punkt "jede Persona erzeugt
plausible decisions" verdeckt hätten: Research aus komplett fehlgeschlagenen
Zyklen wurde permanent übersprungen (nie wieder sichtbar für spätere
Zyklen), und die Prompt-Auswahl ließ hochfrequente EDGAR-Filings alle
Slots belegen und langsamere, eigentlich relevantere Quellen
(VULTURE-Screener-Kandidaten, aktienfinder-Snapshots) komplett verdrängen
— siehe [F047](../features/F047-research-pool-fairness-and-window-resilience.md).
Nach dem Fix (Verifikations-Zyklus 785adc7a, 10.07.2026): alle 6
`agent_run`-Zeilen `SUCCEEDED`, plausible, charaktertypische
`hold`/`reject_idea`-Decisions mit korrekt zitierten `input_research_ids`.
Offen für den formalen DoD-Abschluss: 5 ununterbrochene Handelstage ohne
unbehandelte Exception (Zähler beginnt jetzt neu), Kosten-Cap-Stichprobe
gegen die echte LiteLLM-Abrechnung, täglicher Telegram-Digest verifiziert.

**Update (10.07.2026, Abend — HITL-Listener-Lücke gefunden, echte Order zum
ersten Mal komplett durchgängig verifiziert, F049-F061):** Wichtige
Korrektur an obigem DoD-Punkt "HITL: Approve, Reject und Timeout alle drei
end-to-end nachgewiesen" — das galt bislang nur für einen einmaligen
manuellen Test (F005 §5, 05.07.2026), **nicht für den tatsächlich
deployten Dauerbetrieb**: `docker-compose.yml` startete nirgends
`Application.run_polling()` — der Scheduler versendete Freigabe-Anfragen
per Telegram, aber niemand hörte auf die Button-Klicks. Vier echte,
risk-approved `buy`-Decisions liefen deshalb am 10.07. in den
30-Minuten-Timeout und wurden automatisch abgelehnt (fail-closed wie
vorgesehen, kein Sicherheitsvorfall — aber der Beweis "HITL funktioniert im
Dauerbetrieb" stand bis dahin faktisch noch aus). [F049](../features/F049-telegram-bot-polling-service.md)
deployt den Listener endlich als eigenen `telegram-bot`-Service.

Der darauffolgende Sonderlauf deckte auf, dass selbst mit funktionierendem
Listener **noch keine einzige Order jemals durchgängig bis `EXECUTED`**
gekommen wäre — drei weitere, bis dahin nie erreichte Bugs im
Order-Ausführungspfad:
[F050](../features/F050-stop-loss-tick-rounding.md) (unrundierte
Stop-Preise, von Alpaca abgelehnt — plus ein zweiter Fund dabei: eine
fehlgeschlagene Order wurde nie erneut versucht, neuer
`retry_stuck_decisions`-Sweep),
[F051](../features/F051-fractional-order-day-tif.md) (fraktionale
Stückzahl braucht `DAY` statt `GTC`),
[F052](../features/F052-whole-share-rounding-for-native-orders.md)
(Alpaca lässt bei fraktionaler Stückzahl gar keinen Bracket-Order mit
Pflicht-Stop zu — auf Ralfs Entscheidung hin Rundung auf ganze Aktien).
**Nach allen vier Fixes: erstmals eine echte Order komplett durchgängig
verifiziert** — zwei echte Telegram-Freigaben (CHARTIST/AAPL,
VULTURE/ALDX) von Ralf live bestätigt, beide Orders bei Alpaca `FILLED`,
beide GTC-Stops aktiv. Damit ist der DoD-Punkt "HITL Approve/Reject
end-to-end" jetzt tatsächlich für den deployten Dauerbetrieb bewiesen, nicht
mehr nur für einen isolierten Test.

Anschließender Vollständigkeits-Audit (Ralfs Auftrag: "finde jeden Fehler,
der die Ausführung verhindert") fand + behob sechs weitere reale Lücken:
`/pause`/`/resume` waren wirkungslose TODO-Stubs
([F053](../features/F053-telegram-pause-resume-wiring.md)); der
Ledger-Zustand der drei virtuellen Personas (HYPE/CONTRA/CRYPTOR) war
nirgends als Docker-Volume gemountet — jeder Container-Rebuild setzte sie
auf 5.000 USD/0 Positionen zurück, bereits eingetretener, nicht
rückgängig zu machender Datenverlust
([F054](../features/F054-ledger-volume-mount.md)); der
Persona-Kosten-Cap wurde nach dem LLM-Call nicht erneut geprüft
([F055](../features/F055-persona-budget-post-call-check.md)); der
Telegram-Bot-Token erschien im Klartext im Container-Log
([F056](../features/F056-httpx-token-log-leak.md)); die erzwungene
Tool-Abschlussrunde produzierte leere LLM-Antworten (11 von 17
`llm_output_parse_error`-Fällen bei HYPE,
[F057](../features/F057-forced-final-round-tool-choice.md)); und die
Aktien-Zyklen hatten keine Wochentags-Beschränkung und wären auch am
Wochenende gefeuert ([F061](../features/F061-stock-cycle-weekday-restriction.md)).
Dazu zwei von Ralf gemeldete Anzeige-/UX-Lücken behoben: Depot-Käufe waren
weder im Web-Dashboard noch in Grafana sichtbar
([F059](../features/F059-dashboard-grafana-position-visibility.md)), und
Telegram-HITL-Nachrichten nannten nie, welche Persona handelt
([F060](../features/F060-telegram-persona-name.md)).

**Konsequenz für den Mehrtage-Dauerlauf-Nachweis:** der Zähler beginnt
erneut bei Null — der Abend brachte mehrere manuelle Container-Rebuilds
(jeder Rebuild ist eine Unterbrechung des unbeaufsichtigten Betriebs, den
dieser DoD-Punkt eigentlich nachweisen soll). **Weiterhin offen:**
Kosten-Cap-Stichprobe gegen die echte LiteLLM-Abrechnung; `/digest` ist
weiterhin nur ein TODO-Stub (siehe F053 §1 Non-Scope) — der tägliche
Telegram-Digest ist damit noch nicht nachweisbar.

**Update (12.07.2026, von Ralf gemeldet):** Personas kamen über mehrere Zyklen
hinweg wiederholt auf dasselbe, bereits gehaltene Instrument — legitim (neue
Impulse/Wahrscheinlichkeiten), aber die Positionsgrößen-Berechnung
(`compute_position_value_usd` in `persona_analysis._resolve_buy_decision`)
berechnete jede `buy`-Order komplett neu aus `conviction × max_position_pct ×
equity`, ohne einen bereits gehaltenen Bestand im selben Instrument
abzuziehen — und das Risk-Gate prüfte `max_position_pct` nur gegen die neue
Order, nicht gegen den Gesamtbestand danach. Wiederholte Käufe desselben
Symbols konnten dadurch die persona-eigene Positionsgrößen-Obergrenze
kumulativ überschreiten (Fehlallokation in der Höhe). Die eigentliche
Bestandsbuchung beim Broker/Ledger war bereits korrekt (Bestand + Neukauf
bzw. Bestand − Teilverkauf); der Fehler saß ausschließlich in der
Sizing-/Risk-Gate-Schicht davor. Behoben in
[F071](../features/F071-position-sizing-accounts-for-existing-holdings.md):
Sizing toppt jetzt nur noch die Differenz zum Ziel-Gesamtwert auf (bereits
am/über Ziel → `reject_idea` statt Nullmengen-Order), und das Risk-Gate prüft
`existing_position_value_usd + position_value_usd` gegen die Obergrenze als
unabhängiges Sicherheitsnetz.

**Update (18.07.2026):** DoD-Punkt "Telegram-Tagesdigest" ist erledigt —
[F070](../features/F070-daily-telegram-digest.md) (13.07.2026) implementiert
`/digest` inkl. täglichem Cron-Job (16:30 America/New_York) und ist live gegen
die echte Produktions-DB verifiziert. Seitdem zusätzlich gelandet, ohne
direkten DoD-Bezug, aber mit Auswirkung auf den Dauerlauf-Nachweis:
[F072](../features/F072-hitl-off-paper-trade-notify.md) (13.07.2026, Ralfs
Entscheidung: HITL für `paper` aus, Telegram-Trade-Info statt Freigabe-Button —
`live` bleibt HITL-pflichtig, Invariante #5 unberührt), F073 (Parse-Error-Fix),
F074 (Holding-Charts), [F075](../features/F075-order-fill-reconciliation.md)
(Order-Fill-Reconciliation, behebt Chart-/Holdings-/Digest-Lücken, deployt
14./15.07.2026), F076 (JSON-Parse-Fallback, 15.07.2026).

**Weiterhin offen (unverändert seit 12.07.2026, jetzt mit neuem Datum):**
- **5 Handelstage in Folge ohne unbehandelte Exception:** Zähler beginnt mit
  jedem Deploy/Container-Rebuild neu; die F072–F076-Deploys am 13.–15.07 sind
  selbst Unterbrechungen. Damit läuft der Nachweis frühestens seit dem
  F076-Deploy (15.07.2026) — ~~noch keine 5 Tage seit dem letzten Rebuild~~
  → erledigt am 25.07.2026 (8 Handelstage), siehe Update unten.
- **Kosten-Cap-Stichprobe gegen echte LiteLLM-Abrechnung:** ~~weiterhin nicht
  durchgeführt~~ → erledigt am 25.07.2026, siehe Update unten.
- **HITL Approve/Reject/Timeout end-to-end im Dauerbetrieb:** für Paper seit
  F072 (13.07.2026) nicht mehr zutreffend — HITL ist für `paper` jetzt aus,
  der Nachweis von F049–F052 bleibt als historischer Beleg für den
  Interrupt-/Resume-Mechanismus gültig, ist aber kein laufender
  Dauerbetriebs-Nachweis mehr. Für `live` (Invariante #5, weiterhin
  HITL-pflichtig) steht ein Dauerbetriebs-Nachweis naturgemäß noch aus, da
  kein Live-Betrieb existiert.

**Update (25.07.2026): Kosten-Cap-Stichprobe erledigt.** Vorgehen und Befund:

- **Warum kein direkter LiteLLM-Abgleich möglich ist:** der LiteLLM-Proxy läuft
  bewusst ohne eigene Datenbank (`config/litellm_proxy_config.yaml` — nur
  `master_key`, keine `database_url`); die Spend-Endpoints
  (`/global/spend/report` etc.) antworten mit 400 "Database not connected".
  Es existiert also keine gespeicherte LiteLLM-Abrechnung, gegen die man
  vergleichen könnte. Die Kosten fließen ausschließlich pro Request über den
  Response-Header `x-litellm-response-cost` in den `cost_ledger` (F006 §2 —
  bewusst keine eigene Preistabelle im Repo).
- **Gewählter Ersatz-Maßstab (von Ralf bestätigt):** unabhängige Nachrechnung
  der Ledger-Einträge gegen die offizielle Anthropic-Preisliste
  (Stand 2026-06: claude-sonnet-5 Intro-Preis 2 $/MTok Input, 10 $/MTok Output
  bis 31.08.2026; regulär 3 $/15 $).
- **Befund Aggregat (Stichprobe 22.–24.07.2026, ausschließlich
  claude-sonnet-5):**

  | Tag | Calls | tokens_in | tokens_out | Ledger USD | Nachrechnung USD |
  |---|---|---|---|---|---|
  | 22.07. | 93 | 1.021.201 | 51.608 | 2,5588 | 2,5585 |
  | 23.07. | 104 | 1.174.317 | 58.651 | 2,9344 | 2,9351 |
  | 24.07. | 105 | 1.234.232 | 56.032 | 3,0289 | 3,0288 |

  Abweichung < 0,1 % (Rundung auf 4 Nachkommastellen je Einzelbuchung).
- **Befund Einzel-Calls:** 15 jüngste Sonnet-Zeilen einzeln nachgerechnet
  (`tokens_in × 2 $ + tokens_out × 10 $ pro MTok`) — Differenz durchgängig
  0,0000 USD. LiteLLM bepreist also exakt mit dem Sonnet-5-Intro-Tarif.
- **Cap-Einhaltung im Stichproben-Zeitraum:** System-Tagessummen 2,56 / 2,93 /
  3,03 USD (Cap 5 USD/Tag); Persona-Maximum CRYPTOR 0,67 USD am 24.07.
  (Cap 1 USD/Tag je Persona). Alle Caps eingehalten.
- **Bekannte, bewusst akzeptierte Unschärfe (Prompt Caching):** der Ledger
  speichert nur `tokens_in`/`tokens_out` ohne Cache-Aufschlüsselung.
  Cache-Reads kosten bei Anthropic real nur ~0,1× des Input-Preises,
  Cache-Writes 1,25×/2× — LiteLLM rechnet hier offenbar alle Input-Tokens zum
  vollen Satz. Der Ledger ist damit eine **Obergrenze** der realen Kosten,
  d. h. konservativ im Sinne der Cap-Durchsetzung (Invariante #7): Caps
  greifen eher zu früh als zu spät. Nach dem Auslaufen des Intro-Preises
  (31.08.2026) steigen die realen Sätze auf 3 $/15 $ — LiteLLM liefert den
  Preis pro Request selbst, es ist keine Repo-Änderung nötig, aber die
  Tageskosten werden dann um ~50 % höher ausfallen (heutige ~3 USD/Tag →
  ~4,5 USD/Tag, nahe am 5-USD-Cap — beobachten).

**Update (25.07.2026): 5-Tage-Dauerlauf nachgewiesen (Crash-Recovery-Test
bleibt offen).** Befund und Ralfs Bewertungsentscheidung:

- **Ununterbrochener Betrieb:** `atlas-scheduler-1` und `atlas-telegram-bot-1`
  laufen seit dem F076-Deploy (15.07.2026 04:34 UTC) ohne Restart
  (Docker `RestartCount=0`, kein Rebuild). Das deckt die Handelstage
  15.–24.07. ab — **8 Handelstage in Folge**, mehr als die geforderten 5.
- **Alle geplanten Zyklen gelaufen:** DB-Query über `cycle`: 8 Zyklen/Tag an
  Werktagen (4 Aktien + 4 CRYPTOR), 2/Tag am Wochenende (18./19.07., nur
  CRYPTOR — Wochentags-Beschränkung F061 wirkt), lückenlos.
- **Fehlerbild im Zeitraum:** 8 `cycle failed`-Logeinträge, alle **extern
  verursacht und behandelt** (gefangen, mit Traceback geloggt, Alert-Pfad
  F029): 6× DNS-Auflösung `paper-api.alpaca.markets` fehlgeschlagen, 1×
  Alpaca-500, 1× LiteLLM-500. Nur 3 `agent_run`-Zeilen `FAILED`
  (21.07.: 1, 24.07.: 2); die jeweils übrigen Personas desselben Zyklus und
  alle Folgezyklen liefen normal. **Ralfs Entscheidung (25.07.2026):**
  extern verursachte, sauber behandelte Ausfälle zählen nicht als
  „unbehandelte Exception" — der Nachweis gilt.
  *Beobachtung für den Betrieb:* 6 DNS-Fehler in 9 Tagen ist auffällig
  (Homelab-DNS/fritz.box?) — kein DoD-Blocker, aber beobachten; ggf. später
  Retry für transiente Broker-Fehler in `persona_analysis` (P5-Kandidat).
- **Bereinigung feststeckender Decisions:** 6 GUARDIAN/MSFT-`APPROVED`-
  Decisions (13.–21.07., fraktionale Stückzahlen 0,04–0,22) konnten wegen der
  Ganzaktien-Regel (F052: Rundung auf 0 → `ValueError`) nie ausgeführt werden;
  der `retry_stuck_decisions`-Sweep versuchte sie alle 15 Minuten erneut
  (~530 ERROR-Logzeilen/Tag seit 15.07.). Mit Ralfs Zustimmung am 25.07.2026
  manuell auf `RISK_REJECTED` gesetzt (das `decision_status`-Enum hat kein
  `FAILED`; `RISK_REJECTED` + ausführliche `rejection_reason` ist der
  passende Endzustand). **Offenes Folge-Ticket:** das Sizing erzeugte noch am
  21.07. eine fraktionale Menge < 1 Aktie — die F052-Rundung greift erst im
  Broker-Adapter statt schon in der Sizing-/Risk-Schicht; außerdem sollte der
  Sweep permanente Fehler (`ValueError`) von transienten unterscheiden und
  Erstere terminal markieren, statt endlos zu retryen (P5-Kandidat).
- **Crash-Recovery-Test:** am 26.07.2026 nachgeholt und bestanden — siehe
  eigenes Update unten.

**Einordnung ggü. ARCHITECTURE.md §8:** Phase 4 ist damit **abgeschlossen** —
alle DoD-Punkte inkl. Crash-Recovery stehen; 5-Tage-Dauerlauf und
Kosten-Cap-Stichprobe seit 25.07.2026, Crash-Recovery seit 26.07.2026
nachgewiesen (siehe Updates oben/unten). Phase 5 (§8, "Review, Journal & Wettbewerbsstart" —
Review-Agent, Slippage-Malus, Leaderboard, offizieller Start des
8-Wochen-Wettbewerbs) hat inhaltlich noch nicht begonnen; F072 trägt zwar
`Phase: 5` im Feature-Dokument (Ralfs spontane Betriebsentscheidung, keine
formale Phasen-Eröffnung), ist aber ein Ops-Fix am Paper-Betrieb, kein
P5-Feature im Sinne von ARCHITECTURE.md §8. Der 8-Wochen-Wettbewerbs-Zähler
(ARCHITECTURE.md §4.7) hat noch nicht offiziell begonnen — das ist laut §8
selbst ein P5-DoD-Punkt ("Wettbewerb offiziell gestartet: Stichtag
dokumentiert, alle 6 Portfolios auf 5.000 USD").

**Update (26.07.2026): Crash-Recovery-Test bestanden — letzter offener
P4-DoD-Punkt geschlossen.** Durchgeführt auf dem realen Stack (`atlas-ugreen`),
nicht lokal. Ablauf und Nachweise:

- **Außerplanmäßiger Sonderlauf statt Container-Cron:** ein Ad-hoc-Zyklus mit
  `seq=99` (frischer `thread_id` `2026-07-26-99-us_equity`, kollidiert nicht mit
  den regulären Wochenend-CRYPTOR-Zyklen 06/18 UTC) via `scripts/run_cycle.py`
  im `atlas-scheduler-1`-Container. Ein erster regulärer Sonderlauf (`seq=1`) lief
  in ~6 s komplett durch — zu schnell für einen zuverlässig getimten
  Mid-Cycle-Kill.
- **Deterministisches Einfrieren mitten im Zyklus:** `docker pause
  atlas-litellm-1` friert den LiteLLM-Proxy ein; der Zyklus läuft dann bis zum
  ersten LLM-abhängigen Superstep und blockiert dort. `start_cycle` (DB-Insert des
  cycle-Eintrags) und `shared_research` (Aggregation, hier ohne blockierenden
  LLM-Call) liefen durch, der `persona_analysis`-Fan-out (6× Sonnet) blockierte an
  der pausierten litellm.
- **Container-Kill:** `docker kill atlas-scheduler-1` → Exit **137** (SIGKILL).
  Beobachtung: trotz `restart: unless-stopped` startete Docker den Container
  **nicht** automatisch neu (bei `docker kill` wertet der Daemon das als manuellen
  Eingriff) — bestätigt zugleich, dass **nichts von selbst resumed** (ein
  neu gestarteter Scheduler registriert ohnehin nur Cron mit neuem `thread_id`,
  siehe `scripts/resume_cycle.py`). Container danach manuell via `docker start`
  zurückgeholt, litellm via `docker unpause` freigegeben; regulärer Betrieb
  (nächster CRYPTOR-Zyklus 18:00 UTC) unberührt.
- **Checkpoint hielt den Mid-Cycle-Zustand (read-only geprüft, ohne Resume):**
  `next=('persona_analysis'×6)`, `state.cycle_id=86842410-…`,
  `research_item_ids=294` — d. h. `start_cycle` + `shared_research` abgeschlossen,
  6 `persona_analysis` pending.
- **Resume via Postgres-Checkpointer:** `scripts/resume_cycle.py
  2026-07-26-99-us_equity` fand den Checkpoint und führte **nur** die 6 pending
  `persona_analysis` fort (`input=None`, keine Wiederholung abgeschlossener Nodes).
  Nachweise nach dem Resume:
  - `cycle` mit `seq=99`: weiterhin **genau 1 Zeile** → `start_cycle` **nicht**
    re-run, kein doppelter cycle-Eintrag.
  - `agent_run` für den cycle: **6 total, 6 distinct portfolios** → alle 6
    Personas gelaufen.
  - `decision` für den cycle: 6 (1 BUY, 4 HOLD, 1 REJECT_IDEA).
  - Finaler Checkpoint-State: `next=()`, keine pending tasks → Lauf vollständig
    abgeschlossen.
- **Einschränkung/Notiz:** Das auf der Box laufende Docker-Image ist älter als
  Commit `c578158` (25.07.), enthält `scripts/resume_cycle.py` noch nicht — das
  Script wurde für den Test per `docker cp` in den Container gelegt. Beim nächsten
  Image-Rebuild/Redeploy (fällig ohnehin für den F080/Cost-Cap-Stand) ist es
  regulär enthalten. Der Ad-hoc-`seq=99`-Zyklus samt seinen Decisions bleibt als
  Testartefakt in der Vorsaison-DB; er verschwindet beim Wettbewerbs-Reset am
  03.08.2026.

## Update 2026-08-02 — Vollzyklus-DoD und Sonderlauf mit Unterbrechung

Drei manuelle Läufe auf der Box (`scheduler`-Container, Image-Stand `deba691`
inkl. F101-Fixes), alle gegen die echte Wettbewerbs-DB.

**Lauf 1 (`seq=1`, cycle `095c2933`, 14:17:31 UTC) — Vollzyklus:**
1.534 `research_item`, 8 `agent_run` (6 Personas + `market_research` +
`news_research`), **6 Decisions — eine je Persona**: CHARTIST/CRYPTOR/GUARDIAN
`hold`, HYPE/VULTURE/CONTRA `reject_idea`.

**Lauf 2 (`seq=2`, cycle `d9f07c55`, 14:20:52 UTC):** identisches Bild, 6/6
Personas in unter 50 Sekunden — der Fan-Out über `Send` läuft parallel.

**Lauf 3 (`seq=3`, cycle `8105cdf2`, 14:22:16 UTC) — Crash und Resume:**
- Prozess nach 45 Sekunden mit `kill -9` hart abgeschossen (SIGKILL auf den
  Python-Prozess im Container), während die Persona-Analysen liefen.
- Zustand danach: **2 von 6 Personas** fertig (CHARTIST `buy` EXECUTED, CRYPTOR
  `hold`), 3 `agent_run`, kein laufender Prozess mehr.
- `scripts/resume_cycle.py 2026-08-02-3-us_equity` fand den Checkpoint
  (created 14:22:27) mit **6 pending `persona_analysis`** und führte den Lauf zu
  Ende.
- Zustand nach dem Resume: **6 Decisions, genau eine je Persona** — CHARTIST und
  CRYPTOR wurden **nicht** doppelt entschieden (die Idempotenz-Prüfung in
  `analyze_persona_cycle` gibt die bestehende Decision zurück), weiterhin **eine
  einzige `cycle`-Zeile** für `seq=3`.

**DB-seitige `input_research_ids`-Pflicht:** live gegen die Wettbewerbs-DB
geprüft — ein `INSERT` mit `input_research_ids = '{}'` scheitert an
`ck_decision_input_research_ids_not_empty` (Probe lief in einer Transaktion mit
`ROLLBACK`, keine Testzeile zurückgeblieben, verifiziert).

→ **DoD-Punkt 1 (Vollzyklus für alle 6 Portfolios, `reject_idea`, DB-Validierung)
ist damit erfüllt.**

### Nebenbefunde aus dem Sonderlauf

- **F101-Fix live bestätigt:** CHARTIST kaufte ADSK — exakt der Titel, der am
  27.07. noch mit `stop_loss_too_tight` abgelehnt wurde. Gleicher Einstieg
  (234,31), gleicher Floor (8,26835 %), aber Stop jetzt 214,93 statt 214,94 →
  `actual_loss_pct` 8,27109 % ≥ Floor, `ok: true`. Die Order steht als `NEW`
  beim Broker (Sonntag, Markt geschlossen) und füllt am Montag zur Eröffnung.
- **Companion-Items greifen:** Decisions aus Lauf 3 zitieren vier
  `aktienfinder_screener`-Items aus **früheren** Zyklen — genau die
  Fundamentaldaten, deren Fehlen GUARDIAN/CONTRA vorher als Ablehnungsgrund
  angaben.
- **Digest-Bug gefunden und behoben (F101):** `_count_open_positions` ankerte auf
  `max(position_snapshot.ts)`. Ein Portfolio ohne Positionen schreibt gar keine
  Positionszeilen, deshalb blieb der Zähler auf dem letzten Tag mit Bestand
  stehen — CONTRA meldete am 02.08. „1 offene Position" neben einem
  100-%-Cash-Depotwert (AAOI wurde am 29.07. geschlossen). Der Zähler hängt jetzt
  am neuesten `portfolio_snapshot` (dieselbe Verankerung, die der
  `/snapshot`-Endpoint schon nutzte).

### Weiterhin offen (keine stillschweigende Erledigung)

- ~~Risk-Gate „je Regelklasse mindestens ein echter Reject im Testlauf"~~ →
  **erledigt am 02.08.2026:** Ralf hat die Umformulierung auf „Unit-Test-Nachweis
  je Klasse + Live-Reject je erreichbarer Klasse" freigegeben; der Punkt ist oben
  entsprechend abgehakt und begründet.
- **HITL Approve/Reject/Timeout end-to-end:** für Paper ist HITL bewusst aus
  (`config/hitl.yaml`, F072). Approve/Reject sind aus F022 nachgewiesen, der
  30-Minuten-Timeout-Sweep läuft seit F049 als Job — ein echter End-to-End-Beleg
  bräuchte eine bewusste HITL-Testrunde (`/hitl on`, eine Freigabe abwarten bzw.
  verfallen lassen). Braucht Ralfs Go, weil es echte Paper-Orders verzögert.
- **Digest „kommt täglich":** die Zahlen sind jetzt gegen DB-Queries verifiziert
  (siehe oben); die Zustellung selbst bestätigt Ralf aus dem Telegram-Verlauf.
