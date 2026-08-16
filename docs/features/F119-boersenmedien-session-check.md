# F119 — Wöchentlicher Boersenmedien-Session-Check mit Telegram-Alert

Status: live auf der Box (16.08.2026), gegen die real abgelaufene Session verifiziert
Datum: 2026-08-16
Phase: 5 (Ingestion, ergänzt F078)
Auslöser: Ralf, nach dem Befund in F118 §7

## 1. Zieldefinition

Die gespeicherte Playwright-Session für konto.boersenmedien.com läuft periodisch ab.
Bis hierher ist sie **lautlos** gestorben: aufgefallen ist es erst, wenn das nächste
Heft nicht automatisch geladen wurde — beim letzten Mal drei Wochen später
(Session vom 22.07., bemerkt am 16.08.).

Ein wöchentlicher Job soll die Session anfassen und, wenn sie tot ist, per Telegram
melden — **bevor** die nächste Ausgabe kommt.

**Scope:** ein Scheduler-Job, ein read-only Portal-Aufruf, ein Alert-Text.
**Non-Scope:** die Session selbst erneuern (Cloudflare Turnstile, siehe §4), am
Auto-Download etwas ändern, andere abgelaufene Credentials überwachen.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #2/#3 kein Pfad zur Order | nein | Der Job liest eine Abo-Übersicht. Kein DB-Write, keine Decision, kein Order-Tool. |
| #9 Untrusted Content | am Rande | Es wird nur gezählt, wie viele Abo-Karten sichtbar sind; kein Portalinhalt geht in einen Prompt. Der Alert-Text enthält die Fehlermeldung (die URL, auf der die Navigation landete) — die geht an Telegram, nicht an ein LLM. |
| #10 Fairness | nein | Betrifft eine Quelle, die allen Personas gemeinsam ist. |
| Kosten | nein | Kein LLM-Call. Ein Chromium-Start pro Woche. |
| Kaufaktionen | **ja, bewusst** | Die Abo-Seite trägt „In den Warenkorb"-Links (F078 hat den Selektor deshalb eingegrenzt). Der Check bleibt auf der Übersichtsseite stehen und klickt nichts — er ruft ausschließlich `list_subscriptions()`. |

## 3. Zwei Entscheidungen

**(a) Alert beim ersten Lauf, nicht nach zwei in Folge.** Alle anderen
Ingestion-Jobs alarmieren erst nach zwei Fehlschlägen hintereinander
(`_run_with_failure_alert`, F035) — die Regel schluckt transiente Aussetzer. Eine
abgelaufene Session ist aber kein Aussetzer: sie ist exakt der Zustand, für den
dieser Job gebaut wurde, sie heilt nicht von selbst, und bei einem Lauf pro Woche
würde die Regel den Alert um sieben Tage verzögern — also hinter die nächste Ausgabe,
womit der Vorlauf weg wäre, der der ganze Zweck ist.

`BoersenmedienSessionExpired` wird deshalb im Job **abgefangen** und sofort gemeldet.
Alles andere (Portal down, Playwright-Crash) fliegt weiter und läuft durch den
normalen 2×-Vertrag. Beide Wege sind getestet.

Nicht dedupliziert: bleibt die Session tot, meldet der Job auch nächste Woche wieder.
Stille würde „erledigt" heißen.

**(b) Nur `list_subscriptions`, kein Probe-Download.** Ein Download wäre der
schärfere Test, würde aber wöchentlich zweistellige Megabytes ziehen und die
Ausgaben-Seite mit ihren Kauf-Links anfassen. Der Login-Redirect, den `_goto`
erkennt, passiert schon bei der ersten Navigation — die Übersichtsseite reicht als
Nachweis vollständig aus.

Der Browser-Aufbau (`_open_portal`) ist jetzt geteilt, damit Check und Download sich
identisch authentifizieren. Ein Check, der die Session anders öffnet als der
Download, prüft nicht den Download.

## 4. Was der Job nicht kann

Er kann die Session **nicht erneuern**. Das Login hängt hinter Cloudflare Turnstile,
und ein Playwright-Chromium wird dort ohnehin geblockt (F078 §2.2, live gemessen).
Deshalb ist der Alert selbst die vollständige Handlungsanweisung: er trägt den
Grund, die Konsequenz (bis dahin kommt die manuelle Ablage-Aufforderung) und die
drei Schritte zum Erneuern.

## 5. Testdefinition (vor der Umsetzung geschrieben)

In `tests/ingestion/test_scheduler.py`:

1. `..._alerts_on_the_first_expired_run` — ein Lauf, ein Alert, Text nennt Grund und Skript.
2. `..._keeps_reminding_while_the_session_stays_dead` — zwei Läufe, zwei Alerts.
3. `..._stays_silent_while_the_session_is_valid` — kein Alert, kein Rauschen.
4. `..._treats_a_broken_portal_as_an_ordinary_job_failure` — `RuntimeError`: erster
   Lauf still, zweiter meldet „2x in Folge". Die Abgrenzung zwischen „abgelaufen"
   und „kaputt" ist der Kern des Features.
5. `..._is_not_registered_when_disabled` — Rollback-Schalter.
6. `..._runs_weekly_on_the_configured_day` — Montag, 07:30 America/New_York.

In `tests/ingestion/test_publications_download.py`:

7. `test_format_session_expired_alert_says_how_to_renew`.

Dazu die bestehende Job-ID-Menge um `ingestion-publications-session-check` ergänzt.

### Ergebnis

**1185 passed**, Coverage 91,70 % (Gate 90), `src/risk`+`src/broker` 100 % Branch,
`ruff`, `ruff format`, `mypy src` sauber.

## 6. Live-Verifikation (16.08.2026)

Der beste denkbare Testfall lag vor: die Session auf der Box **war** abgelaufen
(F118 §7). Der Job wurde im `scheduler`-Container von Hand ausgelöst und hat genau
das getan, wofür er gebaut ist:

```
WARNING Boersenmedien session expired: Stored session no longer authenticates
        (landed on https://login.boersenmedien.de/?apiKey=...)
INFO    HTTP Request: POST https://api.telegram.org/...sendMessage "HTTP/1.1 200 OK"
```

Kein DB-Write, kein Download. Der Gegenbeweis (gültige Session ⇒ Job läuft still
durch) steht noch aus — er kommt, sobald die Session wirklich erneuert ist.

### Beim ersten Live-Lauf gefunden: die Env-Var fehlte auf diesem Service

Der allererste Versuch endete mit `KeyError: 'BOERSENMEDIEN_SESSION_STATE'`.
`docker-compose.yml` setzte die Variable und den `boersenmedien`-Mount nur auf `api`
— der Job läuft aber im `scheduler`. Ohne diesen Testlauf wäre der Fehler erst am
Montag aufgetreten, und zwar als generischer „2x in Folge"-Alert zwei Wochen später,
also mit genau der Verzögerung, die das Feature abschaffen soll.

Zwei Konsequenzen:

1. `docker-compose.yml`: Variable und Read-only-Mount auf `scheduler` ergänzt
   (⇒ TRUENAS_HOMELAB.md im `ugreen-Box`-Repo nachgezogen).
2. Der Pfad wird jetzt **bei der Registrierung** aufgelöst, nicht im Job. Fehlt die
   Variable, wird der Job nicht registriert und der Grund steht beim
   Container-Start im Log statt zwei Wochen später in einem irreführenden Alert.
   Als Test festgehalten (§5, Punkt 7).

### Nebenbefund: die erneuerte Session-Datei authentifiziert nicht

Die Datei auf der Box wurde am 16.08. um 18:25 neu geschrieben (2.274 → 7.747 Bytes),
authentifiziert aber weiterhin nicht. Cookie-Inspektion (nur Namen/Domains/Ablauf,
nie Werte):

- **kein einziges Cookie für `konto.boersenmedien.com`** — genau den Host, den der
  Download aufruft. Alle 24 stammen von `boersenmedien.de`/`www`/`login`.
- Das Auth-Cookie `.AspNetCore.Cookies` auf `login.boersenmedien.de` ist am
  **12.08.2026** abgelaufen; alle Zeitstempel stammen vom **29.07.**

Das Chrome-Profil war also seit dem 29.07. nicht mehr am Portal angemeldet — der
Export hat einen alten Stand herausgeschrieben, keine frische Anmeldung.

**Fallstrick im Skript, dabei aufgefallen:** `scripts/boersenmedien_session.py`
schreibt `session_state.json` **vor** dem Verifikationslauf und gibt danach nur
`return 1` mit einer Meldung aus. Eine noch funktionierende Datei wird damit von
einer kaputten überschrieben, bevor irgendjemand merkt, dass der Export nichts
taugt. Hier war die alte ohnehin tot, also ohne Schaden — der Ablauf gehört
trotzdem umgedreht (erst in eine temporäre Datei, verifizieren, dann ersetzen).
Nicht in diesem Feature geändert.

## 7. Rollback

`config/ingestion.yaml` → `schedule.publications_session_check.enabled: false`,
danach Rebuild (config ist ins Image gebacken) und `up -d scheduler`. Der Job wird
dann gar nicht erst registriert; am Auto-Download ändert sich nichts. Kein
Schema-Change, keine Migration, keine neue Env-Var.
