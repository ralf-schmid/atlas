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
- [ ] **Entscheidung: Nano-Caps mit kaputter Split-Historie bei Alpaca.**
      Nebenbefund aus der Verifikation: 22 von 376 Universums-Symbolen haben
      einen Tages-Kurssprung > Faktor 2, der keine Kursbewegung ist, sondern
      Alpacas eigene Datenlage (RCON: Historie mit Faktor 200 hochadjustiert,
      Kurse ab Split-Datum unverändert bei ~0,39). Blue Chips sind sauber.
      Ihre Indikatoren sind Zufallswerte, und eine Persona kann darauf eine
      These bauen. Zwei Wege, beide ändern die Datenbasis für alle sechs
      Personas gleichzeitig und brauchen deshalb dein Go: Plausibilitätsfilter
      im Sync oder Mindest-Marktkapitalisierung im Screener. Details F103 §6.

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
- [ ] **Zwei Entscheidungen, die ich per Default getroffen habe** — Widerspruch
      jederzeit, beides Config und ohne Deploy umkehrbar (F106 §4): alle drei
      Newsletter teilen sich einen `source_type` (Kosten), und
      `APP-PFIFF`/`ANZEIGE`/`MORE BRIEFINGS` fliegen raus, während
      `STAT OF THE DAY/WEEK` bleibt. (Die dritte — Instrument-Tagging nur über
      `$TICKER` — ist durch F107 überholt.)

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

## 9. Älteres, hier nur verlinkt

Die Phase-4-Punkte, die vor dieser Session offen waren, stehen weiterhin in
`docs/dod/phase-4.md` → „Weiterhin offen" (HITL-End-to-End-Testrunde mit
`/hitl on`, Bestätigung der täglichen Digest-Zustellung). Sie sind hier bewusst
nicht dupliziert.
