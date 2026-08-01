"""FILLED orders need a fill price (F096)

`order_record.status` was derived from `filled_at` alone, which made "FILLED with
no fill_price" representable — two such rows exist from 2026-07-12. Everything
downstream (review deviation, slippage malus, holdings charts) then reads a fill it
cannot price.

Added NOT VALID on purpose: those two rows belong to archived pre-season portfolios
(F090 reset), their real prices are unrecoverable (the internal ledger state was
wiped), and inventing a price from a DAY bar would falsify financial history in a
system whose whole point is traceability. NOT VALID guards every future insert and
update without rewriting the past.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_order_record_filled_has_price"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE order_record ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (status <> 'FILLED' OR fill_price IS NOT NULL) NOT VALID"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE order_record DROP CONSTRAINT {_CONSTRAINT}")
