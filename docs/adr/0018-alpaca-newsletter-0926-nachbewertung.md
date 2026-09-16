# ADR-0018: Alpaca-Newsletter 09/2026 — Nachbewertung von ADR-0015 und Ableitung des Backlogs

* Status: accepted — Kalender-Gate von Ralf am 16.09.2026 beauftragt (F124), die
  übrigen Punkte als Backlog/Ablehnung festgehalten
* Deciders: Ralf Schmid
* Datum: 2026-09-16
* Betrifft Invariante(n): **#2** (Privilege Separation), **#10** (Fairness) — beide
  als Ablehnungsgrund, keine wird aufgeweicht
* Betrifft ARCHITECTURE.md **§3.5** (Datenquellen), **§5.2** (Zyklen), **§8** (Phasen)

## Kontext und Problemstellung

Alpaca hat am 16.09.2026 einen Newsletter geschickt, der eine Community-Fallstudie
(„Building AlphaDesk", LangGraph-Pipeline eines Studenten) bewirbt und darunter
vier Ressourcen verlinkt: Skills Library, „Building AI Trading Applications",
MCP-Server, CLI. Frage von Ralf: Was davon vervollständigt ATLAS?

**Ausgangslage:** [ADR-0015](0015-alpaca-agent-research-tooling.md) hat drei der
vier beworbenen Ressourcen am 11.08.2026 bereits bewertet und abgelehnt (Option E:
kein CLI/MCP/Skill im Laufzeitpfad, stattdessen die inhaltlichen Lücken über das
bestehende SDK schließen → F103, F104, F105, später F111). Der Newsletter ist
insofern zu weiten Teilen eine Wiedervorlage.

**Was tatsächlich neu ist:**

1. Die AlphaDesk-Fallstudie selbst (vorher nicht existent).
2. `github.com/alpacahq/agentic` — ein „Multi-Platform Plugin Marketplace", der die
   MCP-Server als **OAuth-geschützte gehostete Endpoints** für Cursor/Claude
   Code/Codex/VS Code bündelt. In ADR-0015 noch nicht vorhanden.

Beide wurden für diese Bewertung live gelesen (16.09.2026).

## Entscheidungstreiber

* ADR-0015 ist erst fünf Wochen alt; eine Neubewertung braucht ein neues Argument,
  nicht eine neue Mail.
* Der Wettbewerb endet am **Fr 18.09.2026**. Jede Änderung, die die
  Versuchsbedingungen berührt, ist bis dahin gesperrt (ARCHITECTURE.md §4.7).
* Der Order-Pfad ist deterministisch und exklusiv (Invariante #2, ADR-0012).
* Phase 6 (Live) steht unmittelbar bevor — Arbeiten, die erst live Wert schaffen,
  gehören dorthin und nicht in die letzten Wettbewerbstage.

## Betrachtete Optionen

* **A** — Nichts tun, ADR-0015 genügt
* **B** — MCP/CLI-Ablehnung revidieren, weil der `agentic`-Marketplace den Zugang
  vereinfacht
* **C** — AlphaDesk-Architektur als Vorlage übernehmen
* **D** — ADR-0015 bestätigen und den Newsletter als Anlass für einen gezielten
  Abgleich der **ungenutzten Alpaca-Endpoints** nehmen

## Entscheidung

Gewählt: **Option D**.

### D.1 — Bestätigt: CLI, MCP-Server und `agentic`-Plugins bleiben draußen

Der Marketplace verschiebt die Bewertung aus ADR-0015 **ins Negative**, nicht ins
Positive: gehostete, OAuth-geschützte MCP-Endpoints bedeuten, dass die
Alpaca-Autorisierung außerhalb unseres Containers liegt und die einzige Begrenzung
weiterhin ein Toolset-Filter (`ALPACA_TOOLSETS`) ist — Konfiguration, keine harte
Grenze. Ein zweiter Credential- und Order-Pfad neben `BrokerAdapter` bleibt ein
direkter Bruch von Invariante #2. Unverändert unbedenklich: Skills Library und CLI
auf Ralfs Arbeitsrechner mit eigenem Paper-Key, außerhalb von Repo und Zyklus.

### D.2 — AlphaDesk ist ein Spiegel, keine Quelle

Die Fallstudie beschreibt dieselbe Grundform wie ATLAS (LangGraph-State-Machine,
deterministischer Risk-Node vor dem Order-Node), aber mit einer Persona, ohne HITL,
ohne Kostenkontrolle, ohne Lineage-Pflicht. Ihre vier „vor Produktion"-Punkte
gegen ATLAS gehalten:

| AlphaDesk-Punkt | ATLAS |
|---|---|
| Deterministische Guardrails vor dem Order-Node | vorhanden (`src/risk/gate.py`, ADR-0012) |
| Backtesting über mehrere Marktphasen | vorhanden (F111) |
| WebSocket statt REST-Polling | siehe D.4 — abgelehnt |
| Volatilitätsbasiertes Sizing statt statischer Guardrails | **echte Lücke**, siehe D.5 |

Der 48-Stunden-Ausfall der Fallstudie (Connection-Pooling unter Cron) ist für uns
kein Befund, sondern eine Warnung gegen langlebige Verbindungen — sie stützt D.4.

### D.3 — Beauftragt: Handelskalender-Gate (F124)

Der Abgleich der ungenutzten Endpoints förderte einen echten Fehler zutage:
`scheduler.py` feuert die Aktienzyklen per Cron `mon-fri` ohne jede Kenntnis des
Börsenkalenders. An ~10 Feiertagen laufen drei Zyklen gegen tote Daten, an
Half-Days liegen C3/C4 hinter dem Schlusskurs, und dabei entstehende Orders werden
bis zur nächsten Eröffnung gequeued. Deterministisch zu lösen über
`TradingClient.get_calendar`. Umsetzung:
[F124](../features/F124-handelskalender-gate.md), Designentscheidungen:
[ADR-0019](0019-handelskalender-gate-fail-open.md).

### D.4 — Abgelehnt: `TradingStream` (WebSocket) statt Fill-Polling

Der Nutzen wäre Latenz. Bei drei Zyklen pro Tag ist Latenz kein Engpass, und
`reconcile_order_fills` (15-Minuten-Intervall, F075) erfüllt seinen Zweck. Dagegen
steht eine dauerhaft offene Verbindung als neue Fehlerklasse im Scheduler-Container
— genau das, woran die AlphaDesk-Installation nach 48 Stunden scheiterte — bei der
das Polling als Fallback ohnehin bestehen bleiben müsste. Der einzige eigenständige
Mehrwert wäre ein „Stop-Loss ausgelöst"-Alert; der ist, falls gewünscht, über ein
engeres Polling-Intervall zu haben und braucht keinen Stream.

### D.5 — Vertagt auf nach dem 18.09.2026

| Thema | Warum vertagt, nicht abgelehnt |
|---|---|
| **`get_account_activities`** (DIV/FEE/INT) | `portfolio_snapshot` liest die echte Alpaca-Equity, Dividenden und Gebühren stecken also in den Zahlen — aber nirgends steht, *warum* sich Cash bewegt hat, und F123 exportiert ausschließlich realisierte Trades. Für die Anlage KAP fehlen damit Dividenden und US-Quellensteuer. Wert entsteht **live**, nicht im Paper-Feld; gehört zusammen mit der offenen FX-Entscheidung (phase-6 §5.2) in **ein** Feature, sonst wird der Steuer-Export zweimal gebaut. |
| **`CorporateActionsClient`** | In F103 §1 bewusst als Non-Scope geparkt. Ein Split während einer gehaltenen Position korrigiert Alpaca kontoseitig, unser FIFO-Matching rechnet mit den Vor-Split-Lots weiter — still falsche Steuerzahlen, genau die Fehlerklasse, die F123 §3 als gefährlichsten Output benennt. Fachlich derselbe Bereich wie oben, deshalb gebündelt. |
| **Volatilitätsadaptives Sizing** | `compute_position_value_usd` = `conviction × max_position_pct × equity`; ATR wirkt heute nur auf die Stop-Distanz, nicht auf die Größe. Berührt Invariante #1 und verändert die Vergleichsbedingungen aller sechs Personas — nur mit eigenem ADR und frühestens in derselben Runde wie die F120-Fixes. |

### D.6 — Abgelehnt: Optionen, Short-Selling/Locates

Alpaca bietet beides vollständig an. Kein Persona-Charter sieht es vor; eine
Aufnahme wäre eine Charter-Änderung mit `charter_version`-Bump und damit ein Bruch
der Vergleichbarkeit über die acht Wochen (Invariante #10). Kein Bedarf, kein
Lerngewinn, der das aufwöge.

### Konsequenzen

* Gut, weil der nächste Alpaca-Newsletter nicht erneut eine Grundsatzevaluation
  auslöst — die Ablehnung ist jetzt zweifach begründet und datiert.
* Gut, weil aus einer Werbemail ein konkreter, deterministischer Bugfix (F124)
  geworden ist statt einer Tool-Integration.
* Schlecht, weil D.5 echte Lücken beschreibt, die bis nach dem 18.09. offen
  bleiben — der Steuer-Export ist bis dahin unvollständig, und das ist ein
  DoD-Punkt der Phase 6.
* Folgearbeit: F124 (jetzt), Activities + Corporate Actions als ein Feature nach
  der Gewinner-Kür, Vola-Sizing mit eigenem ADR im Paket der F120-Fixes.

## Pro/Contra der Optionen

### A — Nichts tun

* Gut, weil ADR-0015 die drei beworbenen Werkzeuge bereits sauber abgedeckt hat.
* Schlecht, weil der Endpoint-Abgleich dann unterblieben wäre — und mit ihm der
  Kalender-Befund, der ein echter Betriebsfehler ist.

### B — MCP/CLI-Ablehnung revidieren

* Gut, weil gehostete OAuth-Endpoints den Einstieg tatsächlich vereinfachen.
* Schlecht, weil genau diese Vereinfachung die Credentials aus unserem Container
  heraus und die Order-Fähigkeit an einem Env-Var-Filter statt an `BrokerAdapter`
  aufhängt (Invariante #2).

### C — AlphaDesk-Architektur übernehmen

* Gut, weil die Fallstudie bestätigt, dass unser Grundmuster tragfähig ist.
* Schlecht, weil ATLAS in jedem verglichenen Punkt bereits weiter ist; zu
  übernehmen wäre einzig das Vola-Sizing — und das ist ein Invarianten-Thema, kein
  Copy-Paste.

### D — Bestätigen + Endpoint-Abgleich

* Gut, weil der Ertrag aus dem liegt, was Alpaca *nicht* bewirbt: ungenutzte
  API-Endpoints unter dem bereits vorhandenen SDK.
* Gut, weil jede Maßnahme deterministischer Code ohne LLM-Beteiligung bleibt.
* Schlecht, weil der Abgleich manuell ist und beim nächsten API-Zuwachs erneut
  anfällt.
