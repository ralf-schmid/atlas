# Branch Protection für `main` über Repository Ruleset aktiviert

* Status: accepted
* Deciders: Ralf Schmid
* Datum: 2026-07-24
* Betrifft Invariante(n): keine direkt — stützt aber die CI-Guardrail „kein Merge ohne grüne CI" (CLAUDE.md / ARCHITECTURE.md §8)

## Kontext und Problemstellung

Phase 2 hatte Branch Protection als „strukturell nicht möglich" abgehakt
([docs/dod/phase-2.md](../dod/phase-2.md)): die klassische Branch-Protection-API
(`PUT /repos/{owner}/{repo}/branches/{branch}/protection`) liefert auf privaten
Repos persönlicher **Free**-Accounts `403 "Upgrade to GitHub Pro or make this
repository public"` — unabhängig von der Konfiguration. Ralf hatte das damals
nicht weiterverfolgt (kein Pro, Repo bleibt privat).

Am 2026-07-24 bat Ralf erneut, Branch Protection für `main` zu aktivieren.
Zwischenzeitlich hat GitHub **Repository Rulesets** auch für private Repos auf
dem Free-Plan freigeschaltet — im Gegensatz zur klassischen Branch Protection.
Damit ist der Free-Plan-Blocker aus Phase 2 umgangen, ohne auf Pro zu wechseln
oder das Repo öffentlich zu machen.

Zweiter, unabhängiger Blocker: Aus einer Claude-Code-Session heraus lässt sich
die Einstellung **nicht** setzen. Der GitHub-MCP-Server bietet kein Tool für
Branch Protection / Rulesets, und der Egress-Proxy blockt Roh-API-Schreibcalls
auf diesen Pfad mit `403 "Write access to this GitHub API path is not permitted
through this proxy"` (Org-Egress-Policy, nicht umgehbar). Die Aktivierung ist
daher zwingend ein manueller Schritt durch Ralf (UI oder lokales `gh`).

## Entscheidungstreiber

* CLAUDE.md-Grundsatz „kein Merge ohne grüne CI" endlich technisch erzwungen
  statt nur dokumentiert.
* Kein Wechsel auf GitHub Pro, Repo bleibt privat.
* Solo-Betrieb (Ralf + Claude via PRs): keine sinnvolle Zweit-Reviewer-Pflicht.
* Setzen aus der Agent-Session heraus ist technisch versperrt → Weg muss
  reproduzierbar für den manuellen Vollzug dokumentiert sein.

## Betrachtete Optionen

* **A — Klassische Branch Protection.** Auf privatem Free-Repo per 403
  gesperrt (Phase-2-Befund). Verworfen.
* **B — Repository Ruleset für `main`.** Auf privatem Free-Repo verfügbar.
  Gewählt.
* **C — Weiter ohne Gate, nur dokumentierter Grundsatz.** Verworfen — bietet
  keinen echten Schutz gegen versehentliche direkte Pushes / rote Merges.

## Entscheidung

Gewählt: **Option B**. Ralf hat am 2026-07-24 über die GitHub-UI
(Settings → Rules → Rulesets → *New branch ruleset*) ein Ruleset für `main`
mit folgender Konfiguration aktiviert:

* Ziel-Branch: `main` (Default-Branch).
* **Require status checks to pass** mit *Require branches to be up to date*
  (strict), Pflicht-Checks: `lint`, `test`, `web`, `gitleaks`.
* **Block force pushes** und Löschschutz aktiv.
* **Bypass-Liste leer** (= gilt auch für den Repo-Owner/Admin;
  Äquivalent zu `enforce_admins`).
* **Keine** Pull-Request-Review-Approval-Pflicht (Solo-Betrieb — 1 Approval
  würde Ralf an eigenen PRs blockieren).

Bewusst **nicht** als Pflicht-Check:

* `pip-audit` — läuft `continue-on-error` (report-only, Security-Audit P6);
  ein Dependency-CVE ist nicht immer same-day fixbar, soll also kein Merge-Gate
  sein.
* `integration` — braucht die `ALPACA_PAPER_*`-Secrets; als Pflicht-Check würde
  es ohne gesetzte Secrets jeden Merge blockieren. Kann später ergänzt werden,
  falls die Secrets dauerhaft im Repo liegen.

### Konsequenzen

* Gut, weil direkte Pushes auf `main` und Merges mit roter CI jetzt technisch
  unterbunden sind — der CLAUDE.md-Grundsatz ist durchgesetzt, nicht nur notiert.
* Gut, weil ohne Pro-Upgrade und ohne das Repo öffentlich zu machen.
* Neutral, weil Ralf als Owner das Ruleset jederzeit selbst in der UI anpassen
  oder pausieren kann (dokumentierter Rollback-Pfad: Ruleset auf *Disabled*).
* Betrieblich zu beachten: **Claude Code kann dieses Setting nicht selbst
  setzen oder ändern** (kein MCP-Tool, Proxy blockt den Schreib-API-Pfad).
  Jede künftige Änderung an den Pflicht-Checks (z. B. neuer CI-Job) muss Ralf
  manuell in der UI/per `gh` nachziehen — Claude kann nur den exakten
  Befehl/Klickpfad liefern.

## Operativer Nachtrag: Änderung der Pflicht-Checks

Wenn ein CI-Job umbenannt/hinzugefügt/entfernt wird, muss die Check-Liste im
Ruleset angepasst werden, sonst blockt ein nicht mehr existierender Pflicht-Check
alle Merges (oder ein neuer Job schützt nichts). Reproduzierbarer `gh`-Weg für
den manuellen Vollzug (klassische Protection-API — nur als Referenz, auf Free
per 403 gesperrt; für Rulesets: `gh api repos/ralf-schmid/atlas/rulesets`):

```bash
# Ruleset-ID finden
gh api repos/ralf-schmid/atlas/rulesets

# Ruleset ansehen / prüfen
gh api repos/ralf-schmid/atlas/rulesets/<id>
```

## Pro/Contra der Optionen

### A — Klassische Branch Protection

* Gut, weil vertrautes Modell.
* Schlecht, weil auf privatem Free-Repo per 403 gesperrt (Phase-2-Befund).

### B — Repository Ruleset (gewählt)

* Gut, weil auf privatem Free-Repo verfügbar — löst den Phase-2-Blocker ohne
  Pro/Public.
* Gut, weil flexiblere Bypass-Listen und mehrere Rulesets kombinierbar.
* Schlecht, weil aus der Agent-Session heraus nicht setzbar (manueller Schritt).

### C — Kein Gate

* Gut, weil kein Aufwand.
* Schlecht, weil kein realer Schutz — widerspricht dem CLAUDE.md-Grundsatz.
