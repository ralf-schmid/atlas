# Paper-Startkapital frei auf 5.000 USD je Account setzbar — bestätigt

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-04
* Betrifft Invariante(n): keine

## Kontext und Problemstellung

ARCHITECTURE.md §3.1 setzt 5.000 USD Startkapital je Paper-Account voraus ("Startbetrag
beim Anlegen wählbar"). Zu verifizieren: erlaubt Alpaca das frei, oder gibt es einen festen
Default (z. B. 100.000 USD, wie im bereits bestehenden Paper-Account sichtbar)?

Im Dashboard (Account-Switcher → "New Paper Account") zeigt das Feld "Set Funds" den
Wertebereich **"$1 - $1,000,000"** als frei editierbares Eingabefeld.

## Entscheidungstreiber

* Einheitliches Startkapital je Persona für einen fairen Vergleich (Invariante 10, indirekt)

## Betrachtete Optionen

* Keine — reine Verifikation, kein Zielkonflikt gefunden

## Entscheidung

Bestätigt: 5.000 USD ist beim Anlegen eines neuen Paper-Accounts direkt im Feld "Set Funds"
einstellbar (Bereich $1–$1.000.000). Kein Fallback nötig.

### Konsequenzen

* Gut, weil keine Änderung an ARCHITECTURE.md §3.1 nötig ist.
* Folgearbeit: beim Anlegen der 3 nativen Paper-Accounts (siehe
  [ADR-0001](0001-alpaca-paper-account-limit.md)) "Set Funds" explizit auf 5.000 gesetzt
  lassen (Default nicht übernehmen — der bestehende Account PA3VUAQVF0N4 steht aktuell auf
  100.000 USD Default und muss ggf. neu angelegt oder angepasst werden, falls er einer
  Persona zugeordnet wird).
