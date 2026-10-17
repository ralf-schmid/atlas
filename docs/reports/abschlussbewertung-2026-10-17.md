# Abschlussbewertung — ATLAS-Wettbewerb und Betrieb bis 17.10.2026

Stand: 17.10.2026. Grundlage: die Endabrechnung
[`endabrechnung-2026-09-18.md`](endabrechnung-2026-09-18.md) (aus der
Wettbewerbs-DB, ohne LLM erzeugt), die Feature- und DoD-Dokumente bis F127 und
eine Nachrechnung der Endabrechnungs-Zahlen (§3). Die Bewertung ist eine
Einordnung, keine Anlageberatung.

**Was diese Auswertung nicht enthält:** Die Produktions-DB auf der Box war aus
der Arbeitsumgebung nicht erreichbar. Für das weiterlaufende Paper-Feld
(19.09.–17.10.2026) liegen deshalb keine Zahlen vor, ebenso wenig für die exakte
Summe der LLM-Kosten aus `cost_ledger`. Wie beides nachgezogen wird, steht in §7.

## 1. Kurzfassung

- **Sieger nach §4.7 ist CRYPTOR** (Score 0,909, Rang 2 CONTRA mit 0,547). Die
  Rangfolge hält auch unter anderen Gewichtungen (§3.2). Das Ergebnis ist also
  formal eindeutig.
- **Wirtschaftlich hat keine Persona den Markt geschlagen.** SPY Buy-and-Hold
  lag im Fenster bei +3,08 %. Die beste Persona (CRYPTOR) kam auf +1,28 %. Das
  Feld zusammen verlor 0,45 % (−136 USD auf 30 000 USD), dazu kommen geschätzt
  150–185 USD LLM-Kosten.
- **Statistisch ist der Sieger nicht von Null zu unterscheiden.** Das
  95-%-Intervall von CRYPTORs Sortino reicht ungefähr von −2,0 bis +6,6, und die
  Intervalle aller sechs Personas überlappen sich (§3.3). Der §4.7-Vorbehalt
  („Regime- und Rausch-Glück") ist damit nicht nur Formalie, er beschreibt das
  Ergebnis.
- **CRYPTORs Sieg ist ein Sieg durch geringe Investitionsquote.** 12 Trades in 8
  Wochen, am Stichtag 93 % Cash. Laut [F120](../features/F120-guardian-cryptor-inaktivitaet.md)
  lag das nicht an der Strategie, sondern an der Research-Auswahl: CRYPTOR bekam
  zu nur einem seiner zehn Paare technische Indikatoren zu sehen.
- **Technisch war das Projekt ein Erfolg.** Acht Wochen autonomer Betrieb mit
  sechs Personas, deterministischem Risk-Gate, Lineage bis zur Quelle, HITL,
  doppelten Kosten-Caps und vier UI-Views. Die Phasen 2–5 sind abgeschlossen.
  Alle Invarianten-Verstöße, die im Betrieb auftraten, wurden gefunden,
  dokumentiert und behoben (§5).
- **Der nächste Schritt laut Plan ist Phase 6:** Gewinner-ADR, danach Live mit
  2 000 €. Für CRYPTOR gibt es dafür heute keinen Broker-Weg, denn Alpaca-Krypto
  ist für DE-Residents gesperrt ([ADR-0002](../adr/0002-alpaca-crypto-de-residents.md)).
  Vorher müsste ein Kraken-Adapter gebaut werden (§6).

## 2. Ergebnis des Wettbewerbs (27.07.–18.09.2026)

| Rang | Persona | Score | Depotwert | Rendite n. Kosten | Sortino | Max DD | Thesen | Trades | investiert am Stichtag |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | CRYPTOR | 0,909 | 5 076 $ | +1,28 % | 2,30 | 2,22 % | 50 % (8) | 12 | 7 % |
| 2 | CONTRA | 0,547 | 5 026 $ | +0,48 % | 0,50 | 3,14 % | 40 % (20) | 20 | 65 % |
| 3 | HYPE | 0,501 | 4 986 $ | −0,29 % | −2,11 | 0,53 % | 22 % (9) | 9 | 4 % |
| 4 | GUARDIAN | 0,326 | 4 961 $ | −0,78 % | −3,13 | 0,92 % | 0 % (1) | 2 | 15 % |
| 5 | VULTURE | 0,253 | 4 918 $ | −1,84 % | −1,88 | 3,28 % | 29 % (28) | 33 | 5 % |
| 6 | CHARTIST | 0,201 | 4 897 $ | −2,09 % | −2,31 | 3,32 % | 29 % (14) | 17 | 21 % |
| — | SPY (Benchmark) | — | 5 154 $ | +3,08 % | — | — | — | — | 100 % |

„Investiert" = 1 − Cash/Depotwert am Stichtag, nachgerechnet aus Tabelle 2 der
Endabrechnung.

## 3. Nachrechnung und Belastbarkeit

### 3.1 Score reproduziert

Die Min-max-Normierung aus `src/metrics/competition_score.py` ergibt aus den
Rohwerten der Endabrechnung dieselben Scores (CRYPTOR 0,9091 … CHARTIST 0,2012).
Zwischen Report und Code gibt es keine Abweichung.

### 3.2 Ist der Sieger robust gegen die Gewichtung?

| Variante | Rang 1 | Rang 2 | Rang 3 |
|---|---|---|---|
| §4.7 offiziell (40/25/15/10/10) | CRYPTOR 0,91 | CONTRA 0,55 | HYPE 0,50 |
| nur Kriterien 1–3 (Depotwert-basiert) | CRYPTOR 0,89 | CONTRA 0,58 | HYPE 0,45 |
| alle fünf gleich gewichtet | CRYPTOR 0,88 | HYPE 0,63 | CONTRA 0,46 |
| nur Rendite nach Kosten | CRYPTOR 1,00 | CONTRA 0,76 | HYPE 0,53 |

CRYPTOR liegt in jeder Variante vorn, weil er bei Sortino, Rendite, Thesen und
Zuverlässigkeit jeweils Bester des Feldes ist. Die Sensitivitätsrechnung dient
nur zur Einordnung. §4.7 bleibt verbindlich, und kein Gewicht wird nachträglich
geändert.

### 3.3 Ist der Sieger statistisch belastbar?

Grobe Näherung des Standardfehlers einer annualisierten Sharpe/Sortino-Kennzahl
über 54 Tagesrenditen (Lo 2002, ohne Autokorrelationskorrektur):

| Persona | Sortino | ≈ 95-%-Intervall |
|---|---:|---|
| CRYPTOR | 2,30 | −2,0 … +6,6 |
| CONTRA | 0,50 | −3,7 … +4,7 |
| HYPE | −2,11 | −6,4 … +2,1 |
| GUARDIAN | −3,13 | −7,4 … +1,2 |
| VULTURE | −1,88 | −6,1 … +2,4 |
| CHARTIST | −2,31 | −6,6 … +2,0 |

Alle Intervalle schließen die Null ein und überlappen sich gegenseitig. Nach acht
Wochen lässt sich keine Persona statistisch von einer anderen und auch nicht von
„kein Effekt" unterscheiden. Genau davor warnt ARCHITECTURE.md §4.7.

### 3.4 Was hinter CRYPTORs Zahlen steckt

- **Niedrige Exposition.** Bei 7–20 % Investitionsquote bleiben Volatilität und
  Drawdown zwangsläufig klein, und schon wenige gute Trades ergeben einen hohen
  Sortino. Dieselbe Mechanik erklärt HYPEs kleinsten Drawdown (0,53 %) bei
  negativer Rendite.
- **Datenhunger, nicht Zurückhaltung.** Laut F120 (U1) sah CRYPTOR wegen der
  faktisch alphabetischen Research-Auswahl nur zu AAVE/USD Indikatoren. Sein
  erster Kauf (LINK/USD, 15.08.) kam aus einem `market_mover`-Impuls. Der Sieger
  hat also eine Strategie gespielt, die sein Charter nicht beschreibt.
- **Bewertungszeitpunkt.** CRYPTOR handelt 24/7, wurde aber wie alle zum
  US-Close bewertet (F121 §3). Das ist eine dokumentierte Setzung und für die
  Vergleichbarkeit richtig. Sie ändert nichts am Bild.

### 3.5 Fairness-Befunde mit Einfluss auf den Vergleich

| Befund | Wen er traf | Wirkung |
|---|---|---|
| F120 U1: alphabetische Research-Auswahl | CRYPTOR, GUARDIAN stark, alle etwas | wenige Kandidaten je Zyklus, überall dieselben Titel |
| F120 U2: aktienfinder liefert nur ISINs | GUARDIAN | Qualitäts-Universum praktisch unkaufbar (2 Trades) |
| F120 U3: `btc_dominance` belegt ~23 % des Prompt-Budgets | alle | weniger Platz für echte Signale |
| F125: Doppel-CLOSE → GPRO-Short ohne Stop (14.09.) | VULTURE | ~4 USD Depotwirkung, kein Rangeffekt; **Invariante #4 verletzt**, behoben |
| F104: Spread-Methodenbruch Mitte August | alle (zeitlich) | Malus nicht über die ganze Saison einheitlich gerechnet |

Formal blieb Invariante #10 gewahrt, weil für alle dieselbe Regel galt. Die
Regeln trafen die Personas aber unterschiedlich hart. Der Wettbewerb hat damit
eher gemessen, wie gut der Research-Pool zur jeweiligen Persona passte, als
welche Anlagephilosophie besser ist.

## 4. Wirtschaftliche Einordnung

| Größe | Wert | Quelle |
|---|---:|---|
| P&L des Feldes (6 × 5 000 USD) | −136 USD (−0,45 %) | Endabrechnung |
| SPY auf dasselbe Kapital | +924 USD (+3,08 %) | Endabrechnung |
| LLM-Kosten im Fenster | **≈ 150–185 USD (Schätzung)** | Stichproben 2,85–3,4 USD/Tag × 54 Tage (F097, F120, phase-5.md); exakter Wert aus `cost_ledger`, s. §7 |
| Ergebnis inkl. LLM-Kosten | ≈ −290 bis −320 USD | Summe der Zeilen 1 und 3 |
| Abstand zu SPY | ≈ 1 200 USD | |

Für einen Live-Gang mit 2 000 € heißt das: Allein die Betriebskosten von
~90–100 USD/Monat, wenn das Gesamtsystem weiterläuft, entsprechen grob 50 % p. a.
des Live-Kapitals. Weil das Paper-Feld laut Plan ohnehin weiterläuft, kostet die
Live-Persona nur wenig zusätzlich, hauptsächlich Review und HITL. Als
Renditeprojekt trägt sich das System trotzdem nicht. Das Projektziel war Lernen
(ARCHITECTURE.md §1, §13.4: „Underperformance ist ein valides Ergebnis"), und
daran gemessen ist das kein Widerspruch.

## 5. Betrieb und Invarianten (Juli–Oktober 2026)

**Was trug:**

- Das Risk-Gate blieb deterministisch. Es gab kein LLM-gesteuertes Risk-Parameter-
  Update und keine `RISK_REJECTED`-Fehlklassifikation als Ursache für Inaktivität
  (F120 §6).
- Die Kosten-Caps griffen nie unberechtigt. Laufend wurden ~3 USD/Tag gegen ein
  Cap von 10 USD verbraucht.
- Die Lineage bis zur Quelle wurde per Probe nachgewiesen (Phase 5, 15.08.).
- Crash-Recovery über den Postgres-Checkpointer wurde nachgewiesen (Phase 4,
  15.08.).
- Die Endabrechnung ist reproduzierbar, weil das Wertungsfenster auf beiden
  Seiten geschlossen ist (F121).

**Was nicht trug, und was daraus wurde:**

| Datum | Vorfall | Ursache | Status |
|---|---|---|---|
| bis 10.07. | HITL-Callback-Listener lief nie als Dienst | fehlender Dauerprozess | F049, behoben |
| 02.–14.09. | GPRO-Short ohne Stop-Loss (Inv. #4) | CLOSE ohne Positionsprüfung, Sweep als transient | F125, behoben 01.10. — **Glattstellung im Paper-Dashboard ist Ralfs Schritt, Stand offen** |
| 18.09. | Settlement-Job nicht gelaufen | Box lief noch auf F119 | am 01.10. rekonstruiert (F121 Nachtrag) |
| 22.09.–01.10. | keine Decisions (LLM-Guthaben leer) | OpenCode Zen und Anthropic-Slot ohne Guthaben | aufgeladen; Kontext-Überlauf danach mit F126 behoben |
| 25.09.–01.10. | aktienfinder-Login defekt | Seiten-Umbau | F125, behoben |
| bis 06.10. | Market-News-Sync tot | Yahoo-Feed 404 | F127, behoben |

Muster: Kein Code-Fehler hat ein Risk-Limit durchbrochen. Das größte Risiko war
der **Betrieb**, also Deploy-Stand der Box, Guthaben und externe Quellen. Für
Live heißt das: Alerting auf Guthaben und Deploy-Stand ist wichtiger als
weitere Strategie-Features.

## 6. Nächster Schritt laut Plan: Phase 6 (Live mit dem Gewinner)

ARCHITECTURE.md §8 P6 und [`docs/dod/phase-6.md`](../dod/phase-6.md) sehen vor:
Gewinner-ADR → Live-Konto (2 000 €) → erste Live-Order mit HITL →
Kill-Switch-Drill → Steuer-Export. Das Paper-Feld läuft weiter.

**Das Hindernis:** Der Gewinner ist CRYPTOR. Alpaca-Krypto ist für DE-Residents
live nicht verfügbar (ADR-0002, Stand 07/2026). Der vorbereitete
`AlpacaLiveAdapter` (F122) hilft CRYPTOR deshalb nicht. Laut ADR-0002 ist der
vorgesehene Weg ein **Kraken-Adapter**. Der ist nicht gebaut, und phase-6.md
schätzt ihn auf eine Größenordnung mehr Arbeit als F122: Order-Pfad,
GTC-Stop-Semantik, Gebühren- und Malus-Modell, Lot-Tracking für §23 EStG.

Damit gibt es drei Wege. Die Wahl ist eine Geld- und Regelfrage, deshalb
entscheidet Ralf (Entwurf: [ADR-0020](../adr/0020-gewinner-entscheidung-und-live-gang.md)):

| Option | Inhalt | Regelkonform? | Aufwand | Einschätzung |
|---|---|---|---|---|
| **A — Plan wörtlich** | CRYPTOR geht live, vorher Kraken-Adapter bauen (oder Alpaca-DE-Krypto erneut prüfen) | ja | hoch (eigenes Feature, mehrere Wochen inkl. Tests/Paper-Smoke gegen Kraken) | sauber, aber viel Aufwand für einen statistisch nicht belastbaren Sieger mit 12 Trades |
| **B — Live vertagen** | Gewinner-ADR schreiben (CRYPTOR), Live aussetzen; erst F120-Fixes, dann eine zweite, saubere Saison; Live nach deren Ergebnis | ja (§4.7 sieht Re-Evaluation vor; Live verschieben bricht keine Regel) | mittel | **meine Empfehlung**: misst endlich die Strategien statt der Research-Auswahl und hält Geld zurück, bis es ein belastbareres Signal gibt |
| **C — Platz 2 live** | CONTRA (Aktien, Alpaca) geht live über den fertigen F122-Pfad | **nein** — Abweichung von §4.7 „vorab fixiert"; bräuchte ADR mit Begründung | niedrig | technisch der schnellste Weg, aber genau das „post hoc"-Auswählen, das §4.7 verhindern soll |

**Warum B:** Option A investiert viel in den Live-Gang eines Ergebnisses, das
§3.3 als Rauschen ausweist und das laut §3.4 überwiegend aus Datenhunger
entstanden ist. Option C bricht die eigene Spielregel. B hält sich an den Plan
(Gewinner-ADR, Feld läuft weiter, Re-Evaluation) und verschiebt nur den
Geld-Schritt, bis die bekannten Messfehler behoben sind.

## 7. Was du konkret tun müsstest

### 7.1 In jedem Fall (Abschluss dokumentieren)

1. **Gewinner-Entscheidung treffen** und den ADR-Entwurf
   [`0020`](../adr/0020-gewinner-entscheidung-und-live-gang.md) von `proposed` auf
   `accepted` setzen, mit gewählter Option. Das ist der erste P6-DoD-Haken.
2. **GPRO-Short bei VULTURE glattstellen** (Buy-to-Cover 146 Stück im
   Alpaca-Paper-Dashboard), falls noch nicht geschehen. Die Position hat keinen
   Stop (Invariante #4, F125 §2).
3. **Zahlen nach dem Stichtag nachziehen** (19.09.–17.10.). Ich hatte keinen
   DB-Zugriff. Auf der Box:
   - Exakte LLM-Kosten im Fenster:
     `SELECT date_trunc('day', ts) AS tag, sum(usd) FROM cost_ledger WHERE ts >= '2026-07-27' AND ts < '2026-09-19' GROUP BY 1 ORDER BY 1;`
     (Spaltennamen ggf. an `src/db/models.py` anpassen)
   - Aktueller Stand des Paper-Feldes: Leaderboard in der UI oder der
     Wochenreport. Die Post-Saison-Zahlen sind wegen des LLM-Ausfalls
     22.09.–01.10. ohnehin nur eingeschränkt aussagekräftig.
4. **Offene Entscheidung 4 aus phase-6.md** (Review für am 18.09. offene
   Positionen) beantworten. Für das Ergebnis ist sie unerheblich: CRYPTOR hält
   nur UNI/USD, und der Abstand zu Platz 2 ist groß.

### 7.2 Wenn Option A (CRYPTOR live)

1. Bei Alpaca prüfen, ob Krypto für DE inzwischen freigeschaltet ist
   (`alpaca.markets/support/what-regions-support-cryptocurrency-trading`, laut
   ADR-0002 vor jeder Adapter-Wahl erneut prüfen). Aus der Arbeitsumgebung war
   die Seite nicht erreichbar.
2. Wenn nicht: Kraken-Konto (Verifizierung, API-Key **nur** mit Trade-Rechten,
   ohne Withdrawal) und Go für das Feature „Kraken-Adapter" an Claude geben.
3. Geld-Entscheidungen aus phase-6.md §5 treffen: EUR/USD-Basis, FX-Kurs für den
   Steuer-Export, Positionsgröße (bei CRYPTOR 20 % ≈ 430 USD je Position, wegen
   fraktionalem Krypto unkritisch).
4. Danach die Schritte aus phase-6.md §4 (Keys nur in die Prod-`.env`,
   Broker-Eintrag, Live-Flag, Live-Portfolio, gitleaks-Historien-Scan).

### 7.3 Wenn Option B (vertagen, empfohlen)

1. ADR-0020 mit Option B annehmen.
2. Go für die F120-Fixes in der Reihenfolge aus F120 §5. Der Universums-Filter
   (Punkt 2) braucht wegen Invariante #10 einen eigenen ADR, die anderen drei
   nicht. Volatilitätsadaptives Sizing (ADR-0018 D.5) gehört in dieselbe Runde.
3. Zweite Saison festlegen: Start- und Enddatum in `config/competition.yaml`,
   Portfolio-Reset wie F090/ADR-0009. Länger als 8 Wochen ist sinnvoll, wenn das
   Signal belastbarer werden soll.
4. Altlasten vor jedem späteren Live-Gang abarbeiten (phase-6.md §6):
   HITL-Timeout end-to-end nachweisen, Digest gegen DB-Query verifizieren,
   P3-Ingestion-Nachweise.

### 7.4 Wenn Option C (CONTRA live)

1. ADR-0020 mit Option C annehmen und die Abweichung von §4.7 ausdrücklich
   begründen.
2. Alpaca-Live-Konto eröffnen, W-8BEN, 2 000 € funden.
3. Positionsgröße entscheiden: CONTRA hat 10 % ≈ 215 USD je Position, und ganze
   Aktien sind Pflicht (F052/F079). Teurere Titel wären live nicht kaufbar.
4. phase-6.md §4 Punkte 2–6, dann erste Live-Order mit HITL und Kill-Switch-Drill.

## 8. Lernertrag (ARCHITECTURE.md §13)

| Erfolgskriterium | Erfüllt? |
|---|---|
| 1. ≥ 8 Wochen autonomer Paper-Wettbewerb, danach Live | Paper ✅ (mit operativen Eingriffen, §5); Live offen |
| 2. Vollständige Data Lineage inkl. verworfener Ideen | ✅ (Lineage-Probe 15.08.) |
| 3. Impuls-Vergleich mit dokumentierten Beispielen | ✅ View vorhanden (F087); eine kuratierte Beispielsammlung im Repo fehlt noch |
| 4. Transparente Performance gegen SPY | ✅ — Ergebnis: alle sechs unter SPY |
| 5. Übertragbares Wissen (LangGraph, MCP, Guardrails, HITL, Kosten-Governance) | ✅ — 127 Feature-Dokumente, 19 ADRs |

Die wichtigsten inhaltlichen Erkenntnisse:

1. **Die Research-Auswahl entscheidet mehr als der Charter.** Was im Prompt
   landet, bestimmt das Verhalten stärker als die Anlagephilosophie (F120).
2. **Paper-Wettbewerbe über 8 Wochen messen Exposition und Glück, keine
   Strategiequalität.** Ein risikoadjustiertes Kriterium belohnt bei kurzer
   Laufzeit vor allem die Personas, die wenig investiert sind.
3. **Die Hypothese „publizierte Tipps haben noch Alpha" (HYPE) wurde in diesem
   Fenster nicht bestätigt**: −0,29 % bei 9 Trades. Bei der Datenlage ist das
   ebenfalls nicht signifikant.
4. **Deterministische Guardrails haben gehalten. Der Betrieb war die
   Schwachstelle.** Deploy-Stand, Guthaben und externe Quellen haben mehr
   Ausfälle verursacht als die Agentenlogik.
