# Phase 6 — Live (Gewinner): Planung & Definition of Done

Checkliste aus ARCHITECTURE.md §8. **Status:** Planung erstellt 05.09.2026, Phase noch
nicht gestartet. Voraussetzung ist der Abschluss des 8-Wochen-Wettbewerbs am
**Fr 18.09.2026** (`config/competition.yaml`) und der Gewinner-Report nach §4.7.

## DoD-Checkliste

- [ ] Gewinner-Report (8 Wochen, alle 5 Kriterien) erzeugt; Entscheidung als ADR
- [ ] Live-Keys ausschließlich in der Prod-Umgebung; gitleaks-Scan über gesamte
      Repo-Historie sauber
- [ ] Erste Live-Order nach Telegram-Approval ausgeführt; GTC-Stop beim Broker
      verifiziert (Alpaca-Dashboard)
- [ ] Kill-Switch-Drill: Live-Circuit-Breaker simuliert ausgelöst und Verhalten
      dokumentiert
- [ ] Steuer-Export (Trades-CSV für Anlage KAP) generierbar

## Ist-Stand bei Planungserstellung (05.09.2026)

Code-geprüft, nicht aus dem Gedächtnis. Was P6 vorfindet:

- **Live-Adapter fehlt vollständig.** `src/broker/` enthält `alpaca_paper.py`,
  `internal_ledger.py`, `ledger_store.py`, `market_data.py`, `protocol.py`,
  `registry.py` — **kein `alpaca_live.py`**. Der `BrokerAdapter`-Protocol steht, der
  Live-Adapter ist Neubau gegen dieses Protocol. Coverage-Gate beachten:
  `src/broker` ≥ 90 % Lines, mypy strict.
- **Steuer-Export existiert nicht.** Kein einziges Modul unter `src/` enthält
  CSV-/Export-Logik. Das ist Neubau, nicht Anpassung. Fachliche Vorklärung nötig
  (Ralf, Geld-Thema): welche Felder die Anlage KAP braucht, Umrechnungskurs-Logik
  USD → EUR, Behandlung von Teilausführungen.
- **Kill-Switch-Drill hat einen Vorbefund.** Der Circuit Breaker
  (`src/risk/gate.py:39-47`) ist zustandslos: er rechnet den Drawdown bei jedem Check
  neu und gibt BUYs automatisch wieder frei, sobald die Equity sich erholt.
  CLAUDE.md Invariante #8 verlangt „Reset nur manuell". Der Drill muss das mit
  abdecken; die Entscheidung, ob der Breaker vor Live einen persistierten Zustand
  bekommt, liegt bei Ralf (Details in `phase-5.md`, Zwischenstand 05.09., Befund 3).
- **HITL für Live steht korrekt.** `config/hitl.yaml`: `paper: false`, `live: true`.
  Bleibt so — Invariante #5, jede Änderung ausschließlich über Config bzw.
  `/hitl`-Kommando, nie im Code.
- **Live-Credentials existieren nirgends** — so gewollt (Invariante #5). Weder
  `.env.example` noch Config enthalten Live-Werte oder Fallback-Defaults.
- **Risk-Gate ist mandantenfähig genug**, aber die Live-Guardrails sind noch nicht
  parametriert: `config/risk.yaml` ist auf 5.000 USD Paper-Depots ausgelegt, live
  sind es 2.000 €. Positionsgrößen-, Trade- und Verlustlimits müssen für das
  Live-Depot neu gesetzt werden (Geld-Thema → Ralf entscheidet, nie stillschweigend
  übernehmen).

## Manuelle Ralf-Aufgaben (Blocker, nicht durch Code ersetzbar)

1. Alpaca-Live-Account anlegen und mit 2.000 € funden.
2. Live-API-Keys erzeugen und **ausschließlich** in die Prod-Umgebung einbringen
   (Environment/Docker Secrets, nie ins Repo).
3. Gewinner-Entscheidung bestätigen, sobald der Report vorliegt (der Report schlägt
   vor, die Kür ist Ralfs).

## Vorgeschlagene Reihenfolge

Nummerierung fortlaufend ab F121; jede Umsetzung nach ARCHITECTURE.md §10 mit eigenem
`docs/features/FNNN-<slug>.md`.

**Block 0 — vor dem Stichtag 18.09. (greift nicht in die Personas ein):**

1. **F121 — Stichtags-Bewertung als Snapshot:** am 18.09. nach Handelsschluss die
   Schlusskurse aller offenen Positionen und die daraus abgeleiteten Depotwerte
   persistieren, damit die Endabrechnung reproduzierbar bleibt. Setzt Ralfs Ruling
   vom 16.08. um (`phase-5.md`, offene Entscheidung 4). **Terminkritisch.**
2. **ADR — Wertbarkeitsschwelle für §4.7:** Mindest-Trade-Zahl, unterhalb derer eine
   Persona nicht gerankt, sondern als „nicht wertbar" ausgewiesen wird. Muss **vor**
   dem Stichtag entschieden sein (Begründung: `phase-5.md`, Befund 1).

**Block 1 — Auswertung (ab 21.09.):**

3. **F122 — Gewinner-Report:** §4.7-Auswertung über die volle Saison auf Basis von
   `competition_score.py`, inkl. statistischem Disclaimer und Ausweisung der nicht
   wertbaren Personas. Ergebnis + Kür als ADR.

**Block 2 — Live-Vorbereitung (parallel möglich):**

4. **F123 — Live-Adapter `alpaca_live`:** gegen das bestehende `BrokerAdapter`-Protocol,
   `mode`-Flag durchgängig, Live-Guardrails aus eigener Config-Ebene.
5. **F124 — Steuer-Export:** Trades-CSV für Anlage KAP, USD → EUR mit dokumentierter
   Kursquelle.
6. **F125 — Kill-Switch-Drill + Breaker-Zustand:** Drill dokumentiert, Entscheidung zur
   Persistierung des `sell_only`-Zustands umgesetzt oder begründet verworfen.
7. **gitleaks über die gesamte Historie** (nicht nur Diff-Scan wie in CI) — reiner
   Prüfschritt, Nachweis ins DoD.

**Block 3 — Livegang:**

8. Erste Live-Order nach Telegram-Approval, GTC-Stop im Alpaca-Dashboard verifiziert,
   Screenshot ins DoD.

## Realistische Terminlage

Wettbewerbsende 18.09., Gewinner-Report ab 21.09. Blocks 2 und 3 sind erfahrungsgemäß
zwei bis drei Wochen Arbeit, nicht ein Wochenende — erste Live-Order damit frühestens
Anfang Oktober 2026. Das Paper-Feld läuft nach der Kür weiter (§4.7, §7.3), der
Livegang blockiert es nicht.
