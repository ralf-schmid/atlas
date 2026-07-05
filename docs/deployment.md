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
  | postgres   | 5432            | 5432      | frei auf der Box                      |
  | litellm    | 4000            | 4000      | frei auf der Box                      |
  | api        | 8000            | 8000      | frei auf der Box                      |
  | web        | 3000            | **3001**  | 3000 ist die bestehende Grafana-Instanz |

- Deployment-/Update-Befehle:
  ```
  ssh atlas-ugreen
  cd /mnt/apps/docker/atlas
  sudo docker compose build api web
  sudo docker compose up -d
  sudo docker compose exec -T api uv run alembic upgrade head   # einmalig / nach Schema-Änderungen
  ```
- **Verifiziert 2026-07-05:** alle 4 Container `healthy`, `http://nas.fritz.box:3001/`
  liefert 200 mit echten DB-Daten, `:8000/health` und `:4000/health/liveliness` ok
  (jeweils von einem anderen Rechner im LAN aus geprüft, nicht nur lokal auf der Box).

## Offen

- **Grafana-Postgres-Datasource:** noch nicht eingerichtet — braucht Grafana-Admin-
  Zugang, den ich nicht automatisch mitgenutzt habe (gehört zum bestehenden
  `monitoring`-Stack, nicht zu ATLAS). Host `nas.fritz.box`, Port 5432, DB `atlas`,
  User/Passwort `atlas`/`atlas`. Ralf richtet das über die Grafana-UI ein
  (Connections → Data sources → PostgreSQL), oder gibt einen API-Key, falls das
  automatisiert werden soll.
- **Grafana-Alert-Regel für Container-Health + Telegram-Contact-Point:** noch nicht
  eingerichtet, gleicher Grund.
- Postgres-Credentials (`atlas`/`atlas`) sind in `docker-compose.yml` hartcodiert,
  nicht aus einem Secret — für eine reine Paper-Trading-Research-DB im Heim-LAN
  akzeptabel, aber erwähnenswert, falls das später mal auffällt.
