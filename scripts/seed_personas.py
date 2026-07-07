"""Seeds the 6 real persona/portfolio rows. Idempotent — safe to re-run.

Usage: DATABASE_URL=... uv run python scripts/seed_personas.py
"""

from __future__ import annotations

from src.db.base import get_session_factory
from src.orchestrator.seed import seed_personas_and_portfolios


def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        count = seed_personas_and_portfolios(session)
        session.commit()
        print(f"seeded/updated {count} personas + portfolios")


if __name__ == "__main__":
    main()
