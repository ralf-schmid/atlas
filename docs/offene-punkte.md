# Offene Punkte für Ralf

Was auf der Box passieren muss, damit die fertig entwickelten Features auch
wirken. Stand: 2026-08-11. Reihenfolge = empfohlene Abarbeitung.

Alles hier ist **Betrieb**, nicht Entwicklung: Code, Tests und Doku sind fertig
und liegen auf `claude/alpaca-research-api-h1kcg2`. Erledigte Punkte abhaken und
den Nachweis im jeweiligen Feature-Dokument (§5) nachtragen — nicht hier.

## 1. Deploy F103–F105 (ein Durchgang)

Alle drei hängen an denselben zwei Containern; ein Deploy reicht.

- [ ] `alembic upgrade head` — zwei Migrationen: `f7a1c2d3e4b5`
      (`order_record.spread_bps`, F104) und `c9e8d7f6a5b4` (`market_mover` +
      `market_news_headline.instruments`, F105). Beide nur `add_column`/
      `create_table`, kein Rewrite, kein Backfill.
- [ ] `docker compose build api scheduler` + `up -d api scheduler`.

## 2. F103 — Split-adjustierte Markt-Bars

- [ ] **Einmaliger Re-Sync mit `lookback_days=180`** direkt nach dem Deploy.
      Ohne ihn wird nur das rollierende 90-Tage-Fenster auf die adjustierte Basis
      umgeschrieben; die Historie ab 13.04.2026 (F048-Backfill) behält Rohbasis,
      und an der Nahtstelle steht Mischbestand. Fertiges Snippet inkl. korrekt
      aufgelöstem Symbol-Universum: `docs/features/F103-split-adjusted-market-bars.md` §5.
- [ ] **Verifikation:** ein Symbol mit Split im Fenster vorher/nachher
      vergleichen; `compute_indicator_snapshot` für AAPL/MSFT/SPY gegen die echte
      DB laufen lassen und die Werte in F103 §5 notieren.

## 3. F104 — Gemessener Bid/Ask-Spread

- [ ] **Nach dem ersten neuen Trade:** die frische `order_record`-Zeile auf
      `spread_bps` prüfen und den Wert gegen den Alpaca-Dashboard-Spread des
      Symbols plausibilisieren; danach das zugehörige Review auf einen Malus > 0
      kontrollieren. Nachweis in F104 §5.
- [ ] **Entscheiden, ob der Methodenbruch in den Wochenreport-Kommentar geht.**
      Orders vor dem Deploy haben keinen gemessenen Spread (historische Quotes
      sind nicht rekonstruierbar) und behalten die Pauschale. Der Schnitt verläuft
      zeitlich, nicht persona-bezogen — Fairness (#10) bleibt gewahrt, aber die
      Malus-Zahl über die Wettbewerbsdauer ist nicht mit einer einheitlichen
      Methode gerechnet. Hintergrund: F104 §2.

## 4. F105 — Alpaca News + Screener

- [ ] **Entitlement prüfen (der Punkt mit dem echten Risiko).** Der
      Marktdaten-Key hat nur IEX-Entitlement. Ob News- und Screener-Endpoints auf
      dieser Stufe freigeschaltet sind, ließ sich ohne Credentials nicht
      verifizieren. Ersten Lauf beobachten: bei fehlendem Entitlement kommt ein
      Alpaca-`APIError`, nach zwei Fehlläufen ein Telegram-Alert — kein anderer
      Job und kein Zyklus leidet darunter. Falls nur eine der beiden Quellen
      entitled ist, den anderen Eintrag auf `enabled: false` setzen
      (`config/ingestion.yaml`, Sektion `schedule`).
- [ ] **Nach dem ersten Lauf:** Zeilenzahl in `market_news_headline` mit
      `guid LIKE 'alpaca:%'` und in `market_mover` prüfen; im nächsten Zyklus
      stichprobenhaft ein `research_item` mit `source_type='market_mover'` und
      eines mit gefülltem `instruments` in der UI ansehen (Decision Journal /
      Agent Trace).
- [ ] **Nach einem vollen Tag `cost_ledger` gegenprüfen.** Mehr Research-Zeilen
      heißt größerer Persona-Prompt in jedem der 4 Zyklen × 6 Personas. Wenn es
      zu teuer wird, sind `alpaca_news.limit` (50) und `alpaca_screener.top` (10)
      die feineren Regler als der `enabled`-Schalter. Rechnung: F105 §6.

## 5. Aus ADR-0015 (Alpaca-Agent-Research-Tooling)

- [ ] **ADR-0015 von `proposed` auf `accepted` setzen**, sobald du die
      Abgrenzung mitträgst (kein CLI, kein MCP-Server, keine Backtest-Skill im
      Laufzeitpfad; Übernahme nur über das vorhandene SDK).
- [ ] **Offen zur Entscheidung, bewusst nicht gebaut:** ein deterministisches
      Backtest-Modul im Review-Zweig (P5+), das den Reproduzierbarkeits-Kontrakt
      der Alpaca-Skill nachbaut (Spec + Config + Data-Fingerprint + Run-Lineage).
      Braucht deine Anforderung — Backtesting steht in keiner Phase von
      ARCHITECTURE.md §8.

## 6. F106 — zwei weitere Tages-Newsletter (Zieldefinition liegt vor)

Blockiert die Umsetzung, Details in `docs/features/F106-morningcrunch-newsletter-ingestion.md` §4.

- [ ] **Je eine Original-Mail als `.eml`** von materialscrunch und marketscrunch
      (die RTF-Exporte zeigen die HTML-Ansicht, ich brauche den `text/plain`-Teil).
      Davon hängt ab, ob es bei zwei Config-Zeilen bleibt oder der Parser eine
      zweite Abschnitts-Erkennung braucht — die beiden laufen nicht über beehiiv.
- [ ] **Instrument-Tagging entscheiden:** nur `$TICKER` wie heute (tagt hier fast
      nichts), Namensabgleich gegen das handelbare Universum, oder erst minimal
      und Namensabgleich als Folge-Feature.
- [ ] **Bucket-Frage:** ein gemeinsamer `source_type='newsletter'` für alle drei
      Newsletter (günstiger, sie konkurrieren um dieselbe Prompt-Quote) oder je
      einer pro Newsletter (mehr Impulse, mehr Token).
- [ ] **Werbe-Abschnitte bestätigen:** `ANZEIGE`, `MORE BRIEFINGS`, `APP-PFIFF`
      raus; `STAT OF THE DAY` / `STAT OF THE WEEK` bleiben.
- [ ] **Status des cryptocrunch-n8n-Zweigs** (F102 steht auf „n8n-Zweig offen") —
      falls noch nicht aktiv, ziehen wir alle drei Zweige in einem Rutsch nach.

## 7. Kein Handlungsbedarf (zur Sicherheit dokumentiert)

- **`ugreen-Box`-Repo:** keine Änderung an `docker-compose.yml` (keine neuen
  Services, Ports, Env-Vars) — die Homelab-Doku bleibt unberührt.
- **`.env`:** keine neue Credential. F104/F105 nutzen den vorhandenen
  `ALPACA_MARKET_DATA_*`-Key.
- **CI-Pflicht-Checks:** kein neuer Job, die Ruleset-Einstellung für `main`
  bleibt wie sie ist.

## 8. Älteres, hier nur verlinkt

Die Phase-4-Punkte, die vor dieser Session offen waren, stehen weiterhin in
`docs/dod/phase-4.md` → „Weiterhin offen" (HITL-End-to-End-Testrunde mit
`/hitl on`, Bestätigung der täglichen Digest-Zustellung). Sie sind hier bewusst
nicht dupliziert.
