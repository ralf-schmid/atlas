# F102 — Zyklus-Drosselung + Krypto-Börsenbrief als Research-Quelle

Status: implementiert und live verifiziert (08.08.2026), n8n-Zweig offen
Datum: 2026-08-08
Auslöser: Ralf, nach dem Zen-Guthaben-Ausfall vom 07.08.2026

Zwei getrennte Änderungen in einem Dokument, weil sie denselben Anlass haben
(LLM-Kosten) und gegenläufig wirken: §1 senkt die Zyklus-Anzahl, §2 vergrößert den
Research-Pool.

---

## 1. Zyklus-Drosselung 4 → 3 pro Tag

### 1.1 Ziel

Den eingeschwungenen LLM-Verbrauch von ~3,4 USD/Tag (~100 USD/Monat) senken.
Messbasis aus `cost_ledger`, 03.–06.08.2026: 3,29 / 3,33 / 3,40 / 3,39 USD/Tag,
davon 81 % `persona_analysis` auf Sonnet (7 Tage: 14,24 von 17,49 USD).

### 1.2 Umsetzung

`config/cycles.yaml`:

- Aktien: C2 (10:30 ET) auf `active: false`. Bleibt deklariert statt gelöscht — der
  Rollback ist damit ein Ein-Zeilen-Flip. Aktiv: C1 09:00, C3 13:00, C4 15:15 ET.
- Crypto: `weekday_times` von `["00:00","06:00","12:00","18:00"]` auf
  `["06:00","12:00","18:00"]`. Wochenende unverändert bei 2 Zyklen.

Auswahl C2: liegt nur 90 Minuten hinter C1, trägt von allen vier den geringsten
Informationszuwachs. Auswahl 00:00 UTC: dünnster Krypto-Slot (Liquidität,
Nachrichtenlage). Beides Ralfs Entscheidung, 08.08.2026.

### 1.3 Kritische Betrachtung

- **Invariante 10 (Fairness):** unkritisch. Die Drosselung trifft alle 6 Personas
  identisch, kein Charter-Bump nötig. Sie verändert aber die Versuchsbedingungen ab
  dem 08.08.2026 — bei der Auswertung nach §4.7 ist die Halbzeit-Zäsur zu erwähnen,
  die Wochen davor liefen auf 4 Zyklen.
- **Erwarteter Effekt:** ~-25 % auf `persona_analysis` (der 4-Zyklen-Anteil), also
  grob 3,4 → ~2,7 USD/Tag. Nicht die Hälfte, weil Recherche-Ingestion, Review-Agent
  und Digest zyklusunabhängig laufen.
- **Deploy-Fallstrick:** `config/` ist ins Image gebacken; nur
  `config/litellm_proxy_config.yaml` ist gemountet (`docker-compose.yml`). Der
  Kommentarkopf von `cycles.yaml` behauptete das Gegenteil („wirkt ohne Deploy") —
  korrigiert. Änderung braucht `build` + `up -d`, nicht nur `restart`.

### 1.4 Tests

`tests/orchestrator/test_cycles_config.py`, `tests/orchestrator/test_scheduler.py` —
die fünf Tests, die die 4-Zyklen-Taktung fest kodierten, prüfen jetzt die 3-Takt-
Konfiguration und dass C2 deklariert-aber-inaktiv bleibt.

### 1.5 Rollback

`active: false` → `true` bei C2, `"00:00"` wieder in `crypto.weekday_times`,
Rebuild. Keine Datenmigration.

---

## 2. Krypto-Börsenbrief (CryptoCrunch) als Research-Quelle

### 2.1 Ziel

Ralf abonniert den täglichen Krypto-Börsenbrief *cryptocrunch*
(`cryptocrunch@m6.morningcrunch.de`, Versand über beehiiv). Jede Ausgabe soll
automatisch in Einzel-Impulse zerlegt und in der DB abgelegt werden, damit CRYPTOR
davon profitiert.

**Nicht** exklusiv für CRYPTOR: die Impulse landen im Shared Research Pool und sind
für alle 6 Personas sichtbar (Invariante 10). CRYPTOR profitiert, weil es die einzige
Persona mit Krypto-Mandat ist — nicht, weil es einen privaten Feed bekäme. Die
Aktien-Namen der Ausgabe (Coinbase, Circle, Block, TeraWulf) sind für die anderen
Personas genauso sichtbar.

### 2.2 Entscheidung: keine Links abrufen

Ralfs ursprüngliche Formulierung war „alle Impulse aus der Mail **und den
aufgeführten Links**". Nach Rückfrage entschieden (08.08.2026): **nur der
Newsletter-Text**, Links nur als Quellenverweis.

Begründung:

- Der Newsletter fasst jede verlinkte Story selbst in 1–3 Sätzen zusammen. Das ist
  der Impuls, den das Abo liefert; der Zielartikel ist meist dieselbe Tatsache in
  länger.
- ~30 Links je Ausgabe, täglich. Robots-Prüfung je Domain wäre nötig (F058-Präzedenz:
  reuters.com verbietet automatisierten Zugriff), Bloomberg & Co. liefern Paywall-
  Seiten statt Inhalt.
- Copyright: CLAUDE.md verbietet Fremd-Volltexte in UI/Repo.

Die Domain-Sperrliste in `config/ingestion.yaml` ist dadurch **zweite** Sicherung,
nicht erste: es ruft ohnehin nichts ab.

### 2.3 Kritische Betrachtung

- **Werbung ist die gefährlichste Zeile der Ausgabe.** Der Börsenbrief enthält eine
  bezahlte Partnerschaft im Stil eines redaktionellen Beitrags („Trading Journey
  Week #2: Warum ich bei HYPE long gegangen bin"), einen `ANZEIGE`-Slot und einen
  Affiliate-Einschub mitten im redaktionellen Intro. Ungefiltert würde CRYPTOR eine
  Anzeige als Analysten-Impuls lesen. Zwei Filterebenen: ganze Abschnitte per
  `drop_sections`, plus Block-für-Block-Drop bei Link auf eine gesperrte Domain.
  Der Block-Filter läuft **vor** dem Single-Item-Merge, damit ein Werbeblock in einem
  sonst redaktionellen Abschnitt nur sich selbst mitnimmt.
- **beehiiv-Links sind nicht nur Rauschen, sondern gefährlich.**
  `magic.beehiiv.com/v1/...?email=<Ralfs Adresse>` ist ein Login-per-Klick-Link mit
  seiner Mailadresse im Query-String, `unsub.beehiiv.com` kündigt das Abo. Beide
  stehen auf der Sperrliste, ein eigener Test (`test_no_blocked_link_is_ever_persisted`)
  wacht darüber, dass keiner in der DB landet.
- **Invariante 9 (Untrusted Content):** Verlags-Text, potenziell feindlich. Erreicht
  Personas ausschließlich als getaggter Datenblock über den Research-Pool, nie als
  System-Prompt, nie in der Nähe eines Order-Tools. Der Webhook nimmt nur konfigurierte
  Absender an (`identify_newsletter` → 422 sonst), sonst wäre er ein offener
  Schreibkanal in den Research-Pool.
- **Invariante 3:** kein Pfad von hier zu einer Order. Wie F014 reine Research-Daten.
- **Kosten, gegenläufig zu §1:** ~21 Items je Ausgabe, täglich. Als eigener
  `source_type` bekommt der Börsenbrief einen eigenen Round-Robin-Bucket in
  `persona_analysis` (F047) — er verdrängt also andere Quellen aus dem Prompt statt
  ihn zu verlängern, der Effekt auf die Token-Zahl je Call ist gering. `raw["excerpt"]`
  ist auf den geteilten 600-Zeichen-Cap begrenzt.
- **Keine LLM-Calls:** Parser und Synthese sind rein deterministisch, wie der Rest von
  `research_synthesis`.

### 2.4 Umsetzung

| Datei | Zweck |
|---|---|
| `src/ingestion/crypto_newsletter.py` | Parser (rein, testbar) + `sync_newsletter_items` |
| `src/db/models.py` | `NewsletterItem` |
| `alembic/versions/e1f2a3b4c5d6_add_newsletter_item.py` | Tabelle + `synced_at`-Index |
| `src/api/routes_ingestion.py` | `POST /api/ingestion/newsletter/notify` |
| `src/orchestrator/research_synthesis.py` | `_research_items_from_newsletter_items` |
| `config/ingestion.yaml` | `newsletters:` — Absender, Sperrlisten, Ticker-Map |
| `n8n/publications-mail-trigger.json` | dritter Zweig am bestehenden IMAP-Trigger |
| `web/src/lib/labels.ts` | Anzeige-Label „Krypto-Börsenbrief" |

Parsing-Details, die aus der echten Ausgabe vom 07.08.2026 stammen:

- Gelesen wird der **text/plain**-Teil, nicht HTML. beehiivs Plain-Part ist bereits
  sauberes Markdown mit Inline-Links; der HTML-Teil ist 4,5× so groß und bräuchte
  erst Tag-Stripping. Der n8n-Node sendet deshalb `textPlain || textHtml` — umgekehrt
  zum Musterdepot-Zweig.
- Abschnitte werden an den `######`-Überschriften geschnitten. Der Text **vor** der
  ersten Überschrift ist redaktionelles Intro mit echten Impulsen (die Ausgabe öffnet
  mit der Bundestags-Petition zur Bitcoin-Haltefrist) und bekommt den synthetischen
  Abschnittsnamen `INTRO`.
- `TOP STORY` wird zu genau einem Item zusammengefasst (`single_item_sections`) — die
  Einzel-Bullets verlieren ohne die Überschrift ihren Sinn. Alle anderen Abschnitte
  liefern einen Impuls je Bullet/Absatz.
- `instruments` bekommt nur Ticker, die `ticker_map` auf ein handelbares Symbol
  abbildet (BTC/ETH/SOL). `$HYPE`, `$JPYC` bleiben im Text, erzeugen aber keine
  Instrument-Referenz, auf die `persona_analysis` dann Companion-Items zu joinen
  versucht.
- `research_item.url` ist der Issue-Permalink, nicht der zitierte Fremdartikel — die
  Quelle ist der Börsenbrief.

### 2.5 Tests (definiert vor der Umsetzung)

`tests/ingestion/test_crypto_newsletter.py` (16 Tests) gegen ein **synthetisches**
Fixture, das die Struktur der echten Ausgabe nachbaut, ohne Verlagstext ins Repo zu
bringen. Kernfälle:

1. Werbe-Abschnitte kommen nicht durch (`test_paid_sections_are_dropped`).
2. Affiliate-Block im redaktionellen Intro fliegt raus, der echte Impuls daneben
   bleibt (`test_affiliate_block_inside_editorial_intro_is_dropped`).
3. Kein gesperrter Link wird je persistiert (`test_no_blocked_link_is_ever_persisted`).
4. Nur handelbare Ticker werden `instruments`.
5. Idempotenz auf `(message_id, seq)` bei Wiederzustellung.

`tests/api/test_routes_ingestion.py`: Secret-Prüfung, 422 bei unbekanntem Absender,
Persistenz inkl. tz-aware `received_at` von n8n.

`tests/orchestrator/test_research_synthesis.py`: Mapping in den Pool, `summary` bleibt
Metadaten-Zeile, Excerpt-Cap.

**Zusätzlich gegen die echte Mail geprüft** (nicht im Repo, Einmal-Lauf im
Scratchpad): 21 Impulse aus 5 Abschnitten, 0 gesperrte Links, alle 5 Werbe-Proben
(`Trading Journey`, `Coinbase Advanced`, `Fast Lane`, `marketscrunch`,
`Derivate sind komplexe`) nicht im Ergebnis. Dabei drei Bugs gefunden und behoben:

- `extract_issue_url` nahm den **ersten** `/p/`-Link — die Top-Story zitiert eine
  ältere Ausgabe (`/p/134-260716`), die Ausgabe wäre unter der falschen URL abgelegt
  worden. Jetzt der letzte Treffer (Footer-Permalink).
- `## ==Titel==` überlebte als `## Titel` im Titel der Top-Story — Heading-Marker
  werden jetzt gestrippt.
- Einfache `_`-Kursivierung blieb als `(_Deep Dive_)` stehen.

### 2.6 Rollback

Zweistufig, je nach Dringlichkeit:

1. **Sofort, ohne Deploy:** den Zweig „Filter: Krypto-Boersenbrief" in n8n
   deaktivieren. Es kommen keine neuen Ausgaben mehr an, bestehende Zeilen bleiben.
2. **Vollständig:** Commit zurücknehmen + `alembic downgrade -1`. Betrifft keine
   andere Quelle — `newsletter_item` ist eine eigene Tabelle, n8n verliert nur einen
   unabhängigen Zweig.

Ein Layout-Wechsel beim Verlag ist kein Rollback-Fall: der Webhook antwortet dann mit
`items: 0` und loggt eine Warnung, statt n8n in eine Retry-Schleife zu schicken.

## 3. Live-Verifikation (08.08.2026)

Deploy per rsync auf `atlas-ugreen`, `docker compose build api scheduler telegram-bot
web` + `up -d`, `alembic upgrade head` (→ `e1f2a3b4c5d6`).

**Zyklus-Drosselung** — gegen die ins Image gebackene Config im laufenden
`scheduler`-Container geprüft:

```
stock active: [(1, '09:00'), (3, '13:00'), (4, '15:15')]
crypto weekday: ['06:00', '12:00', '18:00'] | weekend: ['06:00', '18:00']
cycle jobs: crypto-weekday-{06,12,18}:00, crypto-weekend-{06,18}:00,
            stock-c1, stock-c3, stock-c4
```

**Börsenbrief** — die echte Ausgabe vom 07.08.2026 an den Live-Webhook gepostet:

- `202 {"newsletter":"cryptocrunch","items":21,"status":"ingested"}`
- Verteilung in `newsletter_item`: HEADLINES 9, COIN SNAPSHOT 4, QUICK CATCH-UP 4,
  INTRO 3, TOP STORY 1. Die drei Werbe-Abschnitte fehlen erwartungsgemäß.
- `instruments` gesetzt bei genau 2 Zeilen (BTC/USD, ETH/USD) — `$HYPE` korrekt ohne.
- Gegenprobe in der DB: 0 Zeilen mit einem `beehiiv`- oder `sjv.io`-Link, 0 Zeilen mit
  Werbetext (`trading journey`, `coinbase advanced`).
- Wiederzustellung derselben Mail: erneut 202/21, Tabelle bleibt bei 21 Zeilen
  (Idempotenz).
- Fremder Absender (`spam@example.com`) mit gültigem Secret: **422**, keine Zeile.

Die 21 Zeilen bleiben stehen — es sind echte Daten der abonnierten Ausgabe und werden
vom nächsten Zyklus regulär als Research aufgenommen.

## 4. Offen

- **n8n-Zweig muss Ralf in der laufenden Instanz anlegen** (Workflow „ATLAS -
  Publications Mail-Trigger"): Filter auf Absender `cryptocrunch@m6.morningcrunch.de`
  → HTTP-POST auf `/api/ingestion/newsletter/notify` mit dem Secret-Header. Die
  Vorlage steht in `n8n/publications-mail-trigger.json`, die Credential-IDs sind
  Platzhalter — dieselbe Situation wie bei F014. Bis dahin kommt keine neue Ausgabe
  automatisch an.
- `research_item`-Zeilen mit `source_type = "newsletter"` entstehen erst beim nächsten
  Zyklus. Der lief zuletzt am 07.08. 12:00 UTC — die Zyklen fallen aus, solange das
  OpenCode-Zen-Guthaben leer ist.
- Kein Eintrag im `ugreen-Box`-Repo nötig: weder `docker-compose.yml`, noch Ports,
  Services oder Env-Vars haben sich geändert.
