# F117 — Newsletter-Ausgaben aus `.eml`-Dateien nachholen

Status: live auf der Box (15.08.2026) — wartet auf Ralfs Dateien
Datum: 2026-08-15
Phase: 5 (Ingestion, ergänzt F102/F106)
Auslöser: Ralf — die Ausgaben vom 14./15.08. liegen noch in seinem Postfach

## 1. Zieldefinition

Eine Newsletter-Ausgabe, die am n8n-IMAP-Trigger vorbeigelaufen ist, soll sich
aus der gespeicherten Mail nachholen lassen.

Der reguläre Weg ist n8n → `POST /ingestion/newsletter/notify` → `newsletter_item`.
Der hat ein Loch, das F106 §6 schon beschreibt: eine Ausgabe, die **vor** dem
Anlegen ihres n8n-Zweigs ankommt, wird vom Trigger als gelesen abgehakt
(`lastMessageUid`) und **kommt nicht von selbst nach**. Genau das ist am
15.08.2026 für `materialscrunch` und `marketscrunch` passiert.

**Scope:** ein Adapter, der aus einer `.eml`-Datei die vier Felder zieht, die der
Webhook-Kontrakt braucht, plus ein Skript, das ein Verzeichnis abarbeitet.
**Non-Scope:** Postfach-Zugriff (kein IMAP-Client, keine neuen Credentials), die
Parser-Logik selbst, der n8n-Workflow.

## 2. Warum ein Adapter und kein zweiter Parser

Alles ab „hier ist der Plain-Text-Body" ist unverändert `crypto_newsletter` —
`identify_newsletter`, `parse_newsletter`, `sync_newsletter_items`. Ein zweiter
Parser würde von dem abdriften, den der Webhook benutzt, und dann hinge es vom
Einlieferungsweg ab, was im Research-Pool landet.

Das Neue ist ausschließlich die Mail-Zerlegung, und daran hängen die Fallstricke,
die eine echte Datei von dem sauberen String unterscheiden, den der Webhook
bekommt:

| Fallstrick | Umgang |
|---|---|
| multipart/alternative (HTML + Text) | `get_body(preferencelist=("plain",))` — HTML zu parsen ergäbe Markup-förmige Impulse |
| quoted-printable, `=C3=BC` | `get_content()` dekodiert samt Charset; sonst stünde `H=C3=BCtten` im Pool |
| `"Name" <adresse>` im From | `parseaddr` — `identify_newsletter` matcht auf die nackte Adresse |
| fehlende Message-ID | Fallback `file:<dateiname>`, damit der Upsert-Schlüssel `(message_id, seq)` eindeutig bleibt |
| Datum | `Date`-Header, nicht die Ingest-Zeit — sonst wäre eine Tage später nachgeholte Ausgabe falsch datiert |
| nur HTML, kein Text-Teil | `EmlError` statt „0 Impulse" — sonst sieht ein kaputter Input aus wie eine reine Werbe-Ausgabe |

**Untrusted Content (Invariante #9):** der Body ist verlagsgeschrieben. Nichts
hier führt ihn aus oder folgt ihm; er geht denselben Weg wie über den Webhook.

## 3. Was außerdem gefehlt hat

Zwei Dinge, die beim Verifizieren aufgefallen sind:

1. **`scripts/ingest_publications.py` konnte das nie.** Es scannt
   `PUBLICATIONS_INGEST_DIR` nach PDFs (`scan_ingest_directory`) und kennt weder
   das Newsletter-Verzeichnis noch `.eml`. Ralfs Beobachtung war korrekt; es war
   kein Fehler, sondern schlicht nicht gebaut.
2. **`/data/ingest/newsletter` war nicht in den Container gemountet.**
   `docker-compose.yml` kannte nur `publications` und `boersenmedien` — Dateien
   auf dem Host wären für das Skript unsichtbar geblieben. Mount ergänzt,
   read-only (das Skript liest nur, Aufräumen bleibt Handbewegung).

## 4. Testdefinition (vor der Umsetzung geschrieben)

`tests/ingestion/test_newsletter_eml.py`:

1. Die vier Felder werden korrekt extrahiert.
2. Display-Name wird abgestreift, und die Adresse matcht die echte Config.
3. multipart bevorzugt den Plain-Text-Teil.
4. quoted-printable und Umlaute überleben.
5. Nicht-UTF-8 (iso-8859-1) wird dekodiert.
6. `Date` wird zu naivem UTC (`05:59 +0200` → `03:59`).
7. Fehlendes Datum fällt auf „jetzt" zurück.
8. Fehlende Message-ID fällt auf den Dateinamen zurück.
9. Reine HTML-Mail wird mit `EmlError` abgelehnt.
10. Mail ohne Absender wird abgelehnt.
11. Das Verzeichnis-Scan findet `*.eml` sortiert, ignoriert andere Endungen und
    Unterverzeichnisse; ein fehlendes Verzeichnis ist leer, kein Fehler.
12. **Ende-zu-Ende (DB):** eine `.eml` mit echtem Ausgaben-Body erzeugt
    `newsletter_item`-Zeilen, der konfigurierte Werbeblock fliegt raus.
13. **Ende-zu-Ende ist idempotent:** zweimal laufen lassen ändert die Zeilenzahl
    nicht.

## 5. Verifikation

- **1170 passed**, Coverage 91,71 % (Gate 90), risk/broker-Branch 100 %,
  `ruff`, `ruff format`, `mypy src` sauber.
- **Trockenlauf auf der Box am 15.08.2026** mit einer synthetischen Ausgabe
  (quoted-printable, Display-Name im From, zwei Sektionen):

  ```
  _selftest.eml: marketscrunch, 2026-08-14 03:59, 2 Impuls(e) — DRY RUN, nichts geschrieben
  ```

  Damit sind die umgebungsabhängigen Teile nachgewiesen: Mount sichtbar,
  Container-User (UID 3001, Gruppe `familie`) darf lesen, Datei gefunden,
  Umlaute dekodiert, Absender erkannt, Datum aus dem Header. Testdatei danach
  entfernt, `newsletter_item` unverändert (0 Zeilen mit der Test-ID).
- **Noch offen:** Ralfs echte Ausgaben. Das Verzeichnis
  `/mnt/apps/docker/atlas/data/ingest/newsletter/` war am 15.08.2026 15:14 leer —
  der Kopiervorgang ist nicht durchgelaufen.

## 6. Bedienung

```bash
# 1. .eml-Dateien nach /mnt/apps/docker/atlas/data/ingest/newsletter/ legen
# 2. erst schauen, was passieren würde:
sudo docker compose exec -T api uv run python scripts/ingest_newsletters.py \
  /data/ingest/newsletter --dry-run
# 3. dann schreiben:
sudo docker compose exec -T api uv run python scripts/ingest_newsletters.py \
  /data/ingest/newsletter
```

Idempotent über `(message_id, seq)` — ein zweiter Lauf aktualisiert, statt zu
verdoppeln. Exit-Code 1, wenn mindestens eine Datei übersprungen wurde.

**Erst `--dry-run`**, weil eine Layout-Änderung sich als „0 Impulse" zeigt und
das nach einer Werbe-Ausgabe aussieht.

## 7. Rollback

Skript nicht aufrufen — es läuft nichts automatisch. Der Compose-Mount ist
read-only und additiv; ein Entfernen kostet nur einen `up -d`. Kein
Schema-Change, keine Migration.
