# Phase 6 — Live (Gewinner): Planung & Definition of Done

Checkliste aus ARCHITECTURE.md §8. **Status (01.10.2026):** Wettbewerb am
**Fr 18.09.2026** beendet, Endabrechnung erzeugt
([Report](../reports/endabrechnung-2026-09-18.md)) — **Sieger nach §4.7: CRYPTOR
(Score 0,909)**. Code-Vorbereitung F121–F123 live auf der Box seit 01.10.2026.
Offen ist Ralfs Gewinner-Entscheidung als ADR; davor wird live nichts angefasst.

Diese Datei ist die Vorbereitung, nicht der Abschluss: kein Punkt wird abgehakt,
bevor der Nachweis existiert.

## 1. Zeitplan

| Datum | Was | Wer | Stand |
|---|---|---|---|
| bis 17.09. | Trockenlauf Settlement + Endabrechnung gegen die Produktions-DB (F121 §7) | Claude/Ralf | ❌ entfallen — F121 war bis 01.10. nicht auf der Box |
| Fr 18.09., 16:35 ET | Schlussbewertung + Endabrechnung per Telegram (automatisch) | Scheduler | ❌ nicht gelaufen (Box auf F119) → am 01.10. rekonstruiert, s. F121 Nachtrag |
| 01.10. | Gewinner-Report als Markdown | Claude | ✅ `docs/reports/endabrechnung-2026-09-18.md` |
| offen | ADR mit der Gewinner-Entscheidung | Ralf entscheidet | |
| danach | Live-Konto, Funding, Keys, Aktivierung | Ralf (manuell) | |
| danach | Erste Live-Order mit HITL, Kill-Switch-Drill, Steuer-Export | Ralf + Claude | |

Zwischen Stichtag und Auswertung lag ein Betriebsausfall: kein LLM-Guthaben
22.09.–01.10. (keine Zyklen mit Decisions), dazu die F125-Funde (Doppel-CLOSE,
ungewollte GPRO-Short bei VULTURE seit 14.09.). Das Wertungsfenster endet am
18.09. und ist davon nicht betroffen; der GPRO-Short liegt im Fenster, verschiebt
VULTUREs Depotwert aber nur um ~4 USD und ändert keinen Rang.

Das Paper-Feld läuft während und nach alledem weiter (ARCHITECTURE.md §4.7) —
P6 stoppt nichts.

## 2. DoD-Checkliste

- [ ] **Gewinner-Report (8 Wochen, alle 5 Kriterien) erzeugt; Entscheidung als ADR**
      *Code steht ([F121](../features/F121-endabrechnung-und-gewinner-report.md)):*
      Schlussbewertung zum Stichtag (`competition-settlement`-Job, 16:35 ET),
      geschlossenes Wertungsfenster in allen Kennzahlen, Report als Markdown
      (`scripts/final_report.py`) und als Telegram-Push.
      *Erledigt 01.10.2026:* Schlussbewertung rekonstruiert (C4-Positionen +
      Schlusskurse 18.09., F121 Nachtrag), Report
      [`endabrechnung-2026-09-18.md`](../reports/endabrechnung-2026-09-18.md).
      Der Telegram-Push ist nicht gelaufen. *Offen:* der ADR mit Ralfs Entscheidung.
- [ ] **Live-Keys ausschließlich in der Prod-Umgebung; gitleaks-Scan über die
      gesamte Repo-Historie sauber**
      *Offen, rein Ops.* gitleaks läuft in CI je Push; der Historien-Scan ist
      ein eigener Lauf:
      `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect --source=/repo --log-opts="--all"`.
      Live-Keys existieren heute in **keiner** Umgebung und stehen bewusst nicht
      in `.env.example` (Invariante #5). Die Variablennamen, sobald es sie gibt:
      `ALPACA_LIVE_<PERSONA>_KEY_ID` / `ALPACA_LIVE_<PERSONA>_SECRET_KEY`.
- [ ] **Erste Live-Order nach Telegram-Approval ausgeführt; GTC-Stop beim Broker
      verifiziert (Alpaca-Dashboard)**
      *Code steht ([F122](../features/F122-live-pfad-vorbereitung.md)):*
      `AlpacaLiveAdapter` (erbt den gehärteten Order-Pfad inkl. Bracket-Stop),
      Registry-Auflösung hinter dem Flag `ATLAS_LIVE_TRADING_ENABLED=true`,
      Mode-Guard in `execute_decision`. HITL für Live steht auf `true`
      (`config/hitl.yaml`) und lässt sich per Telegram nicht abschalten.
      *Offen:* Konto, Funding, Keys, Portfolio-Anlage mit `mode=live`.
- [ ] **Kill-Switch-Drill: Live-Circuit-Breaker simuliert ausgelöst und Verhalten
      dokumentiert**
      *Offen.* Vorhandene Mechanik: Der Circuit Breaker ist deterministischer
      Code (`src/risk/gate.py`, Drawdown > 15 % gegen den Portfolio-Höchststand →
      BUY wird abgelehnt, `circuit_breaker_sell_only`), gespeist aus
      `read_portfolio_risk_state` (`src/orchestrator/risk_inputs.py`). Zusätzlich
      als sofortiger Not-Aus: `/pause <persona>` per Telegram. **Der Drill braucht
      keinen neuen Code**, sondern ein Drehbuch: Live-Portfolio mit künstlich
      hohem historischem Peak in einer Staging-DB → Zyklus → Nachweis, dass jeder
      BUY abgelehnt und jeder SELL/CLOSE weiter zugelassen wird.
- [ ] **Steuer-Export (Trades-CSV für Anlage KAP) generierbar**
      *Code steht ([F123](../features/F123-steuer-export-trades-csv.md)):*
      `scripts/export_trades.py --persona X --year 2026`, FIFO-gematchte
      realisierte Lots, §-23-Kennzeichnung für Krypto. *Offen:* die
      EUR-Umrechnung (Entscheidung 2 unten) und ein Lauf gegen echte Live-Daten.

## 3. Was im Code vorbereitet ist (05.09.2026, Status 01.10.2026)

| Feature | Inhalt | Zustand |
|---|---|---|
| F121 | Stichtags-Schlussbewertung, geschlossenes Wertungsfenster, Endabrechnung (Markdown + Telegram), Scheduler-Job, manuelle Fallback-Skripte | live seit 01.10.; Stichtag verpasst, Bewertung nachträglich rekonstruiert. **Achtung:** `scripts/final_settlement.py` taugt nur *am* Stichtag — es bewertet mit den aktuellen Broker-Daten |
| F122 | `AlpacaLiveAdapter`, Registry-Gate, Mode-Guard im Order-Pfad, Credential-Check für Live-Keys | **schlafend** — kein Eintrag, kein Key, kein Flag |
| F123 | Steuer-Export als CSV (FIFO, §23-Flag) | nutzbar, auch gegen Paper-Daten |

Nicht vorbereitet, weil es eine Entscheidung braucht: **Kraken-Adapter**. Nach
[ADR-0002](../adr/0002-alpaca-crypto-de-residents.md) ist Alpaca-Krypto für
DE-Residents live nicht verfügbar — **CRYPTOR hat gewonnen**, ein Kraken-Adapter
ist damit Voraussetzung für einen Live-Gang des Siegers und ein eigenes Feature (Schätzung: eine Größenordnung mehr Arbeit als F122, weil kein
gehärteter Order-Pfad geerbt werden kann).

## 4. Was nur Ralf tun kann

1. Live-Konto bei Alpaca eröffnen und mit 2.000 € funden (→ Entscheidung 1).
2. Live-Keys in die Prod-`.env` der Box, **nirgends sonst**.
3. `config/broker.yaml`: Eintrag `adapter: alpaca_live` für die Gewinner-Persona.
4. `ATLAS_LIVE_TRADING_ENABLED=true` in der Prod-Umgebung setzen.
5. Live-Portfolio mit `mode=live` anlegen (Seed-Skript zieht heute nur Paper —
   kleines Zusatzfeature, sobald 1.–4. entschieden sind).
6. Gewinner-ADR schreiben, gitleaks-Historien-Scan laufen lassen.

Punkt 3 und 4 sind bewusst getrennt: keiner von beiden wirkt allein.

## 5. Offene Entscheidungen (Geld-Themen — nie stillschweigend)

1. **2.000 € auf einem USD-Konto.** Alpaca führt USD. Offen: Umrechnung beim
   Funding, `portfolio.base_ccy` (`EUR` mit Umrechnung oder schlicht `USD` mit
   dem eingezahlten Gegenwert), und ob `start_value` der EUR- oder der
   USD-Betrag ist. Alle Kennzahlen rechnen heute in der Kontowährung.
2. **FX-Kurs für den Steuer-Export.** EZB-Referenzkurs des Handelstages oder
   BMF-Monatsdurchschnitt. F123 liefert bewusst USD und eine `waehrung`-Spalte,
   bis das entschieden ist.
3. **Positionsgröße bei 2.000 € — konkretes Problem, nicht theoretisch.** Die
   Risk-Configs sind prozentual, skalieren also mit. Bei ~2.150 USD Kapital wird
   daraus je Persona ein Positionsbudget von:

   | Persona | max_position_pct | Budget je Position | teuerste kaufbare Aktie |
   |---|---:|---:|---:|
   | VULTURE | 3 % | ~65 $ | ~65 $ |
   | HYPE | 8 % | ~172 $ | ~172 $ |
   | CONTRA / CHARTIST | 10 % | ~215 $ | ~215 $ |
   | GUARDIAN | 15 % | ~322 $ | ~322 $ |
   | CRYPTOR | 20 % | ~430 $ | (Krypto, fraktional) |

   Weil Alpaca für Bracket-Orders mit Pflicht-Stop **ganze Aktien** verlangt
   (F052/F079), ist jede Aktie oberhalb dieses Budgets live schlicht nicht
   kaufbar — die Idee wird als `reject_idea` verworfen. Die Live-Persona handelt
   damit ein spürbar engeres Universum als im Paper-Lauf mit 5.000 USD.
   Optionen: höheres `max_position_pct` für das Live-Portfolio (ADR + Bump nötig,
   verändert den Vergleich), mehr Kapital, oder bewusst akzeptieren und
   dokumentieren. **Braucht Ralfs Entscheidung vor der ersten Live-Order.**
4. **Review-Pflicht für am 18.09. offene Positionen** (§4.7-Kriterium 4). Ralfs
   Entscheidung vom 16.08. regelt die *Bewertung* (Schlusskurs), nicht das
   Review. Aktueller Stand im Code: offene Positionen zählen über die Kriterien
   1–3, nicht über die Thesen-Qualität. Bleibt es dabei?
5. **F120-Fixes nach dem Stichtag.** Die drei Ursachen der GUARDIAN-/
   CRYPTOR-Inaktivität ([F120](../features/F120-guardian-cryptor-inaktivitaet.md))
   sind analysiert und bewusst nicht behoben, weil sie mitten in den Wettbewerb
   eingegriffen hätten. Ab dem 19.09. ist dieser Grund weg — Reihenfolge und
   Umfang entscheidet Ralf (der Universums-Filter berührt Invariante #10 und
   braucht einen ADR).
6. **HITL-Abschaltung live** ist P7 und ausdrücklich erst nach 4 Wochen ohne
   Risk-Inzidenz, per ADR (ARCHITECTURE.md §8). Bis dahin bleibt `live: true`.

## 6. Altlasten aus früheren Phasen (Stand 05.09.2026, ergänzt 01.10.2026)

Diese Punkte sind seit Monaten offen, weil sie einen Live-Nachweis brauchten, den
es damals nicht geben konnte. Der Scheduler läuft seit 07.07.2026 — die
Voraussetzung ist also erfüllt, es fehlt nur der dokumentierte Nachweis:

- **Phase 3** (4 Punkte): PDF-Fallback binnen 5 Min, aktienfinder-Grabbing täglich
  per Schedule, EDGAR + Marktdaten 5 Tage unterbrechungsfrei (Grafana-Freshness),
  VULTURE-Screener täglich. Alle vier laufen inzwischen als Scheduler-Jobs; der
  Nachweis ist ein Blick in `docs/dod/phase-3.md` + Grafana, keine Arbeit am Code.
  **Ausnahme aktienfinder:** 25.09.–01.10.2026 täglich fehlgeschlagen (Login-
  Umbau der Seite, behoben mit [F125](../features/F125-close-guard-und-aktienfinder-login.md));
  der Nachweis-Zeitraum muss danach liegen.
- **Phase 4** (2 Punkte): HITL-Timeout end-to-end (Approve/Reject sind
  nachgewiesen, der 30-Minuten-Sweep existiert seit F025/F049, der Nachweis
  fehlt) und Telegram-Tagesdigest gegen DB-Query verifiziert.

Empfehlung: vor dem Live-Start abarbeiten. Ein Live-Konto an einem System, dessen
HITL-Timeout nie end-to-end nachgewiesen wurde, ist genau die Stelle, an der
Invariante #5 praktisch geprüft wird — Timeout = Reject ist die letzte Sperre,
wenn Ralf eine Live-Anfrage nicht sieht.
