# F109 — Screener-Rauschfilter: Warrants raus, Krypto-Duplikate zusammenfassen

Status: in Umsetzung
Datum: 2026-08-15
Phase: 4/5 (Datenqualität/Kosten, wirkt auf F105)
Auslöser: Ralf — „grenze sinnvoll ein, um die Tokens möglichst effizient zu nutzen"

## 1. Zieldefinition

Der Alpaca-Screener (F105) schreibt pro Lauf 50 `market_mover`-Zeilen, aus denen
je Zyklus 50 Research-Items werden, die **sechs Personas lesen**. Der erste
Produktivlauf am 15.08.2026 zeigt, dass gut die Hälfte davon kein Impuls ist,
sondern Rauschen:

| Kategorie | geliefert | davon Rauschen |
|---|---|---|
| stocks/gainer | AACBR, MYSEW, WETO, DUKRW, ONFOW, MDXH, CAPR, BANL, HHS, UMAL | **5 Warrants/Rights** (`AACBR`, `MYSEW`, `DUKRW`, `ONFOW` …) |
| stocks/loser | GDEVW, AMPGZ, TMCWW, DRMAW, INV, BZAI, BZAIW, KLC, TLSIW, EDBLW | **6 Warrants** (`AMPGZ` bleibt bewusst drin, s. u.) |
| crypto/gainer | LINK/USDC, LINK/USD, LINK/USDT, LINK/BTC, AVAX/USD, AVAX/USDT, AVAX/USDC, UNI/USDT, UNI/USDC, UNI/USD | **7 Duplikate** — es sind nur 3 Assets |
| crypto/loser | TRUMP/USD, BONK/USD, SHIB/USD, SHIB/USDC, SHIB/USDT, HYPE/USD, SKY/USD, ADA/USD, PEPE/USD, PAXG/USD | **2 Duplikate** (SHIB dreifach) |

**Ziel:** dieselbe Zahl echter Impulse bei deutlich weniger Tokens.

1. **Warrants, Rights und Units fliegen aus den Aktien-Movern.** Ein Warrant
   notiert bei wenigen Cent; seine Prozentbewegung ist eine Hebelmechanik, kein
   Unternehmensereignis. ATLAS handelt sie nicht, und für eine Persona ist
   `TMCWW −40 %` schlicht irreführend.
2. **Krypto wird auf ein Quote-Asset reduziert (USD).** `LINK/USDC`, `LINK/USDT`
   und `LINK/BTC` sind dasselbe Asset in anderer Notierung — vier Zeilen für
   einen Sachverhalt. CRYPTOR handelt ohnehin USD-Paare
   (`crypto_market_data.watchlist`).
3. **Overfetch, damit `top` echte Treffer bleibt.** Ohne das würden aus 10
   angeforderten Gainern nach dem Filter 5. Der Job holt deshalb `top × oversample`
   und schneidet **nach** dem Filter auf `top` — ein API-Call wie bisher, gleiche
   Kosten, volle Ausbeute.

**Non-Scope:** die Auswahl-Logik selbst (welche Kategorien, welche Märkte),
`alpaca_news`, und jede Form von Persona-Vorauswahl.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja, geprüft | Der Filter wirkt vor dem Pool, also für alle sechs Personas identisch. Kein Persona-Bezug in der Regel. CRYPTOR verliert die Nicht-USD-Notierungen — dieselben Assets bleiben ihm über das USD-Paar erhalten, sein Charter-Universum ist ohnehin USD. |
| #9 Untrusted Content | nein | Nur Symbole und Zahlen. |
| #3 kein Pfad zur Order | nein | Reine Research-Ebene, `market_mover` hat keinen Order-Bezug. |
| Kosten | Ziel des Features | ~50 → ~28 Research-Items je Zyklus aus dieser Quelle, bei 4 Zyklen × 6 Personas. |

**Das Risiko liegt in der Warrant-Erkennung.** Alpaca liefert im Screener keine
Instrumentenklasse mit, und ein `get_all_assets`-Abgleich je Lauf wäre ein
zweiter API-Call über ~11k Assets für eine Handvoll Symbole. Ich nutze deshalb
die **US-Ticker-Konvention**: ein fünfstelliges Symbol, dessen fünfte Stelle
`W` (Warrant), `R` (Right) oder `U` (Unit) ist, ist per NASDAQ/NYSE-Konvention
keine Stammaktie. Das ist eine Heuristik, und sie kann theoretisch eine echte
fünfbuchstabige Stammaktie treffen.

Warum ich das trotzdem für vertretbar halte — und was es kostet, wenn es
danebengeht: ein fälschlich gefiltertes Symbol taucht einen Zyklus lang nicht als
`market_mover`-Impuls auf. Es bleibt im Screener-Universum (F010), in den
Nachrichten und in den Indikatoren; keine Position, kein Stop und keine Order
hängen daran. Ein falsch **durchgelassener** Warrant dagegen kostet Tokens in
jedem Zyklus und kann eine These auf eine Hebelmechanik stützen. Die Asymmetrie
spricht klar für den Filter. Abschaltbar ist er trotzdem (§4).

**Bewusst nicht gefiltert: `Z`.** In der NASDAQ-Konvention ist die fünfte Stelle
`Z` ein Sammelplatz („misc.", Depositary Receipts, gelegentlich Units). Anders als
`W`/`R`/`U` ist sie nicht eindeutig genug, um ein Symbol blind zu verwerfen —
`AMPGZ` aus der Liste oben läuft deshalb weiter mit. Lieber ein durchgelassener
Grenzfall als eine stillschweigend verworfene Aktie.

**Die Token-Frage, offen entschieden.** Mit `oversample` bleibt die Zeilenzahl
etwa gleich (die Lücken werden mit echten Treffern aufgefüllt) — es sinkt nicht
die Menge, sondern es steigt der Anteil verwertbarer Zeilen von 62 % auf ~100 %.
Das ist die Lesart von „Tokens effizient nutzen", die ich für richtig halte:
gleicher Preis, mehr Substanz. Wer stattdessen **weniger** Tokens will, hat dafür
schon den passenden Regler — `alpaca_screener.top` aus F105. Die beiden Schrauben
bleiben so sauber getrennt: `top` bestimmt die Menge, F109 die Qualität.

## 3. Testdefinition (vor der Implementierung geschrieben)

In `tests/ingestion/test_alpaca_screener.py`:

1. `test_warrants_and_rights_are_dropped_from_stock_movers` — die echte
   Gainer-Liste vom 15.08. rein, `AACBR`/`MYSEW`/`DUKRW`/`ONFOW` raus,
   `MDXH`/`CAPR`/`BANL`/`HHS`/`UMAL`/`WETO` bleiben.
2. `test_four_letter_symbols_ending_in_w_are_kept` — die Regel greift nur bei
   fünf Stellen; ein vierstelliges Symbol auf `W` ist eine normale Aktie.
3. `test_crypto_pairs_are_reduced_to_the_usd_quote` — aus LINK/USDC + LINK/USD +
   LINK/USDT + LINK/BTC bleibt genau LINK/USD.
4. `test_crypto_asset_without_usd_pair_is_kept` — ein Asset, das *nur* als
   USDT-Paar auftaucht, fällt nicht unter den Tisch (sonst verschwindet ein
   echter Mover, weil zufällig kein USD-Paar in der Liste steht).
5. `test_oversampling_fills_up_to_top_after_filtering` — 30 angefragte, 10
   behaltene: der Job liefert 10, nicht 5.
6. `test_ranks_stay_the_original_alpaca_ranks` — nach dem Filter wird **nicht**
   neu nummeriert; Rang 7 bleibt Rang 7. Alles andere wäre eine erfundene
   Rangliste.
7. `test_filter_off_keeps_everything` — Config-Schalter aus ⇒ Verhalten wie
   F105. Der Rollback-Pfad als Test.
8. `test_stock_filter_does_not_touch_crypto_symbols` — `SHIB/USD` hat fünf
   Stellen vor dem Slash, darf aber nie unter die Aktien-Regel fallen.

## 4. Umsetzung

| Datei | Änderung |
|---|---|
| `src/ingestion/alpaca_screener.py` | `_filter_movers()` (Warrant-/Duplikat-Regel) + Overfetch in `run_alpaca_screener_sync` |
| `config/ingestion.yaml` | `alpaca_screener.exclude_derivative_classes`, `crypto_quote`, `oversample` |

**Rollback:** `exclude_derivative_classes: false` und `crypto_quote: null` ⇒
Verhalten exakt wie F105 (als Test festgehalten). `config/` ist ins Image
gebacken, der Rollback braucht also `build api scheduler` + `up -d`.

## 5. Test & Rollout

- 8 neue Tests in `tests/ingestion/test_alpaca_screener.py` (13 gesamt in der
  Datei), `ruff`/`mypy` clean.
- **Gegen den echten Batch vom 15.08.2026 durchgerechnet** (die 50 Zeilen aus dem
  ersten Produktivlauf, ohne Overfetch, um den reinen Filtereffekt zu zeigen):

  | Gruppe | vorher | nachher | entfernt |
  |---|---|---|---|
  | stocks/gainer | 10 | 6 | 4 Warrants/Rights |
  | stocks/loser | 10 | 4 | 6 Warrants |
  | stocks/most_active | 10 | 10 | — (echte Aktien, wie erwartet) |
  | crypto/gainer | 10 | 3 | 7 Notierungs-Duplikate (LINK, AVAX, UNI) |
  | crypto/loser | 10 | 8 | 2 SHIB-Duplikate |
  | **gesamt** | **50** | **31** | **38 %** |

  Bemerkenswert: `most_active` war schon vorher sauber — das Rauschen sitzt
  ausschließlich in den Gainer-/Loser-Listen, weil dort die Prozentbewegung das
  Sortierkriterium ist und Warrants die mechanisch größten haben.
- Im Produktivbetrieb füllt `oversample: 3` diese Lücken wieder mit echten
  Treffern auf; erwartet werden also weiter ~50 Zeilen, aber ohne die 19
  wertlosen.
