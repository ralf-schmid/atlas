"""F090 competition reset — one-shot, manual, against the real DB + ledger.

Archives the pre-season portfolios and creates fresh 5000-USD ones for the
official competition start (docs/features/F090-competition-reset-and-start.md).

PRECONDITIONS (Ralf, before running — see ADR-0009):
  1. The 3 native Alpaca paper accounts have been recreated at 5000 USD in the
     dashboard, their NEW API keys are in the box .env, and the containers have
     been restarted so the native adapters see the new accounts.
  2. scripts/../src/orchestrator/seed.py `_NATIVE_ACCOUNT_IDS` has been updated to
     the NEW account ids (used as broker_account_ref for the fresh portfolios).
  Running before (1) would point the fresh portfolios at the old, drifted accounts.

Idempotency-guarded: a second run for the same start_date refuses (raises/prints
SKIP) instead of double-archiving.

Usage (on the box, no image rebuild needed if run from the mounted repo path):
  sudo docker compose exec -T scheduler /app/.venv/bin/python scripts/reset_competition.py
"""

from __future__ import annotations

from src.broker.ledger_store import JSONLedgerStore
from src.db.base import get_session_factory
from src.orchestrator.competition_config import load_competition_config
from src.orchestrator.competition_reset import (
    CompetitionAlreadyResetError,
    reset_competition,
)
from src.orchestrator.seed import _NATIVE_ACCOUNT_IDS


def main() -> None:
    config = load_competition_config()
    session_factory = get_session_factory()
    ledger_store = JSONLedgerStore()

    print(
        f"competition reset: start_date={config.start_date} "
        f"start_capital={config.start_capital_usd} "
        f"native_accounts={_NATIVE_ACCOUNT_IDS}"
    )
    with session_factory() as session:
        try:
            result = reset_competition(
                session,
                ledger_store,
                start_date=config.start_date,
                start_capital_usd=config.start_capital_usd,
                native_account_ids=_NATIVE_ACCOUNT_IDS,
            )
        except CompetitionAlreadyResetError as exc:
            print(f"SKIP: {exc}")
            raise SystemExit(0) from exc
        session.commit()

    print(
        f"reset done: archived={result.archived_count} created={result.created_count} "
        f"ledger_reset={result.ledger_reset_personas}"
    )


if __name__ == "__main__":
    main()
