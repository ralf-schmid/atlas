# F069 — CHARTIST-Universum: min. 100 Werte live gegen aktienfinder verifiziert

Status: umgesetzt, live verifiziert
Datum: 2026-07-11
Phase: 5

## 1. Zieldefinition

Ralfs Rückmeldung zu F066: *"die Lösung von F066 gefällt mir immer noch
nicht. auch 16 mögliche Werte sind ein viel zu enges Feld. Wir brauchen hier
min. 100 mögliche Werte. Idealerweise live auf aktienfinder mit dem
Bezahlaccount prüfen."*

Berechtigte Kritik an F066s Framing: die 16 handverlesenen Large-Caps waren
zum Zeitpunkt von F066 tatsächlich "die" CHARTIST-Basis. Seitdem hat
[F068](F068-aktienfinder-screener-discovery.md) aber bereits eine
grundlegend andere, deutlich breitere Quelle eingehängt
(`resolve_symbol_universe`, dieselbe Vereinigung wie F066 selbst nutzt) —
F066s Dokumentation wurde nur nie nachgezogen, um das korrekt
widerzuspiegeln, und niemand hatte explizit nachgerechnet, wie viele der
F068-Kandidaten tatsächlich CHARTISTs `price > 10 $`-Kriterium (in echten
Alpaca-USD-Kursen, nicht aktienfinders EUR-Anzeige) erfüllen.

**Scope:** live nachweisen, dass das CHARTIST-Universum bereits ≥ 100 Werte
umfasst; falls nicht, die aktienfinder-Discovery-Parameter erhöhen;
Dokumentation korrigieren, damit F066s statische Liste nicht mehr als "die"
Lösung dargestellt wird.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | nein | Reine Verifikation + Config-Parameter-Anpassung des bereits bestehenden, gemeinsamen F068-Pfads — keine neue Quelle, keine Persona-exklusive Änderung. |
| Keine stillen Annahmen bei Geld-Themen | ja, zentral | aktienfinders Grid zeigt Kurse in **EUR**, Alpaca/`market_bar` in **USD** — eine EUR-Zahl direkt gegen die 10-$-Schwelle zu prüfen wäre genau die Art stiller Fehlannahme, die CLAUDE.md verbietet. Die Prüfung hier läuft ausschließlich gegen `market_bar.close` (echte, von Alpaca gelieferte USD-Kurse), nie gegen aktienfinders EUR-Anzeigefeld. |

**Design-Entscheidungen:**
- **Keine EUR-Preisfilterung in der Discovery selbst** (siehe oben) — die
  Freigabe bleibt zweistufig wie in F068 angelegt: Region als Vorfilter,
  Alpaca-Tradability + (hier neu geprüft) echter USD-Kurs als Nachweis.
- **`target_candidates` von 150 auf 250 erhöht** — nicht weil 150 zu wenig
  lieferte (live weiterhin 164, begrenzt durch `max_pages=10`, nicht durch
  die Zielzahl), sondern als Marge: an einem Tag mit ungünstigerer
  alphabetischer Verteilung der Nordamerika-Treffer über die ersten 10
  Seiten könnte die Ausbeute schwanken. Kein `max_pages`-Anstieg (10 Seiten
  reichen bei Weitem, siehe §5) — zusätzliche Seiten wären reine
  Mehrkosten ohne Effekt auf das bereits deutlich übererfüllte Ergebnis.
- **F066s statische 16er-Liste bleibt bestehen**, aber die Config-Kommentare
  wurden korrigiert: sie ist jetzt explizit als "minimaler Zusatz-Seed",
  nicht mehr als "die CHARTIST-Basis" dokumentiert — die Doku spiegelt jetzt
  wider, was seit F068 technisch bereits der Fall war.

**Kosten:** keine (Config-Änderung, ein zusätzlicher Verifikationslauf).
**Fairness:** unverändert.

## 3. Testdefinition

Keine neuen Unit-Tests — reine Live-Verifikation einer bereits durch F068s
Tests abgedeckten Mechanik (Config-Parameter-Änderung, keine neue Logik).
Bestehende Suite (555 Tests) läuft unverändert grün.

## 4. Implementierung

- `config/ingestion.yaml`: `aktienfinder.screener_discovery.target_candidates`
  150 → 250; Kommentare bei `market_data.watchlist` und
  `screener_discovery` korrigiert (F066s 16er-Liste als Zusatz-Seed
  markiert, F068/F069 als eigentliche Breiten-Quelle referenziert).

## 5. Test & Rollout

- `uv run pytest -q -m 'not integration'`: 555 passed (unverändert).
- Deployment: rsync `config/ingestion.yaml` + `docker compose build api
  scheduler` + `up -d` auf `atlas-ugreen` (Config ist ins Image gebacken).
- **Live verifiziert** (echter Login, Ralfs bezahlter aktienfinder-Account,
  echte Alpaca-Marktdaten):
  - Discovery mit `target_candidates=250`: weiterhin **164 Kandidaten**
    (begrenzt durch `max_pages=10`, nicht durch die Zielzahl — die
    ersten 10 Grid-Seiten liefern bei aktueller alphabetischer Sortierung
    164 Nordamerika-Treffer).
  - Gesamt-Preisuniversum (`resolve_symbol_universe`): **341 Symbole**,
    20.940 Bars synct.
  - **Autoritative Prüfung direkt gegen `market_bar.close` (echte
    Alpaca-USD-Kurse, nicht aktienfinders EUR-Anzeige): 145 Aktien mit
    Kurs > 10 $** — deutlich über Ralfs Mindestanforderung von 100, davon
    128 direkt aus der aktienfinder-Discovery (F068), nur eine kleine
    Minderheit aus der alten 16er-Liste.
- **Rollback-Pfad:** `target_candidates` auf 150 zurücksetzen (Config-Revert,
  kein Schema-/Code-Change) — hätte laut obiger Messung ohnehin keinen
  Effekt auf das Ergebnis, da `max_pages` der eigentliche Begrenzer ist.
