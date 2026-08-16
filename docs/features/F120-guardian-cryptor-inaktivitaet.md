# F120 — Warum GUARDIAN und CRYPTOR praktisch nicht handeln

**Status:** Analyse abgeschlossen, **keine Änderung umgesetzt** — die Fixes greifen in
den laufenden Wettbewerb ein, Entscheidung liegt bei Ralf (§5)
**Phase:** 5 (Betriebsbefund, kein neues Feature — wie [F101](F101-trade-activity-root-cause.md))
**Auslöser:** Ralf, 16.08.2026 — beide Personas haben in drei Wettbewerbswochen je
**genau einen** Kauf getätigt (GUARDIAN 1 buy / 102 hold, CRYPTOR 1 buy / 108 hold)

## 1. Kurzfassung

Es liegt **nicht** an den Chartern und nicht am Risk-Gate. Beide Personas werden von
der Research-Auswahl ausgehungert, und zwar aus drei unabhängigen Gründen:

| # | Ursache | Trifft | Wirkung |
|---|---|---|---|
| U1 | Research-Auswahl ist faktisch alphabetisch und liefert jeden Zyklus dieselben ~8 Titel | beide | CRYPTOR sieht Indikatoren zu **1 von 10** eigenen Paaren |
| U2 | aktienfinder liefert **nur ISINs**, für die es keine Kursreihe gibt | GUARDIAN | jeder Kaufversuch stirbt an `insufficient_price_history` |
| U3 | `btc_dominance` verbraucht ~23 % des Prompt-Budgets mit fast identischen Zahlen | beide | 7 von 30 Slots für eine Kennzahl |

## 2. U1 — die Auswahl sortiert nicht, sie schneidet alphabetisch ab

`_select_prompt_items` (F047) verteilt ein Budget von **30 Items** per Round-Robin
über die vorhandenen `source_type`-Buckets und sortiert innerhalb jedes Buckets
`published_at desc`. Der Gedanke ist richtig; in der Praxis sortiert er nichts:

```
Zyklus 16.08. 06:00, source_type technical_indicator:
  362 Items — 1 (ein) distinkter published_at-Wert
```

Alle Zeilen eines Ingestion-Laufs tragen denselben Zeitstempel. Pythons `list.sort`
ist stabil, also bleibt die Reihenfolge stehen, in der die Zeilen aus der DB kommen —
und `select(ResearchItem).where(cycle_id == ...)` (persona_analysis.py:169) hat **kein
`ORDER BY`**. Das Ergebnis ist Heap-Reihenfolge, und die ist Einfüge-Reihenfolge, und
die ist alphabetisch:

```
AADX, AAOI, AAPL, AAVE/USD, ABAT, ABCL, ABEV, ABG, ABNB, ABSI, ABUS, ACAD, …
```

Bei ~5 Buckets fallen etwa 6–8 Slots auf `technical_indicator`. Jede Persona sieht
also **jeden Zyklus dieselben acht Titel am Anfang des Alphabets** — 362 Symbole
existieren, ~8 werden je gezeigt. Dass GUARDIAN in seinen Hold-Thesen wörtlich
`AADX/AAOI/ABCL` und `ABNB` nennt (Positionen 1, 2, 6 und 9 dieser Liste), ist der
direkte Beleg.

**Für CRYPTOR ist das fatal.** Die zehn Paare seines Universums (F115) liegen im
alphabetisch sortierten Bucket verstreut zwischen 362 Aktien:

| Paar | Position im Bucket |
|---|---:|
| AAVE/USD | **4** ✅ |
| BTC/USD | 169 |
| ETH/USD | 215 |
| LINK/USD | 261 |
| SOL/USD | 328 |
| XRP/USD | 357 |

Nur AAVE/USD schafft es über die Kante. CRYPTOR bekommt Zyklus für Zyklus technische
Indikatoren zu **genau einem** seiner zehn Paare und hält folgerichtig. Die einzigen
Krypto-Impulse, die sonst durchkommen, sind `market_mover` (Alpaca-Tagesgewinner) —
und genau daraus stammt auch sein einziger Kauf (LINK/USD am 15.08.).

**Fairness (Invariante #10) ist formal gewahrt** — die Regel ist für alle Personas
identisch. Sie trifft nur die Personas unterschiedlich hart, je nachdem, wo ihr
Universum im Alphabet liegt. Das ist kein Informationsvorsprung, aber es verzerrt den
Vergleich, und für die Gewinner-Kür nach §4.7 ist das dasselbe Problem.

## 3. U2 — GUARDIANs beste Quelle liefert Instrumente, die er nicht kaufen kann

`aktienfinder_snapshot` enthält exakt sechs Symbole, alle als **ISIN**:

```
DE0007164600, DE0008430026, US0378331005, US4781601046, US5949181045, US7427181091
```

Das ist genau das Quality-/Dividenden-Universum, für das GUARDIAN gebaut ist. Und für
keines davon existiert eine Kursreihe:

```
market_bar für AAPL          : 171 Zeilen
market_bar für US0378331005  :   0 Zeilen
```

`persona_analysis.py:502` holt `get_latest_price(session, parsed.instrument)`; ohne
Kurs gibt es keinen Stop-Loss, und die Decision wird mit
`rejection_reason="insufficient_price_history"` verworfen (Zeile 523). Das ist
**korrektes Verhalten** — Invariante #4 verlangt einen Stop-Loss, und ohne Kurs kann
es keinen geben. Der Fehler liegt davor: die Recherche bietet etwas an, das der
Handelspfad nicht annehmen kann.

Live nachweisbar an GUARDIANs Ablehnungen: die Thesen argumentieren sauber
(„Fair-Value-Abschlag 44 %, klar über meiner 15 %-Mindestschwelle") und scheitern
dann an der Kursreihe. Der einzige erfolgreiche Kauf, `ACIW` am 15.08., kam aus
`aktienfinder_screener` — der liefert **Ticker** statt ISINs.

Pikant: `US0378331005` ist Apple. `AAPL` steht im selben Prompt, mit 171 Kurstagen.
Die beiden werden nirgends zusammengeführt. F107 (Instrument-Namensabgleich) deckt
Blog, Zeitschriften und Marktnews ab, aber nicht ISIN → Ticker im Entscheidungspfad.

## 4. U3 — sieben Slots für eine Zahl

Im Zyklus 16.08. 06:00 sind **7 der 30 Prompt-Items** BTC-Dominanz-Messungen:

```
56.173 %, 56.181 %, 56.167 %, 56.160 %, 56.166 %, 56.163 %, 56.167 %
```

Sie unterscheiden sich in der dritten Nachkommastelle. Der Round-Robin gibt jedem
`source_type` denselben Anteil, unabhängig davon, wie viel Information darin steckt;
`btc_dominance` wird stündlich ingested und hat pro Zyklus ~12 nahezu identische
Zeilen. 23 % des Budgets für eine Kennzahl, die eine Zeile bräuchte.

## 5. Was ich vorschlagen würde — und warum ich es nicht einfach gemacht habe

Jeder dieser Fixes ändert, was **alle sechs** Personas sehen, mitten im laufenden
8-Wochen-Wettbewerb. Das ist kein Charter-Eingriff (kein `charter_version`-Bump
nötig), aber es verschiebt die Vergleichsbasis zwischen Woche 3 und Woche 8. Ob das
akzeptabel ist oder ob der Lauf lieber sauber zu Ende geht, ist Ralfs Entscheidung.

Nach erwartetem Nutzen sortiert:

1. **Deterministische, sinnvolle Reihenfolge im Bucket** statt Heap-Ordnung. Ein
   `ORDER BY` allein reicht nicht — bei identischen Zeitstempeln braucht es ein
   fachliches Zweitkriterium (z. B. Auffälligkeit/Rang statt Symbolname) oder eine
   deterministische Rotation über die Zyklen, damit über die Zeit das ganze Universum
   drankommt. Der größte Hebel, für beide Personas.
2. **Pro Persona ein Universums-Filter vor der Auswahl.** CRYPTOR soll Krypto sehen,
   GUARDIAN Large Caps. Das `universe_screen` in `config/personas/*.yaml` existiert
   bereits, wird aber von keinem Live-Code gelesen. **Achtung:** das berührt
   Invariante #10 unmittelbar — ein persona-spezifischer Filter auf einen geteilten
   Pool ist genau die Grenze zwischen „gleiche Information, andere Brille" und
   „andere Information". Braucht einen ADR, bevor irgendwer Code anfasst.
3. **ISIN → Ticker auflösen**, bevor eine Decision entsteht (F107 erweitern). Ohne
   das bleibt GUARDIANs stärkste Quelle unbenutzbar.
4. **`btc_dominance` je Zyklus auf eine Zeile eindampfen** (letzter Wert + Delta).
   Kleiner Aufwand, gibt sofort ~6 Slots frei.

## 6. Was nicht die Ursache ist

Der Vollständigkeit halber geprüft und ausgeschlossen:

- **Risk-Gate:** GUARDIAN und CRYPTOR haben in der Wettbewerbssaison **keine einzige**
  `RISK_REJECTED`-Decision. Alle 110 Nicht-Kauf-Entscheidungen sind `RECORDED`
  (hold/reject_idea), also LLM-Entscheidungen, keine Gate-Blocks.
- **Charter zu streng:** GUARDIANs Schwelle ist ein Fair-Value-Abschlag von 15 %; die
  abgelehnten Kandidaten lagen bei 19–44 %. Er wollte kaufen.
- **LLM-Ausfall:** die 35-h-Lücke aus F101 §U1 liegt vor dem Betrachtungszeitraum;
  `agent_run`-Zeilen sind über die drei Wochen durchgehend vorhanden.
- **Kosten-Cap:** ~3 USD/Tag gegen 10 USD Cap, nie gegriffen.
