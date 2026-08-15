# F106 — Zwei weitere Tages-Newsletter (materialscrunch, marketscrunch)

Status: live auf der Box inkl. n8n-Zweigen (15.08.2026), erste automatische Ausgabe steht aus (§7)
Datum: 2026-08-11
Auslöser: Ralf, zwei Beispielausgaben vom 11.08.2026 (RTF, danach `.eml`)

## 1. Zieldefinition

Zwei zusätzliche abonnierte Tages-Newsletter desselben Verlags wie der bereits
integrierte Krypto-Börsenbrief (F102) sollen automatisch über n8n in den
geteilten Research-Pool laufen.

| | materialscrunch | marketscrunch |
|---|---|---|
| Absender (laut Beispiel) | `hello@morningcrunch.de` | `markets@m.morningcrunch.de` |
| Antwort-an | `feedback@morningcrunch.de` | `pos@morningcrunch.de` |
| Zustellung | täglich, 06:01 MESZ | täglich, 05:59 MESZ |
| Betreff | wechselt je Ausgabe („🪏 El Niño: Kaffee & Kakao werden teurer") | wechselt je Ausgabe („💸 China: Mit der Börse gegen die USA") |
| Abschnitte | APP-PFIFF, MATERIALS OVERVIEW, HOT STOCKS, DEEP DIVE, ZOOM IN, QUICK CATCH-UP, STAT OF THE WEEK, ANZEIGE, MORE BRIEFINGS | APP-PFIFF, WHAT TO WATCH, TOP STORY, MARKET MOVER, QUICK CATCH-UP, ANZEIGE, STAT OF THE DAY, MORE BRIEFINGS |
| Thematik | Rohstoffe/Soft Commodities, Rohstoffaktien | Aktien, Makro, Einzelwerte |

**Warum das ohne viel neuen Code geht:** F102 hat die Pipeline bereits
**mehr-Newsletter-fähig** gebaut. `config/ingestion.yaml` führt unter
`newsletters:` eine Liste, jeder Eintrag mit `slug`, `sender`, `subject_marker`,
`drop_sections`, `blocked_link_domains`, `single_item_sections`, `ticker_map`;
`identify_newsletter()` matcht auf den Absender, der Webhook
`/api/ingestion/newsletter/notify` und die Synthese in den Pool sind quellen-
agnostisch. Umgesetzt wurde deshalb: **zwei Config-Einträge, zwei n8n-Zweige, eine
Parser-Korrektur** (§3c), verifiziert gegen je eine echte Ausgabe.

**Scope:** beide Newsletter als eigene `newsletter_slug`-Quellen in
`newsletter_item`, Ingestion über den bestehenden n8n-Mail-Trigger, Synthese in
den geteilten Pool wie bei F102.
**Non-Scope (unverändert aus F102):** kein Abrufen der verlinkten Artikel (der
Newsletter fasst jede Story selbst zusammen — das ist der Impuls), keine
Volltexte in UI/Repo, keine LLM-Zusammenfassung (Parser bleibt deterministisch),
keine persona-spezifische Filterung.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, geprüft | Beide landen im geteilten Pool, für alle sechs Personas identisch sichtbar. Dass Rohstoff-Impulse für VULTURE/CONTRA nützlicher sind als für CRYPTOR, ist Charter-Wirkung, kein Informationsvorsprung. |
| #9 Untrusted Content | ja, zentral | Verlagstext, potenziell feindlich. Weg wie F102: als getaggter Datenblock über `research_item.raw["excerpt"]` (600-Zeichen-Cap) in den Persona-Prompt, nie in einen System-Prompt, nie in die Nähe eines Order-Tools. |
| #3 kein Pfad zur Order | nein | Reine Research-Daten. |
| Webhook als Schreibkanal | ja | Unverändert: Secret-Header **und** Absender-Match (`identify_newsletter` → sonst 422). Zwei neue Absender erweitern die Allowlist um genau zwei Adressen. |
| Kosten | ja, zu beziffern | Zwei Ausgaben täglich, je grob 20–30 Impulse. F102 argumentiert, dass `source_type='newsletter'` einen eigenen Round-Robin-Bucket in `persona_analysis` (F047) hat und deshalb andere Quellen verdrängt statt den Prompt zu verlängern. **Das gilt seit F106 nicht mehr unbesehen:** drei Newsletter teilen sich denselben Bucket, er wird also dreifach belegt statt breiter — bewusst so entschieden (§4.2), weil das die Token-Zahl je Call deckelt statt sie zu verdreifachen. |

## 3. Zwei Befunde aus den Beispielausgaben — gegen die echten `.eml` geprüft

**(a) Parser-Risiko: entwarnt.** Die RTF-Exporte zeigten Tracking-Domains
(`elinkb60.morningcrunch.de`), die nicht nach beehiiv aussahen. Der `text/plain`-Teil
der echten Mails zeigt das Gegenteil: **beide Ausgaben sind beehiiv**, mit exakt dem
Layout, das F102 schon parst — `###### ABSCHNITT`-Überschriften, `==`-Auszeichnungen,
`[Text](URL)`-Links, `Bild anzeigen:`/`Caption:`-Gerüst, Permalink am Ende
(`morningcrunch-materials.beehiiv.com/p/30-260811` bzw.
`markets-crunch.beehiiv.com/p/151-260811`). Die Tracking-Domains stecken nur im
HTML-Teil, den die Pipeline gar nicht liest; versendet wird über SendGrid. Der
bestehende Parser lief ohne Änderung durch: **13 Impulse** je Ausgabe.

**(b) Instrument-Tagging: bestätigt dünn.** Über beide Ausgaben zusammen vier Ticker
im Plain-Part — `$BP`, `$SPCX`, `$TSLA` (materials), `$LLY` (markets). Alles andere
steht als Klartext-Firmenname im Fließtext. `ticker_map` bekommt deshalb nur die
Symbole, die Alpaca auch handelt (`TSLA`, `BP`, `LLY`); `$SPCX` (SpaceX, nicht
börsennotiert) bleibt bewusst außen vor. Ergebnis in der Praxis: der SpaceX-Block
wird trotzdem korrekt mit `TSLA` getaggt, weil er Tesla mit Ticker nennt. Der
Namensabgleich bleibt Folge-Feature (§6).

**(c) Neuer Befund: eine echte Lücke im Parser.** `WHAT TO WATCH` (marketscrunch) ist
der Termin- und Earnings-Kalender des Tages — lauter Einzeiler („Makro:
Verbraucherpreise", „Earnings: Salzgitter, Uniper"), die je für sich unter dem
`_MIN_ITEM_CHARS`-Boden von 40 Zeichen liegen. Der Abschnitt fiel dadurch komplett
weg, obwohl er zu den nützlichsten der Ausgabe gehört. Behoben: für
`single_item_sections` greift die Mindestlänge jetzt **nach** dem Zusammenfassen, die
Werbefilter weiterhin pro Block (F102s Begründung bleibt gültig). Danach: 14 Impulse
für marketscrunch.

**(d) Was strukturell nicht ankommt.** `MATERIALS OVERVIEW`, `HOT STOCKS` und
`WHAT'S GOING ON?` sind in der Mail **Bilder** (dynamisch gerenderte Kurstabellen von
`morningcrunch.onvista.de`, mit einer empfängerbezogenen `rid` in der URL). Ihr Inhalt
existiert weder im Plain- noch im HTML-Text. Diese Abschnitte liefern deshalb null
Impulse — sichtbar, deterministisch, kein Fehler. Die Bild-URLs werden nicht
abgerufen (nichts im Code ruft Links ab, und die `rid` macht sie zu einem
Tracking-Pixel).

## 4. Entscheidungen, die ich mangels Rückmeldung selbst getroffen habe

Alle drei sind Config und ohne Deploy umkehrbar — Widerspruch jederzeit möglich:

1. **Instrument-Tagging: Variante C** — zunächst nur `$TICKER`, Namensabgleich als
   Folge-Feature. **Überholt am selben Tag:** Ralf hat den Namensabgleich beauftragt,
   er ist als F107 umgesetzt und greift auch für diese beiden Newsletter.
2. **Gemeinsamer Bucket.** Alle drei Newsletter behalten `source_type='newsletter'`
   und teilen sich damit dieselbe Round-Robin-Quote im Persona-Prompt (F047). Sie
   verdrängen einander statt den Prompt zu verlängern — der Kosten-schonende Weg.
   Preis: cryptocrunch verliert relative Sichtbarkeit im Pool.
3. **Werbe-Abschnitte.** `ANZEIGE`, `MORE BRIEFINGS`, `BEZAHLTE PARTNERSCHAFT` und
   `APP-PFIFF` (Eigenwerbung für die Verlags-App, steht in jeder Ausgabe ganz oben)
   fliegen raus. `STAT OF THE DAY` / `STAT OF THE WEEK` bleiben — das ist Inhalt.
   Zusätzlich steht `app.morningcrunch.de` auf der Domain-Sperrliste, damit der
   Sign-up-Plug auch mitten im redaktionellen Teil erwischt wird.

## 5. Abschnitts-Behandlung (umgesetzt)

| Newsletter | `single_item_sections` | `drop_sections` | liefert je Bullet einen Impuls |
|---|---|---|---|
| materialscrunch | DEEP DIVE, ZOOM IN | ANZEIGE, MORE BRIEFINGS, APP-PFIFF, BEZAHLTE PARTNERSCHAFT | QUICK CATCH-UP, STAT OF THE WEEK, INTRO |
| marketscrunch | TOP STORY, MARKET MOVER, WHAT TO WATCH | dieselben | QUICK CATCH-UP, STAT OF THE DAY, INTRO |

`INTRO` (der Text vor der ersten Überschrift) bleibt drin, wie beim cryptocrunch. Er
ist bei diesen beiden oft redaktioneller Small Talk (Ford Mustang, Bazooka im Rhein),
trägt aber auch echte Impulse (Rhein-Niedrigwasser und dessen BIP-Wirkung). Die
Personas sortieren das selbst aus; ein pauschaler Filter würde die Substanz
mitnehmen.

## 6. Testdefinition und Umsetzung

Tests in `tests/ingestion/test_crypto_newsletter.py` (synthetische Fixture im
F102-Stil — die echten Ausgaben sind Abo-Inhalt und bleiben aus dem Repo):

1. `test_new_newsletters_are_configured` — beide Slugs laden, Abschnitts-Listen sitzen.
2. `test_identify_newsletter_separates_the_three_senders` — jeder Absender trifft
   genau seinen Newsletter.
3. `test_short_calendar_entries_survive_as_one_merged_impulse` — Befund (c), der
   eigentliche Regressionstest.
4. `test_short_blocks_outside_single_item_sections_are_still_dropped` — Gegenprobe:
   der Boden gilt anderswo unverändert.
5. `test_single_item_section_below_the_floor_yields_nothing` — auch zusammengefasst
   zu kurz ⇒ nichts.
6. `test_app_promo_section_is_dropped` — APP-PFIFF-Abschnitt und der Sign-up-Link.
7. `test_market_mover_section_merges_into_one_analysis` — Zusammenfassung greift.
8. `test_ticker_map_tags_configured_symbols` — nur konfigurierte Symbole werden getaggt.

Geändert:

| Datei | Änderung |
|---|---|
| `config/ingestion.yaml` | zwei `newsletters:`-Einträge |
| `src/ingestion/crypto_newsletter.py` | Mindestlänge nach dem Merge für `single_item_sections` (Befund c) |
| `n8n/publications-mail-trigger.json` | zwei weitere Zweige am bestehenden IMAP-Trigger |
| `web/src/lib/labels.ts` | Label „Krypto-Börsenbrief" → „Börsenbrief" (drei Newsletter teilen den `source_type`); dazu das bei F105 vergessene `market_mover`-Label |

Das Modul heißt weiterhin `crypto_newsletter.py`, obwohl es jetzt drei Newsletter
bedient. Umbenennen wäre reine Kosmetik mit Import-Churn — bewusst gelassen.

## 7. Rollout und Rollback

- `uv run pytest`: **956 passed, 26 deselected**. `ruff`, `mypy src`: clean.
- **Gegen die echten Ausgaben vom 11.08.2026 verifiziert** (Einmal-Lauf im
  Scratchpad, nicht im Repo): materialscrunch 13 Impulse aus 5 Abschnitten,
  marketscrunch 14 aus 6; beide Permalinks korrekt erkannt, kein Werbe-Abschnitt und
  kein gesperrter Link in den Ergebnissen, `$BP`/`$TSLA`/`$LLY` korrekt getaggt.
- **Erledigt am 15.08.2026:** Deploy auf der Box (`api`, `web`, `scheduler`,
  `telegram-bot` neu gebaut) und die beiden n8n-Zweige live im Workflow
  „ATLAS - Publications Mail-Trigger" (`Wmf3Qgf3RGq7cNup`), jetzt 11 Nodes,
  `active`. Kein Schema-Change, keine Migration, keine neue Env-Var.
- **Wie der n8n-Import lief — für das nächste Mal wichtig.** Nicht die
  Repo-Vorlage direkt importieren: sie enthält Platzhalter-Credential-IDs und
  würde die bestehende Verdrahtung überschreiben. Stattdessen den **Live-Stand
  exportieren, die zwei Zweige hineinkopieren und zurückimportieren** — dabei
  bleiben `staticData` (`lastMessageUid` des IMAP-Triggers, sonst würde der
  Trigger Mails doppelt oder gar nicht ziehen) und die echten Credential-IDs
  der Header-Auth- und IMAP-Credentials erhalten (die stehen im Live-Export und
  gehören nicht ins Repo). Ablauf im Container `ix-n8n-n8n-1`:

  ```
  n8n export:workflow --id=Wmf3Qgf3RGq7cNup --pretty --output=/tmp/backup.json
  # Zweige ergänzen, dann:
  n8n import:workflow --input=/tmp/neu.json
  n8n publish:workflow --id=Wmf3Qgf3RGq7cNup
  docker restart ix-n8n-n8n-1
  ```

  Zwei Fallstricke, die das erzwingen: `import:workflow` setzt den Workflow
  **immer auf `active=false`** (`--activeState=fromJson` gibt es nur im
  Queue-/Multi-Main-Modus, den diese Instanz nicht fährt) — deshalb das
  anschließende `publish:workflow`. Und n8n 2.x lädt aktive Workflows beim Start:
  ohne Container-Neustart liefe der alte Stand weiter. Der Neustart betrifft die
  ganze n8n-Instanz (auch „Abfallkalender" und „Tägliche Infomail"); beide sind
  Cron-getrieben und wurden im Log sauber reaktiviert.
- **Rollback:** den jeweiligen n8n-Zweig deaktivieren — sofort wirksam, ohne Deploy;
  bestehende Zeilen bleiben. Vollständig: die beiden Config-Einträge entfernen.
  Ein Layout-Wechsel beim Verlag ist kein Rollback-Fall: der Webhook antwortet dann
  mit `items: 0` und loggt eine Warnung.

## 8. Folgearbeit (nicht in diesem Feature)

- ~~Namensabgleich für Instrumente~~ → **erledigt als F107** (11.08.2026), deckt
  alle drei Newsletter, die Zeitschriften-Artikel und die Yahoo-Marktnews ab.
- **Bild-Abschnitte** (`HOT STOCKS`, `MATERIALS OVERVIEW`): nur über OCR erreichbar.
  Aus meiner Sicht nicht lohnend — die Kurstabellen dort haben wir über Alpaca
  ohnehin, und zwar in Zahlen statt in Pixeln.
