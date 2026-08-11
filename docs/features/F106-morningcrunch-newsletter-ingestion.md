# F106 — Zwei weitere Tages-Newsletter (materialscrunch, marketscrunch)

Status: **Zieldefinition** (Schritt 1 nach ARCHITECTURE.md §10 — noch keine Umsetzung)
Datum: 2026-08-11
Auslöser: Ralf, zwei Beispielausgaben vom 11.08.2026

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

**Warum das ohne viel neuen Code gehen sollte:** F102 hat die Pipeline bereits
**mehr-Newsletter-fähig** gebaut. `config/ingestion.yaml` führt unter
`newsletters:` eine Liste, jeder Eintrag mit `slug`, `sender`, `subject_marker`,
`drop_sections`, `blocked_link_domains`, `single_item_sections`, `ticker_map`;
`identify_newsletter()` matcht auf den Absender, der Webhook
`/api/ingestion/newsletter/notify` und die Synthese in den Pool sind quellen-
agnostisch. Der Zielzustand ist also: **zwei Config-Einträge, zwei n8n-Zweige,
Verifikation gegen je eine echte Ausgabe** — plus die Parser-Anpassungen, die
sich aus §3 ergeben.

**Scope:** beide Newsletter als eigene `newsletter_slug`-Quellen in
`newsletter_item`, Ingestion über den bestehenden n8n-Mail-Trigger, Synthese in
den geteilten Pool wie bei F102.
**Non-Scope (unverändert aus F102):** kein Abrufen der verlinkten Artikel (der
Newsletter fasst jede Story selbst zusammen — das ist der Impuls), keine
Volltexte in UI/Repo, keine LLM-Zusammenfassung (Parser bleibt deterministisch),
keine persona-spezifische Filterung.

## 2. Kritische Betrachtung (vorläufig, vor Umsetzung zu schärfen)

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, geprüft | Beide landen im geteilten Pool, für alle sechs Personas identisch sichtbar. Dass Rohstoff-Impulse für VULTURE/CONTRA nützlicher sind als für CRYPTOR, ist Charter-Wirkung, kein Informationsvorsprung. |
| #9 Untrusted Content | ja, zentral | Verlagstext, potenziell feindlich. Weg wie F102: als getaggter Datenblock über `research_item.raw["excerpt"]` (600-Zeichen-Cap) in den Persona-Prompt, nie in einen System-Prompt, nie in die Nähe eines Order-Tools. |
| #3 kein Pfad zur Order | nein | Reine Research-Daten. |
| Webhook als Schreibkanal | ja | Unverändert: Secret-Header **und** Absender-Match (`identify_newsletter` → sonst 422). Zwei neue Absender erweitern die Allowlist um genau zwei Adressen. |
| Kosten | ja, zu beziffern | Zwei Ausgaben täglich, je grob 20–30 Impulse. F102 argumentiert, dass `source_type='newsletter'` einen eigenen Round-Robin-Bucket in `persona_analysis` (F047) hat und deshalb andere Quellen verdrängt statt den Prompt zu verlängern. **Das gilt jetzt nicht mehr ungeprüft:** drei Newsletter teilen sich denselben Bucket, der Bucket wird also dreifach belegt statt breiter. Siehe offene Frage 3. |

## 3. Zwei Befunde aus den Beispielausgaben, die den Aufwand bestimmen

**(a) Anderer Versanddienstleister als beim cryptocrunch — Parser-Risiko.**
F102 schneidet Abschnitte an beehiivs `######`-Überschriften im **text/plain**-Teil
(`_SECTION_RE`), und die geblockten Domains sind beehiiv-Domains
(`unsub.beehiiv.com`, `magic.beehiiv.com`). Die beiden neuen Ausgaben tracken über
`elinkb60.morningcrunch.de` bzw. `elink8d7.m.morningcrunch.de` — das ist nicht
beehiiv. Ob deren Plain-Part dieselben `######`-Anker hat, **lässt sich aus den
gelieferten RTF-Dateien nicht feststellen**: die zeigen die gerenderte
HTML-Variante (Abschnitte erscheinen dort als nackte Großbuchstaben-Zeilen, Links
als `*HYPERLINK "…"`), nicht den Plain-Part, den n8n schickt. Fällt der Anker weg,
parst die Ausgabe zu null Items — das ist der Unterschied zwischen „zwei
Config-Zeilen" und „zweite Abschnitts-Erkennung im Parser".

**(b) Instrument-Tagging greift hier praktisch nicht.**
Der bestehende Mechanismus zieht `$TICKER` aus dem Text und bildet ihn über
`ticker_map` auf handelbare Symbole ab — beim Krypto-Brief die natürliche Form
(`$BTC`, `$ETH`). In diesen beiden Ausgaben ist `$` überwiegend das
**Währungszeichen** („$19,8 Mrd.", „$365 Mrd."), und Unternehmen stehen als
Klartext-Namen im Fließtext („Berkshire Hathaway", „Alphabet", „TTI"). Über beide
Ausgaben zusammen finden sich exakt vier echte Ticker: `$TSLA`, `$SPCX`, `$BP`,
`$LLY`. Ohne Zusatzmechanik bekämen fast alle Impulse `instruments = []` — sie
sind dann im Pool, aber für die symbolbezogene Suche (`search_research_pool`,
F045) unsichtbar und keiner Position zuzuordnen. Genau die Lücke, die F105 für
die News gerade geschlossen hat.

## 4. Was ich von dir brauche, bevor es weitergeht

1. **Je eine Original-Mail als `.eml`** (bzw. „Quelltext anzeigen" → Datei), von
   materialscrunch und von marketscrunch. Ich brauche den `text/plain`-Teil, um
   Befund (a) zu klären; die RTF-Exporte reichen dafür nicht. Damit steht in
   einem Durchgang fest, ob es bei Config bleibt oder der Parser eine zweite
   Abschnitts-Erkennung braucht.
2. **Instrument-Tagging (Befund b) — deine Entscheidung.** Drei Wege:
   - *A (minimal):* nur `$TICKER` wie heute. Fast alles bleibt ungetaggt, dafür
     null Fehlzuordnungen und kein neuer Code.
   - *B (Namensabgleich, mein Vorschlag):* deterministischer Abgleich der
     Klartext-Namen gegen das handelbare Universum über eine gepflegte
     Namensliste (`Berkshire Hathaway → BRK.B`). Nutzt allen drei Newslettern und
     wäre auch für die Zeitschriften-Artikel nachnutzbar. Kostet ein eigenes
     kleines Feature und braucht Pflege.
   - *C:* erst A ausliefern, B als Folge-Feature, wenn sich im Review zeigt, dass
     die Impulse ohne Tag untergehen.
3. **Bucket-Frage (Kosten).** Sollen die drei Newsletter sich weiter einen
   `source_type='newsletter'` teilen (dann konkurrieren sie um dieselbe
   Prompt-Quote — günstig, aber cryptocrunch verliert Sichtbarkeit), oder bekommt
   jeder Newsletter einen eigenen `source_type` (mehr Impulse je Prompt, mehr
   Token)? Ich tendiere zum geteilten Bucket, weil der Kosten-Cap gerade erst
   angehoben wurde.
4. **Werbe-Abschnitte bestätigen:** Ich würde `ANZEIGE`, `MORE BRIEFINGS` und
   `APP-PFIFF` (Eigenwerbung für die Verlags-App, steht in beiden Ausgaben ganz
   oben) hart verwerfen. `STAT OF THE DAY` / `STAT OF THE WEEK` sind Inhalt und
   bleiben drin — Einspruch?
5. **Status des cryptocrunch-n8n-Zweigs.** F102 steht auf „n8n-Zweig offen". Wenn
   der noch nicht importiert/aktiv ist, ziehen wir alle drei Zweige in einem
   Rutsch nach, statt zweimal an derselben Workflow-Datei zu arbeiten.

## 5. Vorgesehene Abschnitts-Behandlung (Entwurf, hängt an §4)

| Newsletter | `single_item_sections` (zusammenhängende Analyse) | `drop_sections` |
|---|---|---|
| materialscrunch | DEEP DIVE, ZOOM IN | ANZEIGE, MORE BRIEFINGS, APP-PFIFF |
| marketscrunch | TOP STORY, MARKET MOVER | ANZEIGE, MORE BRIEFINGS, APP-PFIFF |

Alles Übrige (MATERIALS OVERVIEW, HOT STOCKS, WHAT TO WATCH, QUICK CATCH-UP,
STAT OF THE …) liefert wie beim cryptocrunch **einen Impuls je Bullet**.

`blocked_link_domains`: die beehiiv-Liste greift hier nicht, weil alle Links über
die Tracking-Domain des Verlags laufen — auch Abmelde- und Login-Links. Ob eine
Domain-Sperre überhaupt noch diskriminiert oder ob es einen anderen Marker
braucht, klärt sich mit der `.eml` aus §4.1.

## 6. Nächste Schritte (nach deiner Rückmeldung)

1. Testdefinition schreiben (vor der Umsetzung, §10) — Parser gegen je eine echte
   Ausgabe, Abschnitts-Zuordnung, Werbefilter, Idempotenz, Pool-Mapping.
2. Umsetzung: Config + ggf. zweite Abschnitts-Erkennung + zwei n8n-Zweige.
3. Verifikation gegen die echten Ausgaben, Rollout, Rollback-Pfad (n8n-Zweig
   deaktivieren = sofortiger Stopp ohne Deploy, wie F102).
