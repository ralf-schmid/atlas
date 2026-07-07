# F014 — Musterdepot-Transaktions-Ingestion

Status: umgesetzt und live verifiziert
Datum: 2026-07-06
Phase: 3

## 1. Zieldefinition

Erweiterung von F013: DER AKTIONÄR postet Käufe/Verkäufe aus seinem eigenen
Echtgeld-Musterdepot per Mail. Andere Mail-Art als die "Neuer Inhalt"-Benachrichtigungen:

- Absender: `noreply@boersenmedien.de` (nicht `no-reply@e.boersenmedien.com`)
- Betreff: konstant `Neue Transaktion`
- Body enthält eine Zeile im Muster
  `Transaktion <AKTION> <Name> – WKN <WKN> – <Stückzahl> Stück zu je <Preis> <Währung>`,
  z. B. `Transaktion TEILVERKAUF Moderna – WKN A2N9D9 – 75 Stück zu je 68,31 Euro`
  (verifiziert an einer echten Beispielmail von Ralf).

Ziel: diese Transaktionen strukturiert erfassen (als zukünftiges Recherche-Signal,
siehe Kritische Betrachtung) und Ralf per Telegram informieren — **ohne** dass daraus
jemals automatisch eine ATLAS-Order wird.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #2 Privilege Separation (nur der Handels-Agent platziert Orders) | ja, zentral | Dieses Feature hat **keinerlei** Order-Fähigkeit — es parst, persistiert, alarmiert. Kein Code-Pfad hier ruft `src/broker` auf. Die Musterdepot-Transaktion ist ein fremdes Echtgeld-Depot (Börsenmedien AG), keine ATLAS-Order-Quelle. |
| #3 Keine Order ohne persistierte Decision | ja | Bleibt unberührt — es gibt keine Order, also auch keine Decision-Pflicht hier. Falls das später (P4) ein Recherche-Input für Personas wird, entscheidet weiterhin jede Persona selbst per eigener Decision, ob/wie sie reagiert. |
| #10 Fairness (kein Informationsvorsprung) | ja | Landet in einer für alle Personas gleichermaßen lesbaren Staging-Tabelle (`musterdepot_transaction`), analog zu `edgar_filing`/`publication_article`. Aktuell liest noch kein Agent davon (P4 nicht gebaut) — sobald doch, gilt derselbe Shared-Research-Pool wie bei jeder anderen Quelle. |
| #9 Untrusted Content | ja | Fremdinhalt (E-Mail-Text). Der Telegram-Alert-Text enthält nur die geparsten, strukturierten Felder (Aktion/Name/WKN/Menge/Preis), nicht den rohen HTML-Text — reduziert Injection-Fläche zusätzlich zur generellen Regel "nie in System-Prompts von schreibberechtigten Agenten". |
| Kein Informationsvorsprung/keine Sonderbehandlung | ja | Gleicher Webhook-Mechanismus, gleicher Shared Secret wie F013 — keine persona-spezifische Verarbeitung. |

**Design-Entscheidungen:**
- **Eigene Tabelle `musterdepot_transaction`, nicht `research_item`:** `research_item`
  verlangt eine NOT-NULL-FK auf `cycle` — Cycles entstehen erst durch den (noch nicht
  gebauten) P4-Orchestrator. Genau das gleiche Argument wie bei `edgar_filing` &
  Co. (F009 ff.): Rohdaten zuerst in eine Staging-Tabelle, `research_item`-Synthese
  ist P4-Arbeit.
- **Separater Endpoint `POST /api/ingestion/publications/musterdepot-notify`** statt
  Wiederverwendung von `/publications/notify`: andere Payload-Form (braucht
  `message_id` + vollen Mailtext, nicht nur den Betreff), andere Validierungslogik
  (Regex-Fund statt Zeitschriften-Zuordnung). Teilt sich aber den Webhook-Secret-Check
  (`_check_webhook_secret`, aus dem F013-Code extrahiert) und den Telegram-Alert-Weg.
- **Regex statt LLM zum Parsen:** die Zeile ist strukturell stabil genug für ein
  Muster (`Transaktion AKTION NAME – WKN X – MENGE Stück zu je PREIS WÄHRUNG`) —
  passt zu CLAUDE.md "Finanz-Kennzahlen vom LLM ausrechnen lassen" verboten,
  Berechnungen/Extraktion gehören in Code-Tools.
- **HTML-Entkopplung (`strip_html`):** die reale Mail verteilt "Transaktion",
  "TEILVERKAUF" und "Moderna" auf separate `<p>`/`<strong>`-Tags
  (`<strong>Transaktion</strong></p><p><strong>TEILVERKAUF</strong></p>...`) — Tags
  durch Leerzeichen ersetzen + `html.unescape()` (wegen `&nbsp;` direkt neben dem
  Trennstrich) + Whitespace normalisieren fügt das wieder zu einer matchbaren Zeile
  zusammen. Funktioniert auf HTML *und* Plain-Text gleichermaßen (Tag-Strip ist ein
  No-Op ohne Tags).
- **Mehrere Transaktionen pro Mail unterstützt** (`seq`-Feld, Liste statt Optional) —
  auch wenn der Regelfall vermutlich eine pro Mail ist, kostet die Mehrfach-Erkennung
  nichts und verhindert stillen Datenverlust, falls doch mal mehrere gepostet werden.
- **Alert-Text ohne Handlungsaufforderung**, mit explizitem Disclaimer ("Nur Info aus
  einem fremden Echtgeld-Depot — keine ATLAS-Order, kein automatischer Trade") — die
  Nachricht könnte sonst wie eine Kauf-/Verkaufsempfehlung *für ATLAS* missverstanden
  werden.

**Kosten:** keine LLM-Calls. **Fairness:** ein Ingestion-Pfad, ein Datensatz, keine
Persona bevorzugt.

## 3. Testdefinition (vor Umsetzung)

`tests/ingestion/test_musterdepot_transactions.py`:
1. `strip_html` flacht Tags ab und dekodiert Entities (`&nbsp;`) — gegen einen
   Ausschnitt der echten Mail-HTML verifiziert.
2. `parse_transactions` extrahiert die echte Mail-Transaktion korrekt (Aktion, Name,
   WKN, Menge, Preis, Währung).
3. `parse_transactions` verarbeitet deutsches Zahlenformat mit Tausendertrennzeichen
   (`1.234` → `1234`).
4. `parse_transactions` liefert `[]` für Text ohne Transaktionszeile.
5. `parse_transactions` findet mehrere Transaktionen in einem Text (`seq` 0, 1, ...).
6. `format_transaction_alert` enthält Aktion+Name+WKN und den
   "keine ATLAS-Order"-Disclaimer.
7. `sync_musterdepot_transactions` mit leerer Liste → `0`.
8. `sync_musterdepot_transactions` zweimal mit derselben `message_id`/`seq`, aber
   unterschiedlichen Werten → genau eine Zeile, mit den Werten des zweiten Laufs
   (Idempotenz-Nachweis).

`tests/api/test_routes_ingestion.py` (Ergänzung):
9. Fehlender `X-Webhook-Secret` → `401`.
10. Body ohne erkennbare Transaktionszeile (auch mit korrektem Secret) → `422`.
11. Gültige Transaktion + korrektes Secret → `202`, Persistenz in
    `musterdepot_transaction` verifiziert, `send_alert` aufgerufen.

## 4. Implementierung

`src/ingestion/musterdepot_transactions.py` (`Transaction`, `strip_html`,
`parse_transactions`, `format_transaction_alert`, `sync_musterdepot_transactions`),
`src/api/routes_ingestion.py` (`POST /api/ingestion/publications/musterdepot-notify`,
gemeinsame `_check_webhook_secret`-Hilfsfunktion mit F013), `src/db/models.py`
(`MusterdepotTransaction`), Migration
`alembic/versions/b8bf07d06546_add_musterdepot_transaction.py`,
`n8n/publications-mail-trigger.json` (zweiter Zweig: neuer Filter-Node + neuer
HTTP-Request-Node, beide vom selben IMAP-Trigger gespeist).

## 5. Testdurchlauf

`uv run pytest tests/ingestion/test_musterdepot_transactions.py tests/api/test_routes_ingestion.py -q`
→ 15 passed (8 neue Unit-Tests + 7 API-Tests inkl. F013s bestehenden). `uv run pytest -q`
(Gesamtsuite) → 252 passed, 2 deselected. `uv run ruff check`/`ruff format --check` →
sauber. `uv run mypy src` → sauber. Migration im upgrade→downgrade→upgrade-Zyklus
verifiziert (keine ENUM-Typen). Parser zusätzlich gegen die reale
`Neue Transaktion.eml`-Beispielmail verifiziert (nicht nur synthetische Test-Fixtures)
— extrahiert korrekt "TEILVERKAUF Moderna, WKN A2N9D9, 75 Stück @ 68,31 Euro".

**Update (2026-07-06): vollständig live verifiziert.** Workflow in Ralfs n8n-Instanz
importiert, Feldnamen-Fehler in der ersten Version (`$json.messageId` etc. statt
`$json.metadata['message-id']`) durch Lesen des `emailReadImap`-Node-Quellcodes im
laufenden n8n-Container gefunden und behoben (Commit `8aed520`). Nach der Korrektur
läuft der Workflow durch — Ralf hat den fehlerfreien Durchlauf bestätigt.

**Rein technischer Rest (kein Blocker):**
- Scheduler/Orchestrator-Anbindung an P4-Agenten (research_item-Synthese) — wie bei
  F008–F013, planmäßig erst mit dem P4-Orchestrator.

## 6. Rollback-Pfad

Additives Feature, kein bestehender Code-Pfad wird geändert (neuer Endpoint, neue
Tabelle, n8n bekommt nur einen zusätzlichen, unabhängigen Zweig). Rollback = Commit
zurücknehmen + `alembic downgrade -1`; in n8n reicht das Deaktivieren des neuen
Zweigs/Nodes.
