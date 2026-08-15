# F111 — Deterministisches Backtest-Modul im Review-Zweig

Status: **beauftragt, noch nicht begonnen**
Datum der Beauftragung: 2026-08-15 (Ralf)
Phase: 5+ (Erweiterung — ARCHITECTURE.md §8 kennt Backtesting in keiner Phase)
Grundlage: [ADR-0015](../adr/0015-alpaca-agent-research-tooling.md), dort als
„geparkt" geführt und am 15.08.2026 mit dem ADR-Accept freigegeben

> **Startbefehl für die neue Session: „implementiere das Backtest-Modul".**
> Dieses Dokument ist der vollständige Auftrag. Es ist bewusst *kein* fertiger
> Entwurf: Zieldefinition, Leitplanken und der Ist-Stand des Codes stehen hier,
> die Lösung entsteht im Feature-Prozess (§10) — inklusive Testdefinition **vor**
> der Implementierung. Die offenen Entscheidungen in §5 sind vor dem ersten
> Codezeichen mit Ralf zu klären.

## 1. Auftrag und Herkunft

ADR-0015 hat die Alpaca-Backtest-Skill bewertet und drei Wege abgelehnt: die
Skill im Persona-Zyklus (Option A), den MCP-Server (B) und die CLI (C). Der Grund
war nie „Backtesting ist schlecht", sondern **wo** es stattfinden sollte. Wörtlich
aus dem ADR:

> Falls Backtesting je gewünscht wird, gehört es als **deterministisches
> Code-Modul in den Review-Zweig (P5+)**, nicht in den Persona-Pfad — sonst
> entstehen Kosten- und Fairness-Asymmetrien.

Genau das ist jetzt beauftragt.

**Zweck aus Projektsicht:** ATLAS erkennt heute ausschließlich über den laufenden
Wettbewerb, ob eine Persona-Strategie taugt — acht Wochen, ~40 Handelstage, was
laut §4.7 selbst zu wenig ist, um Können von Zufall zu trennen. Ein Backtest im
Review-Zweig soll eine **zweite, unabhängige Erkenntnisquelle** liefern: hätte die
Regelmenge einer Persona über einen längeren historischen Zeitraum getragen? Das
Ergebnis ist ein Diagnose-Artefakt für Ralf und für die Meta-Review — **kein
Eingabewert für Handelsentscheidungen**.

## 2. Nicht verhandelbare Leitplanken

Diese Punkte sind keine Designvorschläge, sondern Bedingungen. Bei Konflikt:
nachfragen, nicht aufweichen.

1. **Kein LLM im Rechenweg.** Returns, Drawdown, Sortino, Fills, Slippage — alles
   Code. CLAUDE.md verbietet ausdrücklich, Finanz-Kennzahlen vom LLM „ausrechnen"
   zu lassen. Ein LLM darf höchstens ein fertiges Ergebnis *kommentieren*, so wie
   der Review-Agent ein fertig berechnetes Ergebnis beurteilt.
2. **Kein Zugriff aus dem Persona-Pfad** (Invariante #2 und #10). Keine Persona
   darf einen Backtest anstoßen oder sein Ergebnis als Research-Item sehen —
   sonst hat die eine Persona einen Vorteil, den die andere nicht hat, und die
   Kosten je Zyklus werden unvergleichbar. Das Modul läuft im Review-Zweig oder
   on demand, nie in `persona_analysis`.
3. **Keine Order-Fähigkeit.** Das Modul liest historische Daten und schreibt
   Ergebnisse. Es fasst `BrokerAdapter` nicht an.
4. **Keine neuen Credentials, kein neues Deployment-Artefakt.** Datenbasis ist
   `market_bar` in der eigenen DB (siehe §3). Kein CLI-Binary, kein MCP-Server,
   keine Go-Toolchain — das ist die ausdrückliche Absage aus ADR-0015.
5. **Reproduzierbarkeit ist Teil des Features, nicht Kür.** Ein Backtest, dessen
   Zahlen sich beim zweiten Lauf ändern, ist wertlos. Dazu §4.
6. **Kosten-Caps gelten unverändert.** Falls doch ein LLM-Kommentar dazukommt,
   läuft er über `guarded_complete` und landet im `cost_ledger`.

## 3. Ist-Stand — was schon da ist und wiederverwendet gehört

Nicht neu bauen, was existiert:

| Baustein | Ort | Anmerkung |
|---|---|---|
| Tages-Bars | Tabelle `market_bar` | **Split-adjustiert seit F103**, Historie ab 2026-02-17 für die ~375 Universums-Symbole. Vor F103 lagen Rohkurse drin — für ältere Zeiträume gibt es schlicht keine Daten. |
| Kennzahlen | `src/metrics/performance.py` | `sortino_ratio`, `max_drawdown`, `simple_return`, `adjusted_return`, `daily_returns`, `trade_count`, `slippage_malus_sum`, `spread_method_split` |
| Wettbewerbs-Score | `src/metrics/competition_score.py` | die §4.7-Kriterien samt Gewichten — ein Backtest sollte in derselben Sprache sprechen |
| Slippage-Modell | `src/review/slippage.py` | `compute_slippage_malus`, Parameter in `config/review.yaml`. Ein Backtest ohne Slippage-/Kostenmodell lügt. |
| Indikatoren | `src/orchestrator/indicators.py` | SMA/RSI/MACD/Bollinger/Crossover, dazu `detect_price_level_break` (F108) — Reihen mit Niveauwechsel taugen auch im Backtest nicht |
| Persona-Regeln | `config/personas/*.yaml` | Charter, Universums-Screen, Risk-Parameter je Persona |
| Risk-Gate | `src/risk/` | deterministisch, zweistufig — ein ehrlicher Backtest muss dieselben Grenzen anwenden wie der Live-Pfad |
| Review-Zweig | `src/review/agent.py`, `meta_agent.py` | Muster für „Code rechnet, LLM urteilt", Sweep-Struktur, Idempotenz über „hat schon ein Ergebnis?" |

**Datenlage ehrlich einschätzen, bevor gebaut wird:** ~6 Monate Tagesbars für ein
Screener-getriebenes Universum sind für belastbare Aussagen wenig. Das Feature
muss dazu eine Position beziehen (§5, Punkt 4) — lieber ein Modul, das seine
eigene statistische Aussagekraft ausweist, als eine Zahl, die mehr verspricht als
sie kann.

## 4. Artefakt-Kontrakt (aus ADR-0015 übernommen)

Die Alpaca-Skill hat einen brauchbaren Reproduzierbarkeits-Kontrakt, den das ADR
ausdrücklich „als Vorlage geparkt" hat. Er ist hier die Messlatte:

- **`strategy_spec`** — was wurde getestet, als Daten und nicht als Prosa
- **`config`** — Parameter des Laufs (Zeitraum, Universum, Kosten-/Slippage-Modell)
- **Data-Fingerprint** — welcher Datenstand lag zugrunde (Zeilenzahl, Zeitraum,
  Prüfsumme o. Ä.), damit ein späterer Lauf erkennt, dass sich die Basis geändert
  hat
- **Run-Lineage** — was wurde gegenüber dem Vorlauf geändert
- **Pflicht-Disclaimer** — dass ein Backtest keine Aussage über die Zukunft ist;
  im selben Geist wie der §4.7-Hinweis im Wochenreport

Das passt bewusst zu der Lineage-Disziplin, die ATLAS für Decisions schon hat
(`input_research_ids`, `rejection_reason`, Reviews).

## 5. Zu klären, bevor Code entsteht

Alles Geld- bzw. Wettbewerbsnahes — nach CLAUDE.md fragen statt raten:

1. **Was genau wird backtestet?** Die Charter einer Persona als Regelmenge
   (dann braucht es eine maschinenlesbare Fassung der heute LLM-interpretierten
   Charter), oder abstrakte Regelsätze unabhängig von den Personas? Das ist die
   zentrale Weichenstellung — die erste Variante ist wertvoller und deutlich
   aufwendiger, weil die Persona-Entscheidung heute ein LLM-Urteil ist und kein
   Regelbaum.
2. **Wer stößt es an?** Sonntags im Review-Wochenlauf, on demand per
   Telegram-Kommando, oder als Skript von Hand?
3. **Wohin mit dem Ergebnis?** Neue Tabelle (dann Alembic-Migration), Artefakt im
   Dateisystem, oder beides? Und: taucht es in der UI auf?
4. **Welcher Anspruch bei der Aussagekraft?** Mindest-Zeitraum, Umgang mit
   Survivorship Bias (das Universum kommt aus einem *heutigen* Screener),
   Look-ahead-Vermeidung. Wenn die Datenlage für die gewünschte Aussage nicht
   reicht, ist das ein Ergebnis und kein Grund, die Zahl trotzdem zu liefern.
5. **LLM-Kommentar ja/nein?** Ein Sonnet-Kommentar auf das fertige Zahlenwerk
   wäre konsistent mit dem Review-Muster, kostet aber je Lauf und braucht ein
   Budget im `cost_ledger`.

## 6. Vorgehen (ARCHITECTURE.md §10, verbindlich)

1. Offene Punkte aus §5 mit Ralf klären.
2. Dieses Dokument zur vollständigen Feature-Doku ausbauen: Zieldefinition →
   kritische Betrachtung (Invarianten, Kosten, Fairness) → **Testdefinition vor
   der Umsetzung** → Implementierung → kompletter Testdurchlauf → Livesetzung mit
   Verifikation → dokumentierter Rollback-Pfad (Config-Flag bevorzugt).
3. Tests parallel zum Code. Für die Rechenkerne gilt der übliche Anspruch:
   Kennzahlen gegen von Hand nachgerechnete Referenzwerte, nicht gegen sich
   selbst.
4. ADR nur, falls beim Bauen von ADR-0015 abgewichen wird.

**Praktisches für den Deploy** (steht so auch in `docs/deployment.md`, hier zur
Sicherheit): Tests brauchen `DATABASE_URL` auf den lokalen Test-Postgres, sonst
werden ~180 DB-Tests still übersprungen. Auf die Box geht es per `rsync`, danach
`sudo docker compose build api scheduler` + `up -d` — `config/` ist ins Image
gebacken, eine reine Config-Änderung braucht also trotzdem einen Rebuild.

## 7. Was dieses Feature ausdrücklich nicht ist

- Kein Weg, doch noch die Alpaca-CLI, den MCP-Server oder die Skill einzuführen
  (ADR-0015, Optionen A–C bleiben abgelehnt).
- Kein Eingriff in den laufenden Wettbewerb. Der Backtest ändert keine Charter,
  keine Risk-Parameter und keine Decision. Wenn er zeigt, dass eine Persona-Regel
  schlecht ist, ist das eine Erkenntnis für Ralf — eine Charter-Änderung wäre ein
  eigener Vorgang mit `charter_version`-Bump und ADR.
- Kein Ersatz für den Wettbewerb als Erkenntnisweg. ADR-0015 nennt ihn
  ausdrücklich „den einzigen Erkenntnisweg, so ist das Projekt angelegt" — F111
  stellt eine zweite Quelle daneben, nicht davor.
