"""One-off backfill for F075 (docs/features/F075-order-fill-reconciliation.md).

Fixes `order_record` rows for virtual (`internal_ledger`) personas that were
placed *before* this feature shipped and so never got `status=FILLED`. Their
fill is known to have happened at `submitted_at` (InternalLedgerAdapter fills
synchronously, in the same call as order placement) — that timestamp is exact,
not an estimate. `fill_price` is left `NULL`: it was genuinely never recorded
for these pre-existing rows and cannot be reconstructed (the position's
avg_entry_price is a weighted average across any later top-ups too, F071).

Not part of regular operation — `reconcile_order_fills` (scheduler.py) and
`execute_decision` (trading.py) handle every order going forward. Native
(`alpaca_paper`) personas need no backfill: `reconcile_order_fills` polls
Alpaca, which still remembers their real historical fill status.

Usage: DATABASE_URL=... uv run python scripts/backfill_ledger_order_fills.py
"""

from __future__ import annotations

from sqlalchemy import select

from src.broker.registry import get_adapter_type
from src.db.base import get_session_factory
from src.db.models import Decision, OrderRecord, OrderRecordStatus, Persona, Portfolio


def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        stmt = (
            select(OrderRecord, Persona.name)
            .join(Decision, OrderRecord.decision_id == Decision.id)
            .join(Portfolio, Decision.portfolio_id == Portfolio.id)
            .join(Persona, Portfolio.persona_id == Persona.id)
            .where(OrderRecord.status == OrderRecordStatus.NEW)
        )
        rows = session.execute(stmt).all()

        updated = 0
        for order_record, persona_name in rows:
            if get_adapter_type(persona_name) != "internal_ledger":
                continue
            order_record.status = OrderRecordStatus.FILLED
            order_record.filled_at = order_record.submitted_at
            session.add(order_record)
            updated += 1
            print(f"{persona_name}: order_record {order_record.id} -> FILLED")

        session.commit()
        print(f"Backfilled {updated} order_record row(s)")


if __name__ == "__main__":
    main()
