# F005 — Telegram-Bot-Grundgerüst

Status: umgesetzt
Datum: 2026-07-05
Phase: 2

## 1. Zieldefinition

Grundgerüst für den einen Telegram-Bot mit drei Funktionen (ARCHITECTURE.md §6.4):
HITL-Approvals (Inline-Buttons ✅/❌, 30-Min-Timeout = Reject), Alerts, täglicher Digest.
Plus Kommandos `/status`, `/pause <persona>`, `/resume <persona>`, `/hitl on|off`,
`/digest`. Sicherheit: nur die konfigurierte Chat-ID wird akzeptiert.

Per explizitem Entscheidungsstand (AGENTS.md, Punkt 6): *"Telegram-Bot: Ralf liefert
Token + Chat-ID, sobald das Bot-Grundgerüst steht — bis dahin gegen Dummy-Config
entwickeln, Bot-Funktionen testbar mocken."* Dieses Feature liefert genau das: die komplette
Logik (HITL-Zustandsmaschine, Timeout, Kommando-Parsing, Digest-Rendering,
Chat-ID-Sicherheitsgate) als reine, getestete Funktionen, plus eine dünne
`python-telegram-bot`-Verdrahtung. Der Inline-Button-Callback lädt eine pending
Decision per UUID, wendet Timeout/Approve/Reject deterministisch an und persistiert das
Ergebnis in `decision.hitl` + `decision.status`.

## 2. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| HITL-Timeout = Reject, nicht hart codiert umgehbar | ja | `hitl.py` implementiert Timeout als reine Zeitvergleichsfunktion (`is_expired`), die immer `reject` liefert nach Ablauf — kein Pfad, der das umgeht. |
| Bot akzeptiert nur konfigurierte Chat-ID | ja | `security.is_authorized_chat()` wird als globaler Filter auf **jeden** Handler angewendet (Kommandos **und** Callback-Queries), nicht nur auf einzelne Kommandos — sonst wären HITL-Buttons ein Angriffsvektor (ARCHITECTURE.md Zeile 489). |
| #6 Secrets nie im Repo | ja | `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` aus Environment, Dummy-Werte in `.env.example`. |
| Digest ist Code, kein LLM (§7 Punkt 3) | ja | `digest.py` rendert ausschließlich über ein Jinja2-Template auf strukturierten Daten (`DigestData`-Dataclass) — kein LLM-Aufruf. |
| Keine Persona-Bevorzugung | ja | `/pause`/`/resume` nehmen den Persona-Namen als Parameter, keine Sonderbehandlung einzelner Personas im Code. |

**Design-Entscheidungen:**
- **Library:** `python-telegram-bot` (async, `Application`-Pattern) — Standard für
  Telegram-Bots in Python, aktiv gepflegt.
- **HITL-Persistenz:** Offene Requests liegen auf der persistierten Decision:
  `decision.status = hitl_pending`, Metadaten in `decision.hitl`. Der Callback verarbeitet
  ausschließlich pending Decisions per DB-ID und schreibt `approved` oder `hitl_rejected`
  zurück. Eine separate HITL-Tabelle ist für Phase 2 nicht nötig.
- **Digest-Daten:** `DigestData` ist bewusst eine einfache Dataclass (nicht direkt an
  SQLAlchemy-Modelle gekoppelt), damit `digest.py` ohne DB-Verbindung testbar bleibt —
  das tatsächliche Füllen aus `portfolio_snapshot`/`order_record`/`cost_ledger` ist
  Folgearbeit (braucht die noch nicht existierenden Snapshot-Erzeugungs-Jobs).

**Kosten:** keine LLM-Calls. **Fairness:** identischer Code-Pfad für alle Personas.

## 3. Testdefinition (vor Umsetzung)

Unit-Tests (`tests/telegram/`), keine echte Telegram-API, keine Netzwerkzugriffe:

1. `is_authorized_chat`: konfigurierte Chat-ID → `True`; jede andere ID → `False`.
2. `HitlRequest` vor Ablauf der 30 Minuten → `is_expired() == False`.
3. `HitlRequest` nach Ablauf → `is_expired() == True`.
4. `process_callback` mit `"approve"` vor Timeout → `HitlDecision.APPROVED`,
   `decided_by="user"`.
5. `process_callback` mit `"reject"` → `HitlDecision.REJECTED`, `decided_by="user"`.
6. `process_callback`, wenn `is_expired()` bereits `True` ist → `HitlDecision.REJECTED`,
   `decided_by="timeout"`, unabhängig vom Callback-Inhalt.
7. `format_approval_message`: enthält Instrument, Thesis, Betrag, Stop-Preis.
8. `parse_pause_command`/`parse_resume_command`: extrahieren den Persona-Namen aus
   `/pause VULTURE`; fehlender Parameter → `ValueError` mit Hinweistext.
9. `render_daily_digest`: enthält Trades je Persona, Depotwerte, Cash, offene Positionen,
   LLM-Kosten aus `DigestData` — keine LLM-Aufrufe im Renderpfad.
10. Bot-Grundgerüst (`bot.py`) baut eine `Application` mit Dummy-Token ohne Fehler
    (Konstruktion prüft das Token-Format nicht, nur die eigentliche `run_polling()`
    würde einen echten Token brauchen — hier nicht aufgerufen).
11. HITL-Callback ohne DB-Session liefert eine klare Fehlermeldung.
12. HITL-Callback mit pending Decision persistiert das Ergebnis und aktualisiert die
    Telegram-Nachricht.

## 4. Implementierung

`src/telegram/config.py`, `security.py`, `hitl.py`, `hitl_store.py`, `digest.py`,
`commands.py`, `bot.py`.

## 5. Testdurchlauf

`uv run pytest tests/telegram/` → 41 passed, 6 skipped ohne `DATABASE_URL`
(DB-Store-Tests benötigen echten Postgres/Migrationen). `uv run ruff check src/telegram
tests/telegram` → sauber. Der Callback-Pfad ist unit-getestet; die DB-Store-Tests laufen,
sobald `DATABASE_URL` auf eine Test-Postgres zeigt.

**Nebenbei gefunden:** Testordner ohne `__init__.py` führten zu einer Modulnamens-Kollision
(`tests/risk/test_config.py` vs. `tests/telegram/test_config.py`, beide `test_config`) —
behoben durch `__init__.py` in allen `tests/`-Unterordnern.

Echter Bot-Test wurde am 2026-07-05 mit Ralfs `@ralf_atlas_bot` durchgeführt:
Testnachricht gesendet, Inline-Button-Callback empfangen und beantwortet. Die danach
ergänzte DB-Persistenz wurde lokal über Tests abgesichert.

## 6. Rollback-Pfad

Additives Feature, keine Seiteneffekte außerhalb des Telegram-Bot-Prozesses selbst (der
noch nirgends automatisch gestartet wird). Rollback = Commit zurücknehmen.
