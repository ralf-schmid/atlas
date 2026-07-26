# F090 — Wettbewerbs-Reset & offizieller Start

**Status:** Schnitt (26.07.2026), Umsetzung ausstehend
**Phase:** 5, Block 4 (Abschluss der Phase — letzter P5-DoD-Punkt "Wettbewerb
offiziell gestartet")
**Abhängigkeiten:** [ADR-0009](../adr/0009-alpaca-paper-reset-via-new-accounts.md)
(Alpaca-Reset-Verfahren), [F081](F081-spy-benchmark-portfolio.md) (SPY-Benchmark,
startet am Stichtag selbst — kein F090-Eingriff), [ADR-0001](../adr/0001-alpaca-paper-account-limit.md)
(3-nativ-/3-virtuell-Modell). Stichtag/Startkapital liegen bereits in
`config/competition.yaml` (03.08.2026, 5.000 USD).

## 1. Zieldefinition

Zum Stichtag **Montag 03.08.2026** starten alle 6 Personas den 8-Wochen-Wettbewerb
(§4.7) mit **exakt 5.000 USD, positionsfrei (flat), identischem Zeitpunkt**. Der
bisherige Paper-Verlauf seit 08.07. wird zur **archivierten Vorsaison** — vollständig
erhalten (Data-Lineage), aber klar von der Wettbewerbssaison getrennt.

DoD (ARCHITECTURE.md §8, phase-5.md): "Wettbewerb offiziell gestartet: Stichtag
dokumentiert, alle 6 Portfolios auf 5.000 USD, SPY-Benchmark-Portfolio läuft mit."

## 2. Kontext / Ist-Zustand

- **1:1 Persona↔Portfolio, tief verdrahtet:** `seed._get_or_create_portfolio`
  legt genau ein Portfolio je Persona an (Filter nur `persona_id`).
  `list_active_portfolios` (`graph.py`) nimmt **alle** Portfolios aktiver Personas
  (`Persona.active`), die API (`routes.py`) selektiert je `persona_id` + `mode`
  ein Portfolio. Ein zweites Portfolio je Persona (Vorsaison + Wettbewerb) würde
  ohne Abgrenzung **beide** ziehen → doppelte Zyklen-Ausführung bzw. mehrdeutige
  API-Antwort.
- **`Portfolio` hat kein Saison-/Archiv-Feld** (`id, persona_id, mode,
  broker_account_ref, base_ccy, start_value`). Alle nachgelagerten Tabellen hängen
  über `portfolio_id` (Decisions, `portfolio_snapshot`, `position_snapshot`,
  `order_record`→decision, `review`).
- **Native Account-IDs sind in `seed._NATIVE_ACCOUNT_IDS` hartkodiert** (die alten
  `PA…`-IDs) — nach dem Alpaca-Reset (ADR-0009) sind das **neue** Accounts mit
  neuen IDs **und neuen API-Keys** (Keys → Box-`.env`, Account-IDs →
  `broker_account_ref` der neuen Portfolios).
- **SPY-Benchmark (F081) braucht keinen Reset-Eingriff:** `compute_benchmark_value`
  aktiviert sich selbst ab `start_date` (03.08.) und schreibt `benchmark_value` in
  jeden `portfolio_snapshot`. Nur erwähnen, nicht bauen.

## 3. Design-Entscheidung: Archivierung via neue Saison-Portfolios

Ralf-Entscheidung (26.07.2026): **Vorsaison archivieren, nicht löschen/belassen.**
Umsetzung: neues nullable Feld **`portfolio.archived_at: timestamp | None`**
(NULL = aktive Saison, gesetzt = archiviert). Der Reset **archiviert die 6
bestehenden Portfolios** (`archived_at = Stichtag`) und **legt 6 neue an**
(`archived_at = NULL`, `start_value = 5000`). Alle Portfolio-Selektionen filtern
künftig `archived_at IS NULL`.

Warum neue Portfolios statt In-Place-Reset derselben `portfolio_id`:
- **Saubere Zeitreihen:** Metriken (F082: Sortino/Drawdown auf `portfolio_snapshot`)
  und Leaderboard rechnen pro `portfolio_id` — eine frische ID je Saison vermeidet
  einen Sprung-zurück-auf-5.000 mitten in der Snapshot-Reihe.
- **Data-Lineage (Invariante-nah):** Vorsaison-Portfolios samt Decisions/Snapshots/
  Orders/Reviews bleiben unangetastet und über `archived_at IS NOT NULL`
  abgrenzbar — nichts wird destruktiv verändert.
- **Deckt sich mit dem Alpaca-Zwang:** Broker-seitig entstehen ohnehin neue
  Accounts (ADR-0009) — eine neue `portfolio_id` je neuem Broker-Account ist
  konsistent.

## 4. Scope

**Code (dauerhaft):**
- Migration: `portfolio.archived_at` (nullable `timestamp`, default NULL; additiv,
  bestehende Zeilen bleiben NULL = aktiv bis zum Reset).
- `list_active_portfolios` (`graph.py`): zusätzlich `Portfolio.archived_at.is_(None)`.
- API-Portfolio-Selektion (`routes.py`): zusätzlich `archived_at IS NULL`.
- `seed._get_or_create_portfolio`: matcht nur **nicht-archivierte** Portfolios
  (sonst fände der idempotente Seed nach dem Reset das archivierte statt des neuen).
- Native Account-IDs aus `seed._NATIVE_ACCOUNT_IDS` in eine editierbare Quelle
  heben, die der Reset mit den **neuen** IDs füllt (Vorschlag: Konstante bleibt,
  wird beim Reset mit Ralfs neuen IDs aktualisiert — reiner Lineage-Wert, der
  Broker-Zugriff läuft über die `.env`-Keys, nicht über diese ID).

**Reset-Kommando (`scripts/reset_competition.py`, einmalig, idempotent-sicher):**
- Archiviert die 6 aktiven Portfolios (`archived_at = start_date`).
- Legt 6 neue an (mode=PAPER, `start_value=5000`, `archived_at=NULL`; 3 native mit
  den neuen `broker_account_ref`, 3 virtuelle mit `internal_ledger`).
- Setzt die 3 virtuellen Ledger zurück: JSON-Ledger für HYPE/CONTRA/CRYPTOR neu
  initialisieren auf `_STARTING_CASH = 5000` (`JSONLedgerStore` leeren →
  nächster Zugriff re-initialisiert; siehe `data/ledger`-Mount).
- Dokumentiert Stichtag + `charter_version`-Stand je Persona (Fairness-Nachweis).

**Non-Scope:**
- Der Alpaca-Dashboard-Teil (3 Accounts löschen/neu, Keys generieren, `.env`
  rotieren, Container-Restart) — **manuelle Ralf-Aufgabe** (ADR-0009), Claude
  kann keine Accounts/Keys anlegen.
- SPY-Benchmark-Logik (F081, fertig).
- Archiv-UI (Vorsaison anzeigen) — spätere P5-UI, nicht startkritisch.
- Kein LLM-Anteil (reiner Code/DB, CLAUDE.md-Verbot für Geld-Berechnungen).

## 5. Ablauf (Reihenfolge zum 03.08.)

1. **(Ralf, manuell)** Je nativer Persona: alten Alpaca-Paper-Account löschen →
   neuen mit 5.000 USD anlegen → neue Keys notieren (3-Account-Limit, ADR-0009).
   Box-`.env` (`ALPACA_PAPER_{VULTURE,GUARDIAN,CHARTIST}_KEY_ID/_SECRET_KEY`)
   aktualisieren; neue Account-IDs an Claude für `broker_account_ref`.
2. **(Claude/Code)** `scripts/reset_competition.py` gegen die Box-DB: archivieren +
   6 neue Portfolios + Ledger-Reset. **Vorbedingung:** läuft erst, wenn die neuen
   `.env`-Keys stehen (die nativen Adapter müssen die neuen 5.000-Accounts sehen).
3. **(Betrieb)** Container-Restart (Keys aus `.env`, nicht ins Image gebacken →
   Restart, kein Rebuild). Verifikation: `get_account_balance` je nativer Persona
   == 5.000 flat; virtuelle Ledger == 5.000.
4. Erster Wettbewerbszyklus läuft am 03.08. planmäßig; SPY-Benchmark aktiviert sich
   automatisch (F081).

## 6. Testdefinition (VOR Umsetzung)

Postgres-Schema-Fixture wie `tests/orchestrator/test_scheduler*.py`.

1. **Migration additiv:** bestehende Portfolios haben nach Upgrade `archived_at IS
   NULL` (bleiben aktiv); Downgrade entfernt die Spalte.
2. **Reset archiviert + legt neu an:** nach `reset_competition` haben die 6 alten
   Portfolios `archived_at = start_date`, es existieren 6 neue mit
   `archived_at IS NULL` und `start_value == 5000`; die Vorsaison-Decisions/
   -Snapshots sind über die archivierten `portfolio_id` weiterhin abfragbar
   (nichts gelöscht).
3. **`list_active_portfolios` nach Reset:** genau die **6 neuen** (nicht 12) — der
   `archived_at IS NULL`-Filter greift.
4. **API nach Reset:** liefert für jede Persona das neue (aktive) Portfolio, nie
   das archivierte; mehrdeutige Selektion (zwei PAPER-Portfolios je Persona) tritt
   nicht auf.
5. **Ledger-Reset:** nach `reset_competition` liefert der `InternalLedgerAdapter`
   für HYPE/CONTRA/CRYPTOR `cash == equity == 5000`, keine offenen Positionen.
6. **Idempotenz-Schutz:** ein zweiter `reset_competition`-Lauf ohne neue Vorsaison
   legt nicht erneut 6 Portfolios an / archiviert nicht die frisch erstellten
   (Guard gegen versehentliche Doppelausführung — z. B. Abbruch, wenn bereits
   aktive 5.000-flat-Portfolios ab Stichtag existieren).
7. **Fairness:** alle 6 neuen Portfolios `start_value == 5000`, gleicher Stichtag;
   `charter_version` je Persona unverändert gegenüber Vorsaison (kein stiller
   Charter-Bump beim Reset).

## 7. Kritische Betrachtung

- **Invariante 10 (Fairness):** identischer Start (5.000, flat, ein Stichtag,
  gleiche Charters) — Kernzweck des Resets. Testfall 7 sichert es ab.
- **Invariante 5 (Paper/Live):** bleibt Paper; keine Live-Keys, kein Live-Pfad.
- **Invariante 4 (Stop-Loss):** unberührt — der Reset platziert keine Orders; die
  neuen Accounts starten positionsfrei.
- **Data-Lineage:** Vorsaison wird archiviert (`archived_at`), nicht verändert/
  gelöscht — die verworfenen wie ausgeführten Ideen bleiben nachvollziehbar.
- **Kosten:** 0 (reiner Code/DB, kein LLM).
- **Fehlerbild:** riskant ist eine Doppelausführung oder ein Reset gegen noch alte
  `.env`-Keys (neue Portfolios zeigten dann auf die alten, abgedrifteten Accounts)
  → Vorbedingung in §5 Schritt 2 + Idempotenz-Guard (Test 6) + Verifikation
  (§5 Schritt 3) fangen das ab.

## 8. Rollback-Pfad

- **DB-seitig reversibel:** `reset_competition` in einer Transaktion; bei Fehler
  vor Commit kein Effekt. Nachträglicher Rollback: die 6 neuen Portfolios löschen +
  `archived_at` der alten zurück auf NULL (Vorsaison reaktivieren). Als
  Config-Flag-Äquivalent: der Reset ist ein **manuell ausgelöstes Skript**, kein
  Auto-Job — er läuft nur auf explizites Go.
- **Broker-seitig NICHT reversibel:** gelöschte Alpaca-Accounts sind weg (ADR-0009).
  Deshalb: Skript + Tests **vollständig grün** und von Ralf abgenommen, **bevor**
  die alten Accounts im Dashboard gelöscht werden. Reihenfolge in §5 ist bewusst
  so, dass der destruktive Dashboard-Schritt am Anfang von Ralf bewusst ausgelöst
  wird, nicht vom Code.

## 9. Offene Punkte (Ralf)

- **Neue native Account-IDs + Keys:** liefert Ralf nach dem Dashboard-Anlegen
  (Schritt 1) — bis dahin kann `reset_competition` nicht scharf laufen.
- **Ausführungsfenster:** genauer Zeitpunkt am/vor dem 03.08. (vor dem ersten
  Aktien-Zyklus 09:00 ET / 13:00 UTC).
- **`persona`-Tabelle:** bleibt unverändert (Personas sind saison-übergreifend);
  nur `portfolio` wird saisoniert — zur Bestätigung, falls Ralf die Persona-Historie
  anders schneiden will.
