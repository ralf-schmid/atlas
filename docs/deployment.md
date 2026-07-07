# Deployment — UGREEN NAS

Zielhardware für den Paper-Betrieb (ARCHITECTURE.md §8, Phase-2-DoD). Diese Datei
hält fest, was für Deployment/Ops auf der Box nicht aus dem Code ableitbar ist.

## Zugriff

- Host: `nas.fritz.box` (LAN), TrueNAS SCALE auf Debian 12 (bookworm).
- User: `ralf` (Gruppen `familie`, `builtin_administrators`; passwortloses `sudo`).
- Auth: SSH Public-Key, eingerichtet 2026-07-05. Dedizierter Key (nicht Ralfs
  privater Key), damit er unabhängig widerrufbar ist.
- SSH-Config auf Ralfs Mac (`~/.ssh/config`), Alias `atlas-ugreen`:
  ```
  Host atlas-ugreen
      HostName nas.fritz.box
      User ralf
      IdentityFile ~/.ssh/atlas_ugreen
      IdentitiesOnly yes
  ```
  `IdentitiesOnly yes` ist wichtig, weil `~/.ssh/config` global auch einen
  1Password-SSH-Agent für `Host *` einbindet — ohne diese Zeile würde der
  1Password-Agent mitversuchen und den dedizierten Key ggf. verdecken.
- Docker: `ralf` ist nicht in der `docker`-Gruppe, aber `sudo` ist passwortlos
  konfiguriert → alle Docker-Befehle auf der Box laufen über `sudo docker ...`.

## Bestehende Infrastruktur auf der Box (Stand 2026-07-05)

Wichtig für Port-/Namenskonflikte beim ATLAS-Deployment:

- **Grafana läuft bereits** (Container `grafana`, Port 3000) — das ist die
  "bestehende Instanz" aus ARCHITECTURE.md §"Grafana: bestehende Instanz". ATLAS
  deployt kein eigenes Grafana, sondern bekommt hier nur eine zusätzliche
  Postgres-Datasource (siehe "Offen" unten).
- Weitere Container: `dashboard` (nginx, 8080), `roundcube` (8888), `collectors`,
  `influxdb` (8086), `graphite-exporter` (9108/2003), `prometheus` (9090),
  n8n-Stack (`ix-n8n-*`), Immich-Stack (2283), Mail-Stack (`mailarchiv-*`).
- Host-level nginx auf Port 80/443 (kein Docker-Container) — vermutlich
  TrueNAS/UGOS-eigene Weboberfläche, nicht anfassen.
- Compose-Projekte liegen konventionsgemäß unter `/mnt/apps/docker/<projekt>/`
  (z.B. `monitoring/` für Grafana+Prometheus+InfluxDB). ATLAS folgt dieser
  Konvention: `/mnt/apps/docker/atlas/`.

## ATLAS-Deployment

- Pfad auf der Box: `/mnt/apps/docker/atlas/`.
- Repo-Sync: Dateien wurden per `rsync` von der lokalen Arbeitskopie übertragen
  (kein `git clone`, kein Deploy-Key auf der NAS angelegt — bewusst keine neuen
  dauerhaften Credentials ohne Ralfs Zustimmung eingerichtet). Für künftige
  Updates: erneut rsyncen, oder auf Wunsch sauberen `git clone` mit
  GitHub-Deploy-Key (read-only, nur dieses Repo) einrichten.
- `.env` wurde direkt per `scp` von der lokalen `.env` übertragen (echte Secrets,
  `chmod 600`, nicht im Git-Repo, nie über ein Terminal-Log ausgegeben).
- Ports (angepasst gegenüber lokalem Dev wegen Konflikten mit Punkt oben):

  | Service    | Container-Port | Host-Port | Hinweis                              |
  |------------|-----------------|-----------|---------------------------------------|
  | postgres   | 5432            | 5432      | gebunden an `ATLAS_BIND_IP` (LAN-IP `192.168.178.116`, in der Box-`.env`) |
  | litellm    | 4000            | 4000      | gebunden an `ATLAS_BIND_IP` (wie postgres) |
  | api        | 8000            | 8000      | frei auf der Box                      |
  | web        | 3000            | **3001**  | 3000 ist die bestehende Grafana-Instanz — reiner Port-Konflikt (zwei Services können keinen Host-Port teilen), keine Ausweichlösung für die Grafana-Integration selbst; die läuft separat über die bestehende Instanz auf 3000, siehe unten |

- **`ATLAS_BIND_IP=192.168.178.116`** steht in der `.env` auf der Box: Postgres und
  LiteLLM sind damit an das LAN-Interface gebunden (erreichbar aus `192.168.178.0/24`,
  z. B. für die Grafana-Datasource), aber nicht auf anderen/zukünftigen Interfaces.
  Achtung: Die IP ist eine DHCP-Reservation der Fritzbox — ändert sie sich, muss die
  `.env` nachziehen (siehe TRUENAS_HOMELAB.md §2, IP-Persistenz).
- **LiteLLM ist per Image-Digest gepinnt** (v1.92.0, Stand 2026-07-05, in
  `docker-compose.yml`). `main-latest` ist ein mutable Dev-Tag; Update = neuen Digest
  eintragen und Deployment verifizieren.
- **api-Container läuft als non-root** (`ralf`, UID 3001 / GID 3000 `familie` — wie
  auf der Box, siehe Dockerfile.api).
- Deployment-/Update-Befehle (Repo-Stand liegt per rsync auf der Box, kein Git-Clone):
  ```
  # vom Mac aus, aus der lokalen Arbeitskopie:
  rsync -a --delete --exclude='.git' --exclude='.venv' --exclude='node_modules' \
    --exclude='.next' --exclude='.env' --exclude='data/' \
    ./ atlas-ugreen:/mnt/apps/docker/atlas/

  ssh atlas-ugreen
  cd /mnt/apps/docker/atlas
  sudo docker compose build api web
  sudo docker compose up -d
  sudo docker compose exec -T api uv run alembic upgrade head   # einmalig / nach Schema-Änderungen
  ```
- **Verifiziert 2026-07-05:** alle 4 Container `healthy`, `http://nas.fritz.box:3001/`
  liefert 200 mit echten DB-Daten, `:8000/health` und `:4000/health/liveliness` ok
  (jeweils von einem anderen Rechner im LAN aus geprüft, nicht nur lokal auf der Box).
- **Re-Verifiziert 2026-07-05 (Deployment-Härtung):** LiteLLM-Healthcheck jetzt
  wirklich `healthy` (vorher dauerhaft unhealthy — kein curl im Image), api läuft
  als `ralf`, Postgres/LiteLLM binden an `192.168.178.116`, mode-Filter aktiv
  (`?mode=demo` → 422). Hinweis: Die DB ist aktuell **leer** — der frühere
  Demo-Seed wurde zwischenzeitlich weggeräumt (vermutlich durch einen Testlauf
  gegen die Box-DB; genau das Szenario aus dem Docstring von
  `scripts/seed_demo_snapshot.py`). Bei Bedarf neu seeden:
  `sudo docker compose exec -T api uv run python - < scripts/seed_demo_snapshot.py`.
- **Re-Verifiziert 2026-07-05 (Phase-2-Abschluss):** Commit `65cf957`
  (`feat(telegram): persist HITL callback outcomes`) per `rsync` auf die UGREEN
  deployt, `api`/`web` neu gebaut, `sudo docker compose up -d` ausgeführt und
  Alembic `upgrade head` im API-Container ausgeführt. Ergebnis: `atlas-api-1`,
  `atlas-postgres-1` und `atlas-litellm-1` healthy, `atlas-web-1` läuft.
  Healthchecks: `http://localhost:8000/health` → `{"status":"ok"}`,
  `http://localhost:3001/` → 200 OK,
  `http://192.168.178.116:4000/health/liveliness` → `"I'm alive!"`.

## Grafana-Integration (bestehende Instanz, Port 3000)

Kein eigenes Grafana für ATLAS — die bestehende Instanz auf der Box bekommt eine
zusätzliche Postgres-Datasource. Dafür per API, mit einem Service-Account-Token
(Grafana 13 hat klassische API-Keys entfernt): Administration → Users and access →
Service accounts → Add service account (Rolle **Admin**, Datasources anlegen braucht
Org-Admin-Rechte) → Add service account token → Token in `.env` als
`GRAFANA_API_KEY` (Eintrag schon vorbereitet in `.env`/`.env.example`, `GRAFANA_URL`
ist schon gesetzt).

**Status (2026-07-05):** Token angelegt und eingetragen, gegen `$GRAFANA_URL/api/org`
verifiziert. Postgres-Datasource `atlas-postgres` (uid `dfr7iupqjs4cgb`) per API
angelegt: Host `nas.fritz.box:5432` (der Grafana-Container erreicht den
veröffentlichten Host-Port über den LAN-Hostnamen — mit `nc` aus dem
`grafana`-Container getestet, bevor die Datasource angelegt wurde), DB `atlas`,
User/Passwort `atlas`/`atlas`. Health-Check: `"Database Connection OK"`.

**Container-Health-Alert-Regel: separater Ops-Task.** Grafana kann
nur auf Metriken alerten, nicht direkt auf rohe HTTP-Healthcheck-Endpoints — der
Standardweg wäre ein `blackbox_exporter` als neuer Service im bestehenden
`monitoring`-Stack (`/mnt/apps/docker/monitoring/compose.yaml` + `prometheus.yml`,
kein Teil von ATLAS). Dieser Punkt ist deshalb aus ATLAS Phase 2 ausgelagert und
wird in Ralfs bestehender Monitoring-Umgebung eingerichtet.

### Dashboard "ATLAS — Overview"

Per API angelegt (`POST /api/dashboards/db` mit dem Service-Account-Token), Datei
zum manuellen (Re-)Import liegt unter
[config/grafana/atlas-overview-dashboard.json](../config/grafana/atlas-overview-dashboard.json)
(Grafana → Dashboards → New → Import → Datei hochladen; erwartet eine Postgres-
Datasource — beim Import ggf. `atlas-postgres` auswählen, falls Grafana danach fragt).

18 Panels über 5 Reihen, alle Queries gegen die (aktuell leere) DB verifiziert
(keine SQL-Fehler, nur 0-Werte/leere Ergebnisse — normal, solange kein Orchestrator-
Lauf stattgefunden hat):

- **Overview:** aktive Personas, Runs (24h), fehlgeschlagene Runs (24h), Kosten heute
- **Kosten je Persona:** Kosten pro Persona/Tag (Zeitreihe), Kosten diesen Monat vs.
  Soft-Cap 120 USD (Gauge, Warnschwelle bei 80 % gemäß `config/llm.yaml`)
- **Portfolio:** Kosten nach Provider, Portfolio-Wert je Persona (Zeitreihe),
  Leaderboard-Tabelle (letzter Snapshot je Persona)
- **Ingestion Freshness:** Minuten seit letztem Research-Item, Research-Items/Tag
- **Decisions:** nach Status, letzte 20 Decisions (Tabelle)

`agent_run` hat kein eigenes Zeitstempel-Feld — Zeitbezug kommt über den Join auf
`cycle.started_at`.

## Sonstiges

- **Postgres-Passwort rotiert (07.07.2026, Security-Audit P7):** `.env` auf der
  Box hat ein starkes, zufälliges `POSTGRES_PASSWORD`/`DATABASE_URL` statt des
  Compose-Defaults `atlas` (serverseitig generiert und ersetzt). `ALTER ROLE
  atlas WITH PASSWORD ...` im laufenden Postgres-Container **durchgeführt**,
  direkt gefolgt von `docker compose up -d` (postgres + api neu erstellt, beide
  danach `healthy` — minimales Downtime-Fenster).
  **Noch offen (bewusst nicht automatisch ausgeführt — Auto-Mode-Klassifikator
  hat das Grafana-API-Schreiben als nicht explizit angefragte
  Secret-Store-Änderung geblockt):** Grafana-Datasource `atlas-postgres` (uid
  `dfr7iupqjs4cgb`) nutzt noch das alte Passwort und kann sich bis zur manuellen
  Anpassung nicht mit Postgres verbinden (Dashboard-Panels zeigen dann
  Verbindungsfehler statt Daten). Manuell nachziehen: Grafana → Connections →
  Data sources → `atlas-postgres` → Password aktualisieren (neuer Wert steht in
  `.env` auf der Box unter `POSTGRES_PASSWORD`) → Save & Test.
- **Re-Verifiziert 07.07.2026 (Security-Audit-Fixes F026–F031 deployt):**
  rsync + `docker compose build api web` + `up -d` + `alembic upgrade head`
  (keine neuen Migrationen). Health-Checks von einem anderen Rechner im LAN
  (nicht nur lokal auf der Box): `http://192.168.178.116:8000/health` →
  `{"status":"ok"}`, `:3001/` → 200, `:4000/health/liveliness` →
  `"I'm alive!"`. Alle 4 Container `healthy`/laufend.
