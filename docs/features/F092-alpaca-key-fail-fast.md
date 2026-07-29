# F092 — Fail-Fast bei ungültigem Alpaca-Key

**Status:** Draft
**Phase:** 5 (Härtung)
**Abhängigkeiten:** `src/broker/protocol.py`, `src/broker/alpaca_paper.py`,
`src/broker/registry.py`, `scripts/run_scheduler.py`
Berührt Invariante **#5** (Paper/Live-Trennung) und **#6** (Secrets nie im Repo).

## 1. Zieldefinition

Ein falscher/abgelaufener Alpaca-Key führt aktuell zu einer stillen 401-Schleife
über Tage hinweg — der Scheduler läuft, jeder Cycle bricht mit `APIError(401)`,
der Exception-Handler in `scheduler.py:267` zählt einen Consecutive-Failure, aber
die Ursache ist weder im Log auf den ersten Blick sichtbar noch stoppt der Prozess.
Das hat im Juli 2026 3 Tage operativer Zeit gekostet.

F092 baut eine Start-up-Validierung: **bevor** der Scheduler den ersten Cycle startet
(oder der Telegram-Bot auf HITL hört), werden alle konfigurierten Alpaca-Keys
(3 Paper-Accounts + 1 Market-Data-Key) gegen die Live-Alpaca-API geprüft. Bei
Fehler: sofortiger Abbruch mit klarer Fehlermeldung + Telegram-Alarm.

## 2. Kontext / Ist-Zustand

- **Keine Validierung bei Startup:** `AlpacaPaperAdapter.__init__` ruft nur
  `TradingClient(api_key, secret_key, paper=True)` auf — der Alpaca-SDK validiert
  Keys **nicht** beim Client-Bau, sondern erst beim ersten API-Call.
- **Erster API-Call tief im Cycle:** Der erste echte Aufruf ist `get_positions()`
  in `persona_analysis.py:161` (Topf `_safe_generate_portfolio_snapshot`). Der
  Fehler wird von `except Exception` gefangen und als `AgentRun(status=FAILED)`
  persistiert. Der nächste Cycle retried — und scheitert wieder. Kein Exit.
- **3 Paper-Keys + 1 Market-Data-Key:** Sechs Personas, davon drei mit
  Alpaca-Adaptern (VULTURE, GUARDIAN, CHARTIST) — jeder ein separater Key.
  Market-Data-Key für Kursdaten/charts. HYPE/CONTRA/CRYPTOR nutzen
  `InternalLedgerAdapter` (kein externer Key).
- **Market-Data-Key separat:** `build_market_data_provider()` liest
  `ALPACA_MARKET_DATA_*` aus env. Wird von API-Route (`_try_live_price`) und
  vom Ingestion-Sync-Job genutzt — auch dort keine Validierung vor Erstnutzung.
- **Telegram-Bot:** Initialisiert auch Alpaca-Adapter (für HITL-Resume =
  `_persona_analysis_node` → `get_positions()`); ein invalid Key killt auch
  den HITL-Callback-Listener, wenn eine Persona resumed wird.

## 3. Design

### 3.1 BrokerAdapter-Protocol erweitern

```python
class BrokerAdapter(Protocol):
    def validate_credentials(self) -> None: ...
```

Ruft einen simplen Read-Only-API-Call auf (`get_account()`) — bei 401/403
fliegt `APIError` (kein spezieller neuer Exception-Typ nötig).

### 3.2 Implementierungen

- **`AlpacaPaperAdapter.validate_credentials()`:** `self._client.get_account()`
  — schlägt fehl bei falschem Key, liefert bei gültigem Key ein Account-Objekt.
- **`InternalLedgerAdapter.validate_credentials()`:** `pass` — keine externen
  Credentials, kann nicht fehlschlagen.

### 3.3 Registry-Helper

```python
def validate_all_credentials(config_path: Path = _DEFAULT_CONFIG_PATH) -> None:
    """Validate ALL configured Alpaca keys at startup. Raises on first failure."""
```

Ruft für jede konfigurierte Persona `get_adapter(persona).validate_credentials()`
auf, plus `build_market_data_provider(...).validate_credentials()` für den
Market-Data-Key. Schema: `alpaca_paper` → validieren, `internal_ledger` → skip.

### 3.4 Entry-Point-Integration

- **`scripts/run_scheduler.py`:** Nach Config-Load, vor der Scheduler-Schleife
  `validate_all_credentials()` aufrufen. Bei Fehler: Log (level=CRITICAL),
  Telegram-Alarm senden, `sys.exit(1)`. Der Docker-Restart-Policy macht <3
  Restarts, dann `manual intervention` (docker-compose restart fällt irgendwann
  aus — gewollt).
- **`scripts/run_telegram_bot.py:** Gleiches Pattern — vor dem Polling-Loop.
- **`scripts/run_cycle.py`:** Gleiches Pattern — vor `build_and_compile_graph()`.
- **Market-Data-Job** (`src/ingestion/scheduler.py`): Vor dem ersten Batch
  `build_market_data_provider().validate_credentials()` — gleiches Fail-Fast.
- **API-Route** (`_try_live_price` in `routes.py`): Fail-Fast nicht sinnvoll
  (REST-Endpoint soll auch bei invalidem Key 200 mit `price: null` liefern).
  Die Startup-Validierung deckt das ab: wenn der Scheduler stirbt, ist klar,
  dass auch die API keine Live-Preise liefern kann.

### 3.5 Telegram-Alarm

Der Fail-Fast-Exit sendet eine Nachricht an den konfigurierten Chat:
```
🚨 Scheduler-Start abgebrochen: Alpaca-Key invalid
Persona: GUARDIAN (ALPACA_PAPER_GUARDIAN_*)
Fehler: 401 Unauthorized — key expired or wrong account
```
Der Alarm nutzt den vorhandenen `TelegramNotifier` (`src/telegram/notifier.py`).

## 4. Scope

- `src/broker/protocol.py` — `validate_credentials()` zum Protocol
- `src/broker/alpaca_paper.py` — Implementierung (ruft `get_account()`)
- `src/broker/internal_ledger.py` — No-op
- `src/broker/registry.py` — `validate_all_credentials()` + Market-Data-Variante
- `src/broker/market_data.py` — `validate_credentials()` am MarketDataProvider-Protocol
- `scripts/run_scheduler.py` — Validierung vor Loop
- `scripts/run_telegram_bot.py` — Validierung vor Loop
- `scripts/run_cycle.py` — Validierung vor Graph-Build
- `src/ingestion/scheduler.py` — Validierung im Market-Data-Job
- Tests

**Non-Scope:** Keine Änderung an Alpaca-SDK, kein Retry-Mechanismus, kein
HITL-Umweg (validieren ist immer erlaubt — Read-Only). Kein neuer Config-Wert
(die Keys liegen bereits in `config/broker.yaml`).

## 5. Testdefinition

1. **`AlpacaPaperAdapter.validate_credentials()`** — Mock `get_account()`:
   - Gültiger Key → kein Fehler
   - 401 → `APIError` propagiert
2. **`InternalLedgerAdapter.validate_credentials()`** — immer erfolgreich (No-op)
3. **`validate_all_credentials()`** — Mock `get_adapter()`:
   - Alle Keys gültig → `None`
   - Ein invalid Key → `ValueError`/`APIError` propagiert
   - Market-Data-Key invalid → propagiert
4. **Integration (opt-in):** Gegen echten Paper-Account — gültiger + bewusst
   falscher Key testen. Manuell, nicht in CI (braucht Secrets).

## 6. Kritische Betrachtung

- **Invariante #5:** Nur Paper-Keys validieren (in P5 gibt es keine Live-Keys).
  Wenn später Live-Keys hinzukommen, müssen die auch validiert werden — aber
  erst wenn sie existieren (der Config-Eintrag muss dann auch `alpaca_live`
  supporten → Phase 6).
- **Rate-Limit:** `get_account()` ist ein einzelner GET-Call — kein Problem.
- **Startup-Latenz:** ~3 API-Calls (3 Paper-Keys) + 1 Market-Data = <500 ms.
- **Docker-Restart-Loop:** Container startet, validiert, exit 1, Docker restart,
  nach 3× fällt der Container in `manual intervention`. Das ist gewollt —
  besser als 3 Tage stille 401-Schleife.

## 7. Rollback-Pfad

Commit revert — kein Config-Flag nötig. Die Validierung ist hart codiert und
soll immer laufen (das Feature hat keine Nachteile im fehlerfreien Fall).
