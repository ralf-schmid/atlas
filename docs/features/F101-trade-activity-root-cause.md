# F101 — Warum die Personas seit Wettbewerbsstart kaum handeln

**Status:** Analyse abgeschlossen, Fixes 1–3 umgesetzt (02.08.2026)
**Phase:** 5 (Betriebsbefund, kein neues Feature)
**Auslöser:** Ralf, 02.08.2026 — 5 Orders und 0 offene Positionen in den ersten
6 Wettbewerbstagen (Befund aus [F100](F100-portfolio-history-chart.md) §5).

## 1. Datenbasis der Analyse

Live-DB, Zeitraum 27.07.–02.08.2026, nur aktive (nicht archivierte) Portfolios:

| Persona | buy EXECUTED | buy RISK_REJECTED | hold | reject_idea |
|---|---|---|---|---|
| CHARTIST | 2 | 2 | 2 | 28 |
| CONTRA | 3 | 1 | 0 | 30 |
| VULTURE | 0 | 2 | 19 | 13 |
| HYPE | 0 | 0 | 21 | 13 |
| GUARDIAN | 0 | 0 | 30 | 4 |
| CRYPTOR | 0 | 0 | 34 | 0 |

Research war nie knapp: 1.000–3.400 `research_item`-Zeilen **pro Zyklus**.

## 2. Ursachen (nach Wirkung sortiert)

### U1 — 35 h Totalausfall der LLM-Route (13 Zyklen, ~28 % des Zeitraums)

`cycle`-Zeilen vom 30.07. 06:00 UTC bis 31.07. 17:00 UTC haben Research, aber
**0 `agent_run` und 0 `decision`**. Ursache steht im LiteLLM-Log:

```
litellm.AuthenticationError: AnthropicException -
{"type":"error","error":{"type":"CreditsError","message":"No payment method.
Add a payment method here: https://opencode.ai/workspace/…/billing"}}
```

Die OpenCode-Zen-Route (ADR-0011/F094) hatte kein Zahlungsmittel hinterlegt.
Letzter Fehler 31.07. 17:45 UTC, danach lief es wieder. Das ist dieselbe
Fehlerklasse wie der Anthropic-Guthaben-Ausfall aus Phase 4 — nur beim neuen
Provider. **Kein Code-Fehler, aber ein Monitoring-Loch:** der bestehende Alert
feuert erst nach 2 Fehlschlägen *desselben* Job-Keys, und ein Zyklus, der
sauber durchläuft, aber nichts entscheidet, war überhaupt nicht abgedeckt.

### U2 — Sizing verwarf 27 von 28 CHARTIST-Ideen (`position_too_small_for_whole_share`)

F079 verwirft eine Idee, wenn `conviction × max_position_pct × equity` bei
Ganzaktien-Rundung unter 1 Aktie fällt. Bei CHARTIST (max 10 % = 500 USD) und
Conviction 0,4 sind das 200 USD — jede Aktie über 200 USD ist damit strukturell
unhandelbar, unabhängig von der Signalqualität. 27 Rejects in 6 Tagen.

### U3 — Alle 5 Risk-Rejects waren Rundungsartefakte, kein Regelverstoß

`compute_stop_loss_price` rundet den Stop-Preis auf den Alpaca-Tick — mit
`round()`, also **zur nächsten** Stufe. Damit kippt der Stop in rund der Hälfte
der Fälle über die Policy-Grenze, und das Risk-Gate lehnt anschließend eine
Verletzung ab, die die Rundung selbst erzeugt hat:

| Persona | Titel | Policy | Roh-Stop | gerundet | Ist-Verlust | Verdikt |
|---|---|---|---|---|---|---|
| CONTRA | AUPH | max 15 % | 12,631 | 12,63 | 15,007 % | too_wide |
| CHARTIST | ADSK | Floor 8,2684 % | 214,9364 | 214,94 | 8,2668 % | too_tight |
| CHARTIST | BMRN | Floor 8 % | 54,3766 | 54,38 | 7,994 % | too_tight |
| VULTURE | GCTK | max 25 % | 0,57 | 0,57 | 25,000000000000006 % | too_wide |
| VULTURE | NUWE | max 25 % | 3,36 | 3,36 | 25,00000000000001 % | too_wide |

Die beiden VULTURE-Fälle sind reine IEEE-754-Repräsentation: der Stop trifft die
Grenze exakt, die Division liegt 6e-17 darüber. Der ATR-Zweig des Gates hatte
dafür längst eine 1e-9-Toleranz, der Fixed-Zweig nicht.

### U4 — Fundamentaldaten erreichen die Personas praktisch nie (Haupttreiber der HOLDs)

GUARDIAN und CONTRA begründen ihre HOLDs/Rejects fast wörtlich identisch:
„Keine aktienfinder-Fair-Value-Daten im Pool", „kein fundamentaler Cross-Check
verfügbar". Der Grund ist `_MAX_PROMPT_RESEARCH_ITEMS = 30`: aus 1.000–3.400
Items pro Zyklus wählt `_select_prompt_items` per Round-Robin über ~10
`source_type`s aus — macht **~3 aktienfinder-Items pro Zyklus**, zufällig die
neuesten, praktisch nie zu dem Ticker, den die Persona technisch interessant
findet. Das Suchtool (F045) könnte die Lücke schließen, wird aber offenbar kaum
genutzt. → Optimierungsvorschlag, siehe §4; **nicht** in diesem Feature umgesetzt.

### U5 — CRYPTOR: 34 HOLDs, kein Bug

Durchgängige Begründung: SMA20 > SMA50, aber MACD-Histogramm negativ und
fallend. Das ist charterkonformes Verhalten in einem seitwärts laufenden Markt,
kein Defekt. Beobachten, nicht anfassen.

## 3. Umgesetzte Fixes (02.08.2026)

1. **Richtungsbewusste Tick-Rundung** (`decision_sizing._quantize_to_tick`):
   Fixed-Policy rundet den Stop **auf** (Verlust bleibt ≤ Cap), ATR-Policy
   rundet **ab** (Abstand bleibt ≥ Floor). Der Stop wird dadurch nie lockerer
   als die Policy, höchstens strenger. Alle 5 historischen Rejects hätten damit
   bestanden (nachgerechnet in §5).
2. **1e-9-Toleranz im Fixed-Zweig des Risk-Gates**, symmetrisch zur bereits
   vorhandenen ATR-Toleranz → [ADR-0014](../adr/0014-stop-loss-rounding-and-float-tolerance.md).
3. **Ein-Aktien-Fallback im Sizing:** rundet die Conviction-Größe auf 0 Aktien,
   wird genau eine Aktie gekauft — aber nur, solange sie unter der
   persona-eigenen `max_position_pct`-Grenze und dem Cash bleibt. Sonst weiter
   `reject_idea`. Das Risk-Gate entscheidet danach unverändert.
4. **Silent-Cycle-Alert:** ein Zyklus, der ohne Exception durchläuft, aber keine
   einzige Decision persistiert, löst jetzt sofort einen Telegram-Alert aus
   (jede Persona schreibt immer mindestens ein `hold` — 0 ist nie legitim).

## 3b. Fix 5 — Companion-Items gegen U4 (Ralf, 02.08.2026: „B umsetzen")

`_select_companion_items` lädt nach der Round-Robin-Auswahl gezielt die neuesten
Fundamental-Items zu genau den Symbolen nach, die es in den Prompt geschafft
haben — `aktienfinder_snapshot`, `aktienfinder_screener`, `edgar_filing`, über
das aktuelle Zyklusfenster hinaus (Snapshots kommen in eigenem Takt).

- Dreifach gedeckelt: max. 10 Symbole, max. 2 Items je Symbol, max. 15 gesamt.
  Round-Robin über die Symbole, damit nicht das erste Symbol das Budget frisst.
- Companions werden Teil der zitierbaren `available_ids` — sie stammen aus
  früheren Zyklen, und eine These darf genau auf ihnen aufbauen.
- Identische Regel für alle 6 Personas (Invariante #10): das ist keine
  persona-spezifische Quelle, sondern eine symbolgetriebene Vervollständigung
  des gemeinsamen Pools.
- **Datenlage (Live-Check 02.08.):** 405 Symbole mit technischen Items in den
  letzten Zyklen, 218 mit Fundamentaldaten, **160 Überlappung** — der Mechanismus
  greift. `edgar_filing` trägt kaum bei (nur 68 von 31.145 Filings haben ein
  Symbol im `instruments`-Feld), das Gros kommt aus den aktienfinder-Quellen.
- **Kosten:** ~500 Zeichen je Item × 15 ≈ 2k zusätzliche Input-Tokens je Analyse,
  bei 48 Analysen/Tag ≈ 0,1–0,3 USD/Tag — deutlich unter der 0,5–0,8-USD-Schätzung
  aus §4 und unkritisch gegen das 10-USD-Cap.

## 4. Optionen, die zur Entscheidung standen (erledigt — B ist umgesetzt)

U4 ist der größte verbleibende Hebel, aber jede Variante kostet Tokens und
berührt Invariante #10 (Fairness). Drei Optionen:

- **A — Cap erhöhen (30 → 60 Items):** trivial, wirkt sofort, verdoppelt aber
  den Research-Block im Prompt. Grobe Schätzung auf Basis der aktuellen
  Tageskosten (~2,8 USD bei 48 Analysen): +1,5 bis +2 USD/Tag, also 4–5 USD von
  10 USD Cap. Keine Fairness-Frage (gleiche Regel für alle).
- **B — Companion-Items (Empfehlung):** zusätzlich zu den 30 Round-Robin-Items
  für jedes im Prompt vorkommende Symbol gezielt die neuesten Fundamental-Items
  (`aktienfinder_snapshot`, `edgar_filing`) desselben Symbols nachladen, hart
  gedeckelt (z. B. +15 Items). Trifft genau U4, kostet deutlich weniger als A
  (~+0,5–0,8 USD/Tag) und bleibt eine für alle Personas identische Regel.
- **C — Suchtool erzwingen:** die Persona muss vor einem `hold` mit Begründung
  „keine Daten" einmal `search_research_pool` aufgerufen haben. Billigster
  Token-Einsatz, aber der unzuverlässigste Hebel (Modellverhalten statt Code).

Empfehlung war **B**; Ralf hat B am 02.08.2026 freigegeben (umgesetzt, §3b). A
bleibt als spätere Option offen, falls der Kontext trotzdem zu dünn wirkt.

## 5. Tests

- `tests/orchestrator/test_decision_sizing.py`: Fixed rundet auf (AUPH-Fall,
  12,64 statt 12,63), ATR rundet ab (ADSK-Fall, 214,93 statt 214,94) — beide
  mit Nachrechnung der resultierenden Verlustquote gegen die Policy.
- `tests/risk/test_gate.py`: Grenzfall 0,76/0,57 wird akzeptiert; 25,01 % bleibt
  abgelehnt (die Toleranz weicht die Regel nicht auf). Branch-Coverage
  `src/risk` weiterhin 100 %.
- `tests/orchestrator/test_persona_analysis.py`: Ein-Aktien-Fallback greift
  innerhalb des Caps (ersetzt den F079-Test), bleibt `reject_idea` darüber.
- `tests/orchestrator/test_scheduler.py`: Alert bei 0 Decisions, kein Alert bei
  6 Decisions.
- `tests/orchestrator/test_persona_analysis.py` (Companions): Fundamental-Item
  zum Prompt-Symbol wird gezogen; Nicht-Fundamental-Quellen (`market_news`)
  bleiben draußen; keine Dubletten zu bereits ausgewählten Items; Gesamt-Cap 15
  und Symbol-Cap 10 werden eingehalten; ohne Symbole im Prompt keine Abfrage;
  End-to-End: Companion steht im Prompt-Text und ist zitierbar.
- Gesamtlauf: 841 passed, ruff/mypy grün.

## 6. Live-Verifikation

(nach Deployment)

## 7. Rollback

`git revert` des Commits + Rebuild von `api`/`scheduler`/`telegram-bot`. Kein
Schema-Change, keine Migration, keine Config-Änderung. Die drei Fixes sind
unabhängig voneinander revertierbar.
