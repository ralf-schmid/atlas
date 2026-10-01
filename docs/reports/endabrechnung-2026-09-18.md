# Endabrechnung — ATLAS-Wettbewerb 27.07.2026 bis 18.09.2026

Erzeugt aus der Wettbewerbs-DB, ohne LLM: `src/metrics/final_report.py` (F121).
Grundlage der Gewinner-Entscheidung nach ARCHITECTURE.md §4.7 — der ADR zur
Entscheidung referenziert diesen Report.

| | |
|---|---|
| Wertungsfenster | 27.07.2026 – 18.09.2026 (54 Tage mit Snapshot) |
| Bewertungsschnitt | 18.09.2026 23:59 UTC |
| Startkapital je Persona | 5 000 USD |
| Gewertete Kriterien | Risiko-adj. Rendite (Sortino) 40 %, Rendite nach Kosten 25 %, Max Drawdown (invers) 15 %, Thesen-Qualität 10 %, Operative Zuverlässigkeit 10 % |
| Sieger nach §4.7 | CRYPTOR (Score 0,909) |

## 1. Rangliste (§4.7, gewichtet)

| Rang | Persona | Score | Sortino | Rendite n. Kosten | Max DD | Thesen | Zuverl. | Trades |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | CRYPTOR | 0,909 | 2,30 | +1,28 % | 2,22 % | 50,00 % (8) | 100,00 % | 12 |
| 2 | CONTRA | 0,547 | 0,50 | +0,48 % | 3,14 % | 40,00 % (20) | 78,54 % | 20 |
| 3 | HYPE | 0,501 | -2,11 | -0,29 % | 0,53 % | 22,22 % (9) | 99,76 % | 9 |
| 4 | GUARDIAN | 0,326 | -3,13 | -0,78 % | 0,92 % | 0,00 % (1) | 100,00 % | 2 |
| 5 | VULTURE | 0,253 | -1,88 | -1,84 % | 3,28 % | 28,57 % (28) | 96,47 % | 33 |
| 6 | CHARTIST | 0,201 | -2,31 | -2,09 % | 3,32 % | 28,57 % (14) | 96,49 % | 17 |

Gewichte laut §4.7: Risiko-adj. Rendite (Sortino) 40 %, Rendite nach Kosten 25 %, Max Drawdown (invers) 15 %, Thesen-Qualität 10 %, Operative Zuverlässigkeit 10 %.

## 2. Schlussbewertung zum Stichtag

Offene Positionen gehen mit ihrem Marktwert zum Stichtag ein und werden nicht
zwangsliquidiert (Ralfs Entscheidung, 16.08.2026).

| Persona | Depotwert | davon Cash | offene Positionen | Bewertung (UTC) |
|---|---:|---:|---:|---|
| CHARTIST | 4 897,28 $ | 3 863,92 $ | 3 | 18.09.2026 20:35 |
| CONTRA | 5 025,65 $ | 1 769,60 $ | 11 | 18.09.2026 20:35 |
| CRYPTOR | 5 076,18 $ | 4 708,13 $ | 1 | 18.09.2026 20:35 |
| GUARDIAN | 4 961,20 $ | 4 214,86 $ | 2 | 18.09.2026 20:35 |
| HYPE | 4 985,77 $ | 4 810,99 $ | 1 | 18.09.2026 20:35 |
| VULTURE | 4 917,85 $ | 4 649,81 $ | 10 | 18.09.2026 20:35 |


**CHARTIST — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
| AAPL | 1 | 336,13 $ | -0,11 $ |
| ADBE | 2 | 497,84 $ | -19,44 $ |
| ANET | 1 | 199,39 $ | -0,39 $ |

**CONTRA — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
| AAPL | 1,0251 | 344,57 $ | 34,62 $ |
| ABEV | 71,5523 | 210,36 $ | 11,81 $ |
| ACIW | 5,3215 | 267,51 $ | -9,07 $ |
| AHCO | 53,2001 | 303,77 $ | 7,71 $ |
| AKAM | 2,5003 | 261,33 $ | -15,08 $ |
| ALNY | 1,3437 | 321,90 $ | 28,26 $ |
| APP | 1,0006 | 308,25 $ | -7,46 $ |
| ATS | 15,8154 | 305,87 $ | -24,81 $ |
| BRBR | 26,7823 | 240,51 $ | -50,62 $ |
| META | 0,5561 | 370,20 $ | 60,70 $ |
| TSLA | 0,8834 | 321,78 $ | 45,58 $ |

**CRYPTOR — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
| UNI/USD | 40,7951 | 368,05 $ | 16,71 $ |

**GUARDIAN — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
| ACEL | 35 | 394,45 $ | -17,85 $ |
| ACIW | 7 | 351,89 $ | -20,93 $ |

**HYPE — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
| NVDA | 0,7863 | 174,78 $ | -6,16 $ |

**VULTURE — offene Positionen am Stichtag**

| Instrument | Stück | Marktwert | unrealisiert |
|---|---:|---:|---:|
| ABAT | 14 | 30,52 $ | -8,54 $ |
| CRDL | 22 | 41,25 $ | -7,59 $ |
| GDRX | 14 | 47,32 $ | -4,46 $ |
| GPRO | -146 | -191,26 $ | 4,38 $ |
| INDI | 11 | 33,77 $ | -1,43 $ |
| KEEL | 20 | 80,20 $ | 9,78 $ |
| RXRX | 15 | 57,45 $ | 7,35 $ |
| SABR | 28 | 63,28 $ | 9,52 $ |
| TSLG | 11 | 52,47 $ | -3,18 $ |
| VZLA | 13 | 53,04 $ | 1,56 $ |

## 3. Benchmark

SPY Buy-and-Hold über dasselbe Fenster: +3,08 %.

## 4. Vorbehalt (§4.7, unverändert)

8 Wochen ≈ 40 Handelstage reichen nicht für eine signifikante
Strategie-Unterscheidung — der Sieger ist mit hoher Wahrscheinlichkeit Regime- und
Rausch-Glück. Das Paper-Feld läuft nach der Kür weiter, die Live-Persona wird
quartalsweise gegen das Feld re-evaluiert.
