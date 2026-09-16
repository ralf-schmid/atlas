"""F121 manual fallback: writes the closing valuation of the competition's last day.

The scheduler does this on its own at 16:35 ET on `competition.end_date`
(`src/orchestrator/scheduler.py`, job `competition-settlement`). This script exists
for the case that matters: the container was down at that moment, or a single
portfolio failed. Running it again is harmless — the report reads the *last*
snapshot before the cutoff.

Usage (on the box):
  sudo docker compose exec -T scheduler /app/.venv/bin/python scripts/final_settlement.py
Optional: --now 2026-09-18T20:35 (naive UTC) to stamp a specific settlement time.
"""

from __future__ import annotations

import argparse
import datetime

from src.broker.registry import get_adapter
from src.db.base import get_session_factory
from src.orchestrator.competition_config import load_competition_config
from src.orchestrator.competition_settlement import (
    market_close_utc,
    run_final_settlement,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the competition closing valuation")
    parser.add_argument("--now", help="naive UTC timestamp to stamp (default: now)")
    args = parser.parse_args()

    config = load_competition_config()
    if config.end_date is None:
        raise SystemExit("config/competition.yaml has no competition.end_date")

    now = (
        datetime.datetime.fromisoformat(args.now)
        if args.now
        else datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    )
    close = market_close_utc(config.end_date)
    if now < close:
        print(
            f"WARNING: {now} is before the {config.end_date} close ({close} UTC) — "
            "this would not be a closing valuation."
        )

    session_factory = get_session_factory()
    with session_factory() as session:
        result = run_final_settlement(session, get_adapter, now)
        session.commit()
    print(f"settled at {result.settled_at}: {', '.join(result.personas) or 'none'}")
    if result.failed:
        raise SystemExit(f"failed for: {', '.join(result.failed)}")


if __name__ == "__main__":
    main()
