# F122 — Live-Pfad vorbereiten: Adapter, Mode-Guard, Aktivierungs-Schalter

Status: implementiert, **schlafend** — kein Persona-Eintrag, kein Key, kein
gesetztes Flag. Es handelt nichts live.
Datum: 2026-09-05
Phase: 6 (Vorbereitung; die Aktivierung ist Ralfs Entscheidung nach der
Gewinner-Kür)
Auslöser: P6-DoD „Live-Adapter, HITL an" (ARCHITECTURE.md §8)
ADR: [ADR-0017](../adr/0017-live-aktivierung-per-flag-und-mode-guard.md) — berührt Invariante #5

## 1. Zieldefinition

**Done heißt:** wenn Ralf nach der Kür ein Live-Konto eröffnet, ist der Weg
dorthin drei bewusste Handgriffe (Keys ins Environment, Persona-Eintrag in
`config/broker.yaml`, Flag setzen) — und kein Code-Change am Order-Pfad mehr.
Bis dahin ist jeder dieser Handgriffe für sich wirkungslos.

**Scope:** `AlpacaLiveAdapter`, Registry-Auflösung + Aktivierungs-Flag,
Mode-Guard im Order-Pfad, Credential-Validierung für Live-Keys.
**Non-Scope:** Live-Keys (existieren nirgends, Invariante #5), das Funding, der
EUR/USD-Umgang beim 2.000-€-Konto, die HITL-Umschaltung für Live (steht bereits
auf `true` und bleibt es — `set_hitl_required` weigert sich, `live` per Telegram
zu schalten).

## 2. Warum Subclass statt zweiter Implementierung

`AlpacaLiveAdapter` erbt `AlpacaPaperAdapter` und überschreibt genau ein
Klassenattribut: `_paper = False`. Der Order-Pfad — Bracket-Order mit
Pflicht-Stop-Leg (F052), Ganzaktien-Rundung (F079), die
`client_order_id`-Replay-Erkennung (F027), das Cancel-vor-Verkauf-Verhalten
(F077) — ist seit Monaten gegen einen echten Broker gehärtet. Echtes Geld ist der
denkbar schlechteste Ort für eine zweite, weniger getestete Variante davon. Bei
Alpaca unterscheidet Paper von Live nichts als der Endpoint, und genau das ist
das eine, was diese Klasse ändert.

`_paper` ist ein Klassenattribut, kein Konstruktor-Argument und keine
Environment-Variable: ein Klassenattribut lässt sich nicht durch einen Tippfehler
in der Config oder eine verirrte Env-Var umlegen.

## 3. Drei unabhängige Sperren

1. **Config:** kein `adapter: alpaca_live`-Eintrag in `config/broker.yaml`.
2. **Environment:** kein Live-Key, und `_require_env` bricht hart ab. In
   `.env.example` steht bewusst nichts dazu (Invariante #5), die Variablennamen
   stehen in `docs/dod/phase-6.md`.
3. **Aktivierungs-Flag:** `ATLAS_LIVE_TRADING_ENABLED=true`. Ohne das verweigert
   die Registry den Bau des Live-Adapters, auch mit Eintrag und Keys. Live wird
   damit *eingeschaltet*, nicht *versehentlich erreicht*.

Dazu der **Mode-Guard** in `execute_decision` — der einzigen Stelle, die
überhaupt Orders platzieren darf (Invariante #2): stimmen `portfolio.mode` und die
Modus-Zuordnung des Adapters nicht überein, fliegt ein `ValueError`, bevor der
Broker gerufen wird. Beide Richtungen sind Fehler: ein Paper-Portfolio am
Live-Konto gibt echtes Geld für ein Experiment aus; ein Live-Portfolio am
Paper-Konto erzeugt eine `mode='live'`-Order-Historie zu Orders, die es nie gab —
das fällt erst beim Steuer-Export auf.

## 4. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #5 Paper/Live-Trennung | ja, zentral | Drei Sperren plus Mode-Guard, s. o. Der Guard ist neu — bis heute wurde `portfolio.mode` im Order-Pfad **nirgends** geprüft, es gab nur nichts Live-fähiges zu verwechseln. |
| #4 Stop-Loss | nein | Unverändert geerbt: dieselbe Bracket-Order mit GTC-Stop. |
| #2 Privilege Separation | nein | Kein neuer Order-Einstiegspunkt. |
| #10 Fairness | nein | Der Live-Adapter betrifft ein Portfolio nach dem Wettbewerb. |

**Was diese Vorbereitung bewusst nicht entscheidet:** ob der Live-Gewinner
überhaupt über Alpaca läuft (bei CRYPTOR wäre Kraken zu prüfen — ADR-0002), wie
2.000 € auf ein USD-Konto kommen, und mit welchem `base_ccy` das Live-Portfolio
angelegt wird. Alles Geld-Themen → Ralf, notiert in `docs/dod/phase-6.md`.

## 5. Testdefinition (vor der Umsetzung geschrieben)

`tests/broker/test_alpaca_live.py`

1. Der Live-Adapter baut den `TradingClient` mit `paper=False`, der Paper-Adapter
   mit `paper=True`.
2. Der Live-Adapter erbt den Order-Pfad unverändert (Identität der Methoden).
3. Registry verweigert den Live-Adapter ohne Flag — und auch bei `=1` statt
   `=true` (kein „irgendwas gesetzt reicht").
4. Mit Flag, Eintrag und Keys wird er gebaut.
5. `validate_all_credentials` prüft auch Live-Keys — und verweigert ohne Flag.
6. `adapter_mode` bildet jeden bekannten Adaptertyp ab und lehnt unbekannte ab.

`tests/orchestrator/test_trading.py`

7. Paper-Portfolio + Live-Adapter → `ValueError`, keine Order, Decision bleibt
   `APPROVED`.
8. Live-Portfolio + Paper-Adapter → `ValueError`.
9. Passendes Paar → Order mit `order_record.mode = live`.

## 6. Rollback

`config/broker.yaml`-Eintrag entfernen oder `ATLAS_LIVE_TRADING_ENABLED` löschen —
beides beendet Live sofort und ohne Deploy. Der Code selbst ist ohne diese beiden
Dinge wirkungslos.
