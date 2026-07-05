# F007 — FastAPI-Skeleton + erste UI-Seite (Portfolio-Snapshot)

Status: in Umsetzung
Datum: 2026-07-05
Phase: 2

## 1. Zieldefinition

FastAPI-Backend mit einem echten Endpoint (`GET /api/personas/{name}/snapshot`), das den
letzten `portfolio_snapshot` + zugehörige `position_snapshot`-Zeilen aus der DB liest. Eine
Next.js-Seite (mobile-first, ~390 px) zeigt diesen Snapshot an. DoD-Punkt: "UI zeigt einen
Portfolio-Snapshot aus der DB; mobil brauchbar".

**Nicht Teil dieses Features:** Leaderboard, Decision Journal, Impuls-Vergleich, Agent
Trace (spätere Phasen), Auth/Login (kein Login vorgesehen laut Architektur — Ralf ist der
einzige Nutzer), SSE/Realtime-Updates.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| Fairness | ja | Ein generischer Endpoint für alle Personas (`{name}`-Parameter), keine
Persona-spezifische Sonderbehandlung im Code. |
| Mobile-first (§3.7) | ja | UI-Grundlayout ab 390 px entworfen, Touch-Targets ≥ 44 px. |
| Keine Fremdtext-Volltexte in UI (Was Claude Code nicht tun darf) | n/a | Dieser Endpoint zeigt nur Zahlen (Depotwert, Cash, Positionen) — keine Zeitschriften-/Recherche-Inhalte. |

**Design-Entscheidungen:**
- **Seed-Skript für Demo-Daten:** Da noch keine Snapshot-Erzeugungs-Jobs existieren
  (kommen mit dem Handels-Agenten), gibt es `scripts/seed_demo_snapshot.py`, das eine
  Beispiel-Persona/Portfolio/Snapshot-Zeile anlegt — ausschließlich für lokale
  Entwicklung/Verifikation, klar als Dev-Seed gekennzeichnet, kein Teil des
  Produktionscodes.
- **Kein Auth-Layer:** Passt zum Projektkontext (Einzelnutzer, kein Fremdzugriff
  vorgesehen) — nicht Teil dieses Features, könnte später über die UGREEN-Reverse-Proxy-
  Ebene gelöst werden statt in der App selbst.

**Kosten:** keine LLM-Calls. **Fairness:** siehe oben.

## 3. Testdefinition (vor Umsetzung)

1. `GET /api/personas/{name}/snapshot` mit existierendem Snapshot → 200, JSON mit
   `total_value`, `cash`, `positions[]`.
2. `GET /api/personas/{name}/snapshot` ohne Snapshot für diese Persona → 404.
3. `GET /api/personas/{unknown}/snapshot` → 404 (unbekannte Persona).
4. UI-Seite rendert die vom Endpoint gelieferten Werte; bei 390 px Viewport keine
   horizontalen Scrollbalken, Touch-Targets ≥ 44 px (per `preview_inspect` verifiziert).

## 4. Implementierung

`src/api/app.py`, `src/api/routes.py`, `src/api/schemas.py`, `scripts/seed_demo_snapshot.py`,
`web/` (Next.js).

## 5. Testdurchlauf

**Backend:** `uv run pytest tests/api/ --cov=src/api --cov-branch` → 6/6 grün, 93%
Line-Coverage (die ungetesteten Zeilen sind der `get_session`-Generator selbst, der in
Tests per FastAPI-`dependency_overrides` ersetzt wird). `ruff`/`mypy` sauber.

**Frontend:** `npx tsc --noEmit` und `npm run lint` sauber (TypeScript strict, wie von
CLAUDE.md gefordert).

**Manuell verifiziert** (`scripts/seed_demo_snapshot.py` gegen lokales Postgres, dann Next.js
Dev-Server + FastAPI-Backend über Bash gestartet, Browser-Preview):
- Seite rendert Depotwert, Cash, P&L, 2 Positionen korrekt aus echten DB-Daten.
- Bei 390×844 (exakter DoD-Wert): kein horizontaler Scroll (`scrollWidth === clientWidth
  === 390`), keine Browser-Konsolen-Fehler.
- Touch-Targets: Positions-Zeilen `min-height: 44px` (tatsächlich 58px durch Padding),
  per `preview_inspect` verifiziert.
- **Lighthouse (echter Lauf via `npx lighthouse`)** gegen den **Production-Build**
  (`next build && next start`, nicht den Dev-Server — Dev-Server-Werte sind wegen HMR/
  unminifiziertem Code irreführend niedrig, dort nur 76): **Performance 99, Accessibility
  100** — beide deutlich über der geforderten Schwelle von 85.

**Nebenbei gefunden:** Der Preview-Tool-Sandbox blockiert Python-Prozessstarts über
`preview_start` (`uv run` scheitert an blockiertem `getcwd()`, direkter Venv-Python-Aufruf
an einem blockierten Read von `.venv/pyvenv.cfg` — beides `PermissionError`, keine
Unix-Rechte-Ursache). Node/npm-Prozesse sind davon nicht betroffen. Workaround: FastAPI
über normale Bash-Hintergrundausführung starten (`.claude/launch.json` enthält nur noch
den `web`-Eintrag, `api` wurde entfernt, um künftige Sessions nicht in dieselbe Sackgasse
laufen zu lassen — Backend-Start-Befehl steht hier im Dokument).

## 6. Rollback-Pfad

Additives Feature. Rollback = Commit zurücknehmen.
