"""Dev-only seed: inserts one demo persona/portfolio/snapshot so the UI (F007)
has something to show locally. Not part of production code — no snapshot-
generation job exists yet (comes with the trading agent).

Commits for real — if pointed at the same DB as the test suite, run the tests
afterwards so their session-scoped fixture (tests/conftest.py) downgrades and
re-upgrades the schema, wiping this seed data before it can collide with a
test's own fixtures (e.g. a test creating its own "VULTURE" persona). Found by
hitting exactly that collision once during F007 verification.

Usage: DATABASE_URL=... uv run python scripts/seed_demo_snapshot.py
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from src.db.base import get_session_factory
from src.db.models import Persona, Portfolio, PortfolioMode, PortfolioSnapshot, PositionSnapshot


def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        persona = session.query(Persona).filter_by(name="VULTURE").one_or_none()
        if persona is None:
            persona = Persona(
                name="VULTURE",
                charter_version=1,
                model="claude-sonnet-5",
                config_ref="config/personas/vulture.yaml",
            )
            session.add(persona)
            session.flush()

        portfolio = session.query(Portfolio).filter_by(persona_id=persona.id).one_or_none()
        if portfolio is None:
            portfolio = Portfolio(
                persona_id=persona.id,
                mode=PortfolioMode.PAPER,
                broker_account_ref="PA32N1PG3J5G",
                base_ccy="USD",
                start_value=Decimal("5000.00"),
            )
            session.add(portfolio)
            session.flush()

        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        session.add(
            PortfolioSnapshot(
                ts=now,
                portfolio_id=portfolio.id,
                total_value=Decimal("5320.50"),
                cash=Decimal("2100.00"),
                pnl_realized=Decimal("120.00"),
                pnl_unrealized=Decimal("200.50"),
                benchmark_value=Decimal("5100.00"),
                max_drawdown=Decimal("0.0350"),
            )
        )
        session.add(
            PositionSnapshot(
                ts=now,
                portfolio_id=portfolio.id,
                instrument="AAPL",
                qty=Decimal("10"),
                avg_price=Decimal("150.00"),
                market_value=Decimal("1550.00"),
                pnl_unrealized=Decimal("50.00"),
            )
        )
        session.add(
            PositionSnapshot(
                ts=now,
                portfolio_id=portfolio.id,
                instrument="SOUN",
                qty=Decimal("300"),
                avg_price=Decimal("4.20"),
                market_value=Decimal("1670.50"),
                pnl_unrealized=Decimal("150.50"),
            )
        )
        session.commit()
        print(f"Seeded VULTURE portfolio snapshot at {now}")


if __name__ == "__main__":
    main()
