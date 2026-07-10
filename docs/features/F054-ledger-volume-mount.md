# F054 — Internal-Ledger-State persistent mounten (HYPE/CONTRA/CRYPTOR)

Status: umgesetzt
Datum: 2026-07-10
Phase: 5

## 1. Zieldefinition

Fund im Vollständigkeits-Audit (Subagent-Recherche nach F049-F053): `docker-
compose.yml` mountet für `api`/`scheduler`/`telegram-bot` gezielt
`data/ingest/publications` bzw. `data/ingest/aktienfinder/screenshots` als
host-persistente Volumes — aber **nirgends** `data/ledger`, obwohl
`JSONLedgerStore` (`src/broker/ledger_store.py`, `_DEFAULT_BASE_DIR =
<repo>/data/ledger`) genau dort den gesamten Zustand der drei virtuellen
Personas (HYPE/CONTRA/CRYPTOR: Cash, offene Positionen, pending Stops,
`executed_decisions`-Idempotenz-Log) ablegt. `.gitignore` dokumentiert
`/data/ledger/` bereits als vorgesehene, host-persistente Konvention
(analog zu den beiden tatsächlich gemounteten Verzeichnissen) — die Umsetzung
fehlte schlicht.

**Zwei Konsequenzen, beide live bestätigt:**
1. Jeder `docker compose build`/`up -d`-Zyklus (Redeploy, Rebuild) erzeugt
   einen neuen Container mit leerer beschreibbarer Schicht — `data/ledger`
   existiert dann nicht, `JSONLedgerStore.load()` liefert für jede Persona
   `LedgerState(cash=default_cash)` (5.000 USD, keine Positionen) zurück, ganz
   ohne Fehler (`internal_ledger.py`s `_load` behandelt eine fehlende Datei
   als Neustart, nicht als Anomalie). **Auf der Box direkt verifiziert:** nach
   den heutigen F050-F053-Redeploys existiert `/app/data/ledger/` in weder
   `scheduler` noch `telegram-bot` — jeder vorherige Handelsstand der drei
   virtuellen Personas ist weg.
2. `scheduler` und `telegram-bot` sind zwei getrennte Container mit
   getrennten Dateisystemen. Ein HITL-Resume für eine `internal_ledger`-Persona
   läuft im `telegram-bot`-Prozess (`_maybe_execute_decision` →
   `execute_decision` → `InternalLedgerAdapter.place_order`) und hätte — auch
   ganz ohne Neustart — eine andere, unabhängige Ledger-Datei gesehen als der
   `scheduler`-Prozess, der denselben Zyklus gestartet hat. Doppelte/
   widersprüchliche Cash-/Positionsstände wären die Folge gewesen.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #3 Keine Order ohne persistierte Decision | nein | `decision`/`order_record` liegen unverändert korrekt in Postgres — betroffen ist ausschließlich der virtuelle Broker-Zustand (Cash/Positionen), der laut ADR 0001 bewusst außerhalb der DB lebt. |
| Datenintegrität (kein Invarianten-Name, aber Kern des Funds) | ja | Ohne Mount ist der Ledger-Zustand nicht überlebensfähig über einen Redeploy hinaus, und bei zwei Prozessen (scheduler/telegram-bot) sogar innerhalb eines einzigen Moments inkonsistent. Fix macht beides korrekt: ein gemeinsamer Host-Pfad für beide Container, persistent über Redeploys. |

**Kosten:** keine. **Bereits eingetretener Schaden (nicht rückgängig zu
machen):** falls HYPE/CONTRA/CRYPTOR vor den heutigen Redeploys offene
Positionen hatten, sind diese jetzt aus der Ledger-Sicht weg (die Postgres-
`decision`/`order_record`-Historie bleibt als Nachweis erhalten, nur der
virtuelle Broker-Zustand selbst ist zurückgesetzt). Alle drei Personas
starten ab jetzt faktisch wieder bei 5.000 USD Cash, 0 Positionen.

## 3. Testdefinition

Kein neuer Logik-Testbedarf — reine Deployment-Verdrahtung (gleiche
Einordnung wie F032/F049). Verifikation: `docker-compose.yml` bleibt gültiges
YAML (`yaml.safe_load`); nach Deploy `data/ledger` in beiden Containern
prüfen (`ls /app/data/ledger`), dass beide auf denselben Host-Pfad zeigen
(z. B. eine Test-Persona-Order in einem Container auslösen, Datei im anderen
Container sichtbar).

## 4. Implementierung

`docker-compose.yml`: `./data/ledger:/app/data/ledger` als Volume bei
`scheduler` und `telegram-bot` (gleicher Host-Pfad, damit beide Container
dieselbe Datei sehen).

## 5. Testdurchlauf

`uv run python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"`
→ lädt ohne Fehler.

## 6. Rollback-Pfad

Volume-Zeile entfernen + Commit zurücknehmen — fällt zurück auf den
(fehlerhaften) vorherigen Zustand. Kein Schema-Change.
