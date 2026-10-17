# Persona-Universum bei der Prompt-Auswahl berücksichtigen?

* Status: accepted (Option D, Ralf, 17.10.2026)
* Deciders: Ralf Schmid
* Datum: 2026-10-17
* Betrifft Invariante(n): **#10 Fairness** (unmittelbar)

## Kontext und Problemstellung

Laut [F120](../features/F120-guardian-cryptor-inaktivitaet.md) §5 Punkt 2 ist der
größte Hebel gegen die Inaktivität von CRYPTOR und GUARDIAN, dass eine Persona bei
der Auswahl ihrer 30 Prompt-Items ihr eigenes Universum zu sehen bekommt.
[F128](../features/F128-research-auswahl-fixes.md) hat die drei Fixes ohne
Invarianten-Berührung umgesetzt. Danach bleibt diese Lücke: Bei ~380
Indikator-Symbolen und ~6–8 Indikator-Slots je Zyklus sieht CRYPTOR seine zehn
Paare im Schnitt in etwa jedem fünften Zyklus. Er kann sein Charter
(Trend-Following auf Krypto-Majors) damit weiterhin kaum spielen.

Ein persona-spezifischer Filter auf den gemeinsamen Pool liegt genau auf der
Grenze, die Invariante #10 zieht: „gleiche Information, andere Brille" ist
erlaubt, „andere Information" nicht.

Zusätzlich gibt es eine frühere Entscheidung von Ralf (15.08.2026,
`docs/offene-punkte.md` §8b): **`universe_screen` bleibt LLM-Ermessen und wird
nicht deterministisch durchgesetzt.** Jede Option außer A muss sich dazu
verhalten.

## Entscheidungstreiber

* Saison 2 soll Strategien messen, nicht die Passung des Research-Pools (Abschlussbewertung §3.5)
* Invariante #10: Der gemeinsame Pool bleibt die einzige Quelle, keine Persona bekommt mehr Information
* Ralfs Entscheidung vom 15.08.: Das Universum ist kein harter Kauf-Filter
* Einfachheit und Nachvollziehbarkeit (Agent Trace muss zeigen, warum ein Item im Prompt war)

## Betrachtete Optionen

* **A** — Nichts weiter tun; F128-Rotation + `search_research_pool` (F045) genügen
* **B** — Harter Filter: Die Persona sieht nur Items ihres Universums
* **C** — Kontingent: ein fester, für alle gleich großer Anteil der 30 Slots
  (Vorschlag 10) wird mit Items aus dem eigenen Universum belegt, die übrigen 20
  laufen wie bisher über die gemeinsame Auswahl. Der Pool bleibt vollständig
  durchsuchbar, Käufe außerhalb des Universums bleiben möglich.
* **D** — Assetklasse als eigener Bucket: `technical_indicator` wird für **alle**
  Personas in Krypto und Aktien getrennt (F116-Paarformat), ohne jede
  persona-spezifische Logik

## Bewertung

| | A | B | C | D |
|---|---|---|---|---|
| Invariante #10 | unberührt | **verletzt** (andere Information) | berührt, vertretbar: dieselbe Quelle, dieselbe Slot-Zahl, nur andere Priorisierung | unberührt |
| Ralfs Entscheidung 15.08. | konform | widerspricht (harte Durchsetzung) | konform: priorisiert die Sicht, sperrt keinen Kauf | konform |
| hilft CRYPTOR | kaum | ja | ja | ja (~3–4 Krypto-Indikatoren je Zyklus) |
| hilft GUARDIAN | kaum | nur mit Large-Cap-Liste, die es nicht gibt | nur mit Large-Cap-Liste, die es nicht gibt | nein |
| Aufwand | 0 | klein | mittel (Universums-Definition je Persona, Trace-Kennzeichnung) | klein |

GUARDIANs `universe_screen` (10 Jahre Gewinnhistorie, Fair-Value-Abschlag)
lässt sich aus den vorhandenen Daten nicht deterministisch auswerten (F111 §9.4:
die Daten fehlen). B und C helfen GUARDIAN deshalb erst mit einer gepflegten
Symbol-Liste. Das wäre eine eigene Entscheidung.

## Entscheidung

Gewählt: **Option D**, umgesetzt als [F129](../features/F129-krypto-indikator-bucket.md).
C bleibt als Option, falls nach den ersten zwei Wochen von Saison 2 GUARDIAN oder
CRYPTOR weiterhin praktisch nicht handeln. D löst den CRYPTOR-Fall ohne
Invarianten-Berührung und ohne Konflikt mit der Entscheidung vom 15.08. B ist mit
Invariante #10 nicht vereinbar.

### Konsequenzen (für D)

* Gut, weil eine einheitliche Regel ohne Persona-Bezug genügt und kein
  `charter_version`-Bump nötig ist
* Schlecht, weil die Aktien-Personas ~3–4 Krypto-Indikatoren je Zyklus sehen, mit
  denen sie nichts anfangen können. Diese Slots fehlen ihnen für Aktien.
* Folgearbeit: F129 (umgesetzt 17.10.2026), Trace-Nachweis nach dem Deploy
