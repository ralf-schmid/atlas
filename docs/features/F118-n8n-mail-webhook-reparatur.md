# F118 — Der n8n-Mail-Weg lieferte nichts: RFC-2822-Datum, Charset, Musterdepot-Feld

Status: live auf der Box (16.08.2026), Newsletter- und Musterdepot-Zweig verifiziert
Datum: 2026-08-16
Phase: 5 (Ingestion, repariert F013/F014/F102/F106)
Auslöser: Ralf — „der n8n workflow funktioniert nicht richtig, sowohl die
Zeitschriften als auch die Newsletter können nicht automatisch verarbeitet werden"

## 1. Befund

Der Trigger lief die ganze Zeit sauber, die Mails kamen an, und trotzdem stand seit
Wochen nichts Automatisches in der DB. Drei voneinander unabhängige Ursachen, alle
hinter demselben Symptom:

| # | Zweig | Ursache | Wirkung |
|---|---|---|---|
| 1 | Newsletter (alle 3) | `received_at` kam als RFC 2822, Pydantic parst nur ISO 8601 | HTTP 422, **jede** Ausgabe seit 08.08. verworfen |
| 2 | Musterdepot | n8n-Ausdruck las `$json.messageId` — ein Feld, das der IMAP-Node nicht hat | HTTP 422 „Field required", **nie** eine Zeile |
| 3 | Newsletter + Musterdepot | n8n liefert den Mail-Body doppelt UTF-8-kodiert | Mojibake im Pool, Trennlinien werden zu Impulsen |
| 4 | Zeitschriften | gespeicherte Playwright-Session vom 22.07. abgelaufen | Auto-Download fällt auf die manuelle Telegram-Aufforderung zurück |

Nr. 4 ist **kein Code-Fehler** und nicht von hier aus zu beheben — siehe §6.

### Wie der Befund zustande kam

`execution_entity`/`execution_data` in n8ns Postgres sind das Beweismittel: die
Executions stehen dort samt Mail und Node-Fehler. Auszählung über alle Executions
seit dem 06.08.:

- `cryptocrunch` 08./09./11./12./13./14.08. → HTTP-Node lief, **422**,
  `description: "Input should be a valid datetime or date, invalid character in year"`
- `musterdepot` 07.08. und 14.08. → **422**, `description: "Field required"`
- `marketscrunch`/`materialscrunch` → HTTP-Node lief nie; deren Zweige gibt es erst
  seit dem 15.08. (F106), und seitdem war Wochenende. Sie tragen denselben
  `received_at`-Ausdruck und wären am Montag genauso gescheitert.
- `publikation` 05./12./13.08. → HTTP-Node **erfolgreich**, `download_started`. Der
  Webhook war hier nie das Problem.

Die vier Ausgaben, die überhaupt in `newsletter_item` stehen, kamen alle **nicht**
über n8n: drei aus Ralfs `.eml`-Nachholung (F117), eine aus einem Verifikationslauf
zu F102. Der reguläre Weg hat noch nie eine Zeile geschrieben.

## 2. Ursache 1 — RFC 2822 vs. ISO 8601

n8ns IMAP-Node reicht den `Date`-Header unverändert durch. Was ankommt:

```
"received_at": "Thu, 13 Aug 2026 04:01:19 +0000 (UTC)"
```

`received_at: datetime.datetime | None` in `NewsletterNotification` nimmt ISO 8601.
Ergebnis: 422, und zwar bei jeder einzelnen Ausgabe.

**Warum das in CI grün war:** sämtliche Fixtures schickten
`"2026-08-07T04:01:35+00:00"`. Der Test hat einen Kontrakt geprüft, den der einzige
reale Aufrufer nie erfüllt hat. Der neue Test benutzt deshalb einen String, der
wörtlich aus einer Produktions-Execution kopiert ist.

**Fix serverseitig, nicht in n8n.** Der Kontrakt gehört der API, `parsedate_to_datetime`
ist dieselbe Funktion, die der `.eml`-Adapter aus F117 schon benutzt, und sie ist hier
testbar — der n8n-Ausdruck ist es nicht. Ein `{{ new Date(...).toISOString() }}` hätte
außerdem in vier Nodes gepflegt werden müssen.

## 3. Ursache 2 — der Musterdepot-Ausdruck

Live stand im Node:

```
"message_id": $json.messageId || $json.headers?.['message-id'] || $json['message-id']
```

Keines der drei Felder existiert in der Ausgabe des IMAP-Nodes; die Header liegen
unter `$json.metadata`. Alle drei Alternativen `undefined` ⇒ Feld fehlt im JSON ⇒ 422.

Die Repo-Vorlage `n8n/publications-mail-trigger.json` trägt seit F014 den richtigen
Ausdruck (`$json.metadata['message-id']`) — **live war er nie angekommen.** Genau die
Divergenz, vor der F106 §7 warnt: importiert wird der Live-Stand, nicht die Vorlage,
und wer die Vorlage danach nicht gegenprüft, merkt es nicht. Der Live-Node ist jetzt
auf den Vorlagen-Ausdruck gezogen; Repo und Box stimmen wieder überein.

## 4. Ursache 3 — n8n zerstört das Charset des Bodys

Der tieferliegende Fund, und der einzige, der stille Datenkorruption verursacht hat.
In `EmailReadImapV2.node.js`, Format „Simple":

```js
const partData = await connection.getPartData(message, part);
return partData.toString();     // das charset=utf-8 des Parts wird ignoriert
```

Der Body kommt dadurch UTF-8-als-Latin-1 an: `Bestände` → `BestÃ¤nde`,
`—` → `â€"`. Nachgewiesen an neun Executions (alle morningcrunch-Ausgaben **und**
die Musterdepot-Mail); Header sind nicht betroffen, die dekodiert n8n per RFC 2047.

Zwei Folgen, die zweite ist die unangenehme:

1. Verlagstext mit kaputten Umlauten im Research-Pool.
2. **Die Trennlinien `———` werden nicht mehr als Trennlinien erkannt** und landen als
   eigene „Impulse" in `newsletter_item`. Live gemessen: dieselbe Ausgabe ergab 22
   statt 18 Impulse, die vier zusätzlichen waren reine Trennstriche.
3. Beim Musterdepot zerlegt es den `–` in „– WKN" und damit die Regex:
   `parse_transactions` fand **0** Transaktionen — der Zweig wäre also selbst mit
   korrigiertem `message_id` leer geblieben.

**Fix:** `value.encode("latin-1").decode("utf-8")`, und nur übernehmen, wenn der
Round-Trip vollständig gelingt. Ein unbeschädigter Body scheitert zuverlässig an
einer der beiden Stufen — diese Newsletter sind voller Emojis, die Latin-1 gar nicht
darstellen kann, und reiner Umlaut-Text ergibt kein gültiges UTF-8. Beide Fälle sind
als Test festgehalten.

**Die Wurzel läge in n8n**, nicht bei uns: Format „Resolved" lässt `simpleParser` über
die komplette Rohmail laufen und dekodiert korrekt. Das ändert aber die komplette
Ausgabestruktur des Nodes (`$json.from` wird ein Objekt, `textPlain` → `text`,
`metadata['message-id']` → `messageId`) und damit alle fünf Filter und vier
HTTP-Nodes — blind umzustellen, mit einem stillen Fehlermodus (Filter greift nicht
mehr) und ohne Testmöglichkeit bis zur nächsten echten Ausgabe. Bewusst nicht
gemacht; als Entscheidungsvorlage für Ralf in §7 notiert.

## 5. Testdefinition (vor der Umsetzung geschrieben)

In `tests/api/test_routes_ingestion.py`:

1. `..._accepts_the_rfc2822_date_n8n_actually_sends` — Produktionsstring, 202, naives UTC.
2. `..._musterdepot_accepts_the_rfc2822_date_and_converts_to_utc` — `+0200` → UTC-1400.
3. `..._still_rejects_an_unparsable_date` — kaputtes Datum bleibt 422, fällt **nicht**
   still auf „jetzt" zurück.
4. `..._repairs_n8ns_double_encoded_body` — beschädigter Body ⇒ Umlaute korrekt **und**
   ein Impuls statt zwei (die Trennlinie ist wieder eine Trennlinie).
5. `..._leaves_an_intact_body_alone` — Gegenprobe mit Emoji.
6. `test_repair_mail_body_keeps_plain_german_text_untouched` — der Grenzfall ohne
   Emoji, den der Round-Trip theoretisch falsch behandeln könnte.

Der bestehende ISO-Test bleibt unverändert und deckt weiterhin den ISO-Pfad ab.

### Ergebnis

**1178 passed**, Coverage 91,69 % (Gate 90), `src/risk`+`src/broker` 100 % Branch,
`ruff`, `ruff format`, `mypy src` sauber.

**Ein Fund beim Testen:** die tz-Normalisierung zuerst in den `BeforeValidator` gelegt
— falsch, Pydantics eigenes ISO-Parsing läuft danach, und ein ISO-Datum mit Offset
landete dadurch als lokale Wandzeit in der DB (04:01 UTC → 06:01 gespeichert). Der
bestehende F102-Test hat das sofort gefangen. Aufgeteilt in `BeforeValidator`
(RFC 2822 → datetime) und `AfterValidator` (→ naives UTC), damit beide Eingabeformate
durch dieselbe Normalisierung laufen.

## 6. Live-Verifikation auf der Box (16.08.2026)

- `api` neu gebaut und ausgerollt.
- **Newsletter, echter Payload:** die am 13.08. mit 422 gescheiterte Execution (1451)
  wurde mit exakt ihrem gespeicherten Body erneut an den Webhook geschickt:
  `202 {"newsletter":"cryptocrunch","items":18,...}` — dieselbe Zahl, die F117 für
  diese Ausgabe aus der `.eml` bekommen hat. Vor dem Charset-Fix: 22 Impulse mit
  Mojibake. DB-Kontrolle: Umlaute und Emojis korrekt, keine Trennlinien-Zeilen.
- **Musterdepot, echte Mail, ohne Seiteneffekt:** Body aus Execution 1498 gezogen und
  offline durch `_repair_mail_body` + `parse_transactions` geschickt (kein DB-Write,
  kein Telegram-Alert): unrepariert 0 Transaktionen, repariert genau eine —
  `KAUF SpaceX A42D4F 140 Stück zu je 122,98 Euro`.
- **n8n-Workflow** nach dem Verfahren aus F106 §7 geändert: Live-Stand exportiert
  (Backup `/tmp/n8n_backup_20260816_182005.json` auf der Box), genau ein Node
  gepatcht, importiert, `update:workflow --active=true`, Container neu gestartet.
  Alle drei aktiven Workflows im Log sauber reaktiviert, inklusive „Abfallkalender"
  und „Tägliche Infomail".

### `synced_at` — Fallstrick beim Nachspielen

`research_synthesis` fenstert Newsletter über **`synced_at`**, nicht über
`received_at`. Ein nachgespielter Payload bekommt damit „jetzt" und würde im nächsten
Zyklus als frische Research ausgeliefert — die 18 Impulse vom 13.08. hatte der
15.08.-18:00-Zyklus aber schon gesehen. Nach Ralfs Entscheidung auf den ursprünglichen
Wert aus dem F117-Lauf (`2026-08-15 13:49:34`) zurückgesetzt; Text bleibt korrigiert,
nichts läuft doppelt.

**Kein Nachziehen des Rückstands** (Ralfs Entscheidung, 16.08.): die Bodies der
gescheiterten Ausgaben vom 06.–14.08. liegen zwar noch in n8ns Execution-Store, aber
über `synced_at` kämen rund 150 bis zu zehn Tage alte Impulse gesammelt als frische
Research in den nächsten Zyklus. Das verzerrt Entscheidungen und damit den
Persona-Vergleich (Invariante #10).

## 7. Offen — braucht Ralf

**Zeitschriften-Auto-Download (Ursache 4).** Im `api`-Container reproduziert:

```
SESSION EXPIRED: Stored session no longer authenticates
(landed on https://login.boersenmedien.de/?apiKey=...)
```

`data/ingest/boersenmedien/session_state.json` ist vom 22.07.2026. Das ist der von
F078 vorgesehene, erwartete Ablauf, kein Bug — der Webhook antwortet weiter mit
`download_started`, der Download scheitert, und Ralf bekommt die Telegram-Aufforderung,
die PDF von Hand abzulegen. Genau das ist seit dem 05.08. passiert: die abgelegten
PDFs gehören alle dem Host-User, nicht dem Container.

Behebbar nur durch ihn — das Login hängt hinter Cloudflare Turnstile, und Claude gibt
grundsätzlich keine Zugangsdaten ein. Ablauf steht im Docstring von
`scripts/boersenmedien_session.py`: Chrome-Profil starten, anmelden mit „Angemeldet
bleiben?", Skript laufen lassen, `session_state.json` auf die Box kopieren, `chmod 640`.

**Kein Warnsignal vor dem Ablauf.** Die Session stirbt lautlos und fällt erst beim
nächsten Heft auf. Ein wöchentlicher Check, der `list_subscriptions` nur anfasst und
bei `BoersenmedienSessionExpired` einen Telegram-Alert schickt, wäre billig. Nicht in
diesem Feature gebaut — eigener Scope, gehört Ralf vorgelegt.

**n8n-Format „Resolved"** (§4): würde die Charset-Reparatur überflüssig machen, kostet
aber eine komplette Überarbeitung aller neun Nodes. Nur sinnvoll, wenn ohnehin am
Workflow gearbeitet wird.

## 8. Rollback

- **Code:** die beiden `Annotated`-Typen (`MailDate`, `MailBody`) wieder auf `str`
  bzw. `datetime | None` setzen — dann gilt exakt das alte Verhalten (inkl. 422).
  Kein Schema-Change, keine Migration, keine neue Env-Var, kein Config-Flag.
- **n8n:** `/tmp/n8n_backup_20260816_182005.json` auf der Box zurückimportieren,
  `update:workflow --active=true`, Container neu starten.
- Beide Teile sind unabhängig voneinander zurücknehmbar.
