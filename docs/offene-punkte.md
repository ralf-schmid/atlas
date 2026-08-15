# Offene Punkte für Ralf

Was auf der Box passieren muss, damit die fertig entwickelten Features auch
wirken. Stand: 2026-08-15. Reihenfolge = empfohlene Abarbeitung.

Alles hier ist **Betrieb**, nicht Entwicklung. Erledigte Punkte abhaken und
den Nachweis im jeweiligen Feature-Dokument (§5) nachtragen — nicht hier.

**Deploy-Durchgang vom 15.08.2026:** F103–F107 sind auf der Box live (rsync,
`build api web scheduler telegram-bot`, `up -d`, `alembic upgrade head`, beide
n8n-Zweige aktiv, F103-Backfill gelaufen). Was hier noch offen steht, sind
ausschließlich Beobachtungs- und Entscheidungspunkte, die Zeit oder dich
brauchen — kein Deploy-Schritt mehr.

## 1. Deploy F103–F105 (ein Durchgang) — erledigt 15.08.2026

- [x] `alembic upgrade head` — beide Migrationen gelaufen: `f7a1c2d3e4b5`
      (`order_record.spread_bps`, F104) und `c9e8d7f6a5b4` (`market_mover` +
      `market_news_headline.instruments`, F105). DB stand vorher auf
      `e1f2a3b4c5d6`, jetzt auf `c9e8d7f6a5b4`.
- [x] `docker compose build` + `up -d` — alle sechs Container laufen, `api`
      healthy, `/health` → `{"status":"ok"}`, Web auf `:3001` → 200. Der
      Scheduler registriert die neuen Jobs `_alpaca_news_job` und
      `_alpaca_screener_job`.

## 2. F103 — Split-adjustierte Markt-Bars

- [x] **Einmaliger Re-Sync mit `lookback_days=180`** — gelaufen, 375 Symbole,
      46.444 Bars geschrieben, `market_bar` 49.079 → 64.836 Zeilen, Historie
      jetzt ab 2026-02-17 statt 2026-04-13. Kein Mischbestand mehr.
- [x] **Verifikation** — Adjustment gegen die Alpaca-API nachgewiesen (RCON
      `raw` 0,4607 vs. `split` 92,14), Indikatorwerte für AAPL/MSFT/SPY in
      F103 §5 notiert.
- [x] **Nano-Caps mit kaputter Split-Historie** — entschieden und umgesetzt als
      [F108](../features/F108-indikator-plausibilitaet.md) (15.08.2026, live).
      Kein `technical_indicator`-Impuls mehr, wenn die Kursreihe im
      Indikator-Fenster einen Niveauwechsel hat (Overnight-Gap ≥ Faktor 2,0).
      Aktuell 9 von 378 Symbolen betroffen, keine offene Position darunter.
      Der Filter sitzt bewusst **nicht** im Screener, obwohl das die
      ursprüngliche Ansage war: das `screener_result`-Item trägt nur den
      korrekt gemessenen Live-Kurs, da gibt es nichts zu filtern (F108 §1).

## 3. F104 — Gemessener Bid/Ask-Spread

- [ ] **Nach dem ersten neuen Trade:** die frische `order_record`-Zeile auf
      `spread_bps` prüfen und den Wert gegen den Alpaca-Dashboard-Spread des
      Symbols plausibilisieren; danach das zugehörige Review auf einen Malus > 0
      kontrollieren. Nachweis in F104 §5.
- [x] **Methodenbruch steht seit 15.08.2026 im Wochenreport** (Ralfs
      Entscheidung). Der Report weist aus, wie viele der gewerteten Orders einen
      gemessenen Spread tragen und wie viele die Pauschale, samt Hinweis, dass
      der Schnitt zeitlich und nicht persona-bezogen verläuft. Der Kommentar
      erscheint nur, solange beide Methoden im Wertungsfenster stecken, und
      verschwindet von selbst, sobald die letzte Pauschal-Order herausgelaufen
      ist. Ursprünglicher Text des Punktes:
      Orders vor dem Deploy haben keinen gemessenen Spread (historische Quotes
      sind nicht rekonstruierbar) und behalten die Pauschale. Der Schnitt verläuft
      zeitlich, nicht persona-bezogen — Fairness (#10) bleibt gewahrt, aber die
      Malus-Zahl über die Wettbewerbsdauer ist nicht mit einer einheitlichen
      Methode gerechnet. Hintergrund: F104 §2.

## 4. F105 — Alpaca News + Screener

- [x] **Entitlement geklärt (15.08.2026) — beide Endpoints sind freigeschaltet.**
      Der erste Job-Lauf um 07:10 UTC hat 50 Zeilen in `market_news_headline`
      (`guid LIKE 'alpaca:%'`) und 50 in `market_mover` geschrieben, kein
      `APIError`, kein Telegram-Alert. Das IEX-Entitlement des Marktdaten-Keys
      reicht also für News **und** Screener; der `enabled: false`-Notausgang
      wird nicht gebraucht.
- [ ] **Noch anzusehen:** im nächsten Zyklus stichprobenhaft ein `research_item`
      mit `source_type='market_mover'` und eines mit gefülltem `instruments` in
      der UI (Decision Journal / Agent Trace). Nebenbefund beim Zählen: unter den
      Movern stehen auch Krypto-Symbole (`BONK/USD`) und Warrants (`TMCWW`) —
      ansehen, ob das für die Aktien-Personas sinnvoll ist oder ob der
      Screener-Job auf `us_equity` eingegrenzt werden sollte.
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

## 6. F106 — zwei weitere Tages-Newsletter (umgesetzt)

Gegen die echten Ausgaben vom 11.08.2026 verifiziert; Details in
`docs/features/F106-morningcrunch-newsletter-ingestion.md`.

- [x] **n8n-Zweige live (15.08.2026).** Der Workflow „ATLAS - Publications
      Mail-Trigger" hat jetzt 11 Nodes und ist aktiv; die beiden neuen Filter
      hängen am bestehenden IMAP-Trigger und posten auf denselben
      Newsletter-Webhook wie cryptocrunch. Der Krypto-Zweig war entgegen der
      Notiz in F102 §4 bereits seit dem 08.08. drin. Vorgehen und die zwei
      n8n-Fallstricke stehen in F106 §7.
- [x] `docker compose build` + `up -d` (mit dem Deploy aus §1 zusammengefallen);
      Config auf der Box verifiziert: alle drei Slugs geladen, Absender
      `hello@morningcrunch.de` und `markets@m.morningcrunch.de` sitzen.
- [ ] **Nach der ersten automatisch verarbeiteten Ausgabe:** `newsletter_item` auf
      Zeilen mit `newsletter_slug IN ('materialscrunch','marketscrunch')` prüfen
      (Erwartung: 13–14 je Ausgabe) und im nächsten Zyklus ein `research_item` mit
      `source_type='newsletter'` in der UI ansehen. **Das ist frühestens am
      16.08. morgens möglich:** die Ausgaben vom 15.08. kamen um 05:59/06:01 MESZ
      an, also bevor die Zweige existierten, und der IMAP-Trigger hat sie bereits
      als gelesen abgehakt (`lastMessageUid`). Sie kommen nicht von selbst nach.
- [x] **Zwei Default-Entscheidungen von Ralf bestätigt (15.08.2026):** alle drei
      Newsletter teilen sich einen `source_type` (Kosten), und
      `APP-PFIFF`/`ANZEIGE`/`MORE BRIEFINGS` fliegen raus, während
      `STAT OF THE DAY/WEEK` bleibt. (Die dritte — Instrument-Tagging nur über
      `$TICKER` — war schon durch F107 überholt.)

## 7. F107 — Namensabgleich für Instrumente (umgesetzt)

Deckt Newsletter, Zeitschriften-Artikel und die Yahoo-Marktnews ab; Details in
`docs/features/F107-instrument-namensabgleich.md`.

- [x] Nichts Eigenes zu deployen — mit dem Deploy aus §1/§6 erledigt
      (15.08.2026), `config/instrument_names.yaml` liegt im Image.
- [ ] **Laufende Pflege, wenn dir etwas auffällt:** Wenn im Decision Journal ein
      Impuls ohne Instrument-Tag steht, obwohl die Firma genannt wird, ist ein
      Eintrag in `config/instrument_names.yaml` die ganze Arbeit. Pflegeregeln
      stehen im Kopf der Datei (nur handelbare Symbole, keine Alltagswörter,
      mindestens vier Zeichen).
- [ ] **`aktienfinder_blog_post` an den Namensabgleich anschließen.** Die
      Blog-Beiträge nennen Firmen genauso im Klartext wie die Newsletter, sind aber
      noch nicht angeschlossen — ihre Pool-Zeilen bleiben damit ohne
      `instruments`. Aufwand: eine Zeile in
      `research_synthesis._research_items_from_aktienfinder_blog_posts` plus Test.
      Braucht nur dein Go.
- [ ] Ebenfalls offen, aber derzeit gegenstandslos: `reddit_post`. Der
      Reddit-Job steht seit F039 auf `enabled: false` (Credentials fehlen,
      `config/ingestion.yaml`) — solange dort nichts ankommt, gibt es auch nichts
      zu taggen.

## 8. Kein Handlungsbedarf (zur Sicherheit dokumentiert)

- **`ugreen-Box`-Repo:** keine Änderung an `docker-compose.yml` (keine neuen
  Services, Ports, Env-Vars) — die Homelab-Doku bleibt unberührt.
- **`.env`:** keine neue Credential. F104/F105 nutzen den vorhandenen
  `ALPACA_MARKET_DATA_*`-Key.
- **CI-Pflicht-Checks:** kein neuer Job, die Ruleset-Einstellung für `main`
  bleibt wie sie ist.

## 9. Phasen-Ebene (nicht dupliziert, hier nur der Stand)

Korrektur zum bisherigen Text dieses Abschnitts: die dort genannten Punkte sind
längst erledigt — der tägliche Digest durch F070 (18.07.2026), und HITL ist für
`paper` seit F072 gar nicht mehr zutreffend (`live` bleibt HITL-pflichtig,
Invariante #5). Was auf Phasen-Ebene wirklich offen ist:

- **Phase 4:** nur noch der **Crash-Recovery-Test** — Container-Kill mitten im
  Zyklus, Resume über den Postgres-Checkpointer nachweisen. Kein Feature, ein
  dokumentierter Test (`docs/dod/phase-5.md` §„Reihenfolge", Punkt 1).
- **Phase 5:** vier DoD-Haken offen (`docs/dod/phase-5.md`). Zwei davon brauchen
  **dich**, nicht Code: der Smartphone-Test der UI (~390 px) und die
  Lineage-Probe (5 zufällige Trades, Kette Quelle→Research→Decision→Order→Fill
  →Review in der UI, Screenshots ins DoD-Dokument). Die anderen beiden
  (Review-Agent, Slippage-Malus im Leaderboard) sind gebaut und laufen — Stand
  15.08.: 7 `review`- und 10 `meta_review`-Zeilen bei 56 ausgeführten Decisions
  —, aber der formale Nachweis „jede geschlossene Position hat binnen 7 Tagen
  ein Review" ist nie geführt worden.
