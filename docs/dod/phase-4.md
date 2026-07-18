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

- [ ] Vollständiger Zyklus läuft automatisch für alle 6 Portfolios; jede Persona
      erzeugt decisions inkl. `reject_idea`; `input_research_ids`-Pflicht wird
      DB-seitig validiert
      **Teilweise:** [F015](../features/F015-persona-portfolio-seed.md) — die 6
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
- [ ] Risk-Gate: beide Regelebenen implementiert, 100 % Branch-Coverage der
      Regellogik; je Regelklasse mindestens ein echter Reject im Testlauf
      dokumentiert
      **Vorarbeit aus Phase 2** ([F004](../features/F004-risk-gate.md)): Regellogik
      + Coverage-Ziel bereits erfüllt. **Offen:** der "echte Reject im Testlauf"
      braucht den laufenden Orchestrator-Zyklus, nicht nur Unit-Tests.
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
- [ ] 5 Handelstage in Folge: alle geplanten Zyklen (4/Tag Aktien +
      CRYPTOR-Plan) gelaufen, 0 unbehandelte Exceptions; Crash-Recovery getestet
      (Container-Kill mitten im Zyklus → Resume via Postgres-Checkpointer)
      **Teilweise:** [F025](../features/F025-cycle-scheduling.md) —
      `config/cycles.yaml` + `build_scheduler` (APScheduler, alle 4 Aktien-Zyklen +
      CRYPTOR Werktags-/Wochenend-Zeiten) fertig und getestet (Job-Registrierung,
      Zeitzonen, abschaltbare Zyklen). **Bewusst nicht gestartet** — ein laufender
      Scheduler löst automatisiert, unbeaufsichtigt echte Zyklen aus (Kosten, ggf.
      echte Orders); Aktivierung erfordert Ralfs ausdrückliches Go (siehe F025 §6).
      Ohne laufenden Scheduler kein 5-Tage-Dauerlauf, kein Crash-Recovery-Test.
- [ ] Tageskosten ≤ Cap; `cost_ledger` stimmt stichprobenhaft mit
      LiteLLM-Abrechnung überein
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
  F076-Deploy (15.07.2026) — noch keine 5 Tage seit dem letzten Rebuild.
- **Kosten-Cap-Stichprobe gegen echte LiteLLM-Abrechnung:** weiterhin nicht
  durchgeführt.
- **HITL Approve/Reject/Timeout end-to-end im Dauerbetrieb:** für Paper seit
  F072 (13.07.2026) nicht mehr zutreffend — HITL ist für `paper` jetzt aus,
  der Nachweis von F049–F052 bleibt als historischer Beleg für den
  Interrupt-/Resume-Mechanismus gültig, ist aber kein laufender
  Dauerbetriebs-Nachweis mehr. Für `live` (Invariante #5, weiterhin
  HITL-pflichtig) steht ein Dauerbetriebs-Nachweis naturgemäß noch aus, da
  kein Live-Betrieb existiert.

**Einordnung ggü. ARCHITECTURE.md §8:** Phase 4 ist damit weiterhin formal
nicht abgeschlossen (2 von 6 DoD-Punkten offen: Mehrtage-Dauerlauf,
Kosten-Cap-Stichprobe). Phase 5 (§8, "Review, Journal & Wettbewerbsstart" —
Review-Agent, Slippage-Malus, Leaderboard, offizieller Start des
8-Wochen-Wettbewerbs) hat inhaltlich noch nicht begonnen; F072 trägt zwar
`Phase: 5` im Feature-Dokument (Ralfs spontane Betriebsentscheidung, keine
formale Phasen-Eröffnung), ist aber ein Ops-Fix am Paper-Betrieb, kein
P5-Feature im Sinne von ARCHITECTURE.md §8. Der 8-Wochen-Wettbewerbs-Zähler
(ARCHITECTURE.md §4.7) hat noch nicht offiziell begonnen — das ist laut §8
selbst ein P5-DoD-Punkt ("Wettbewerb offiziell gestartet: Stichtag
dokumentiert, alle 6 Portfolios auf 5.000 USD").
