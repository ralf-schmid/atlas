"""add order_record.spread_bps

Revision ID: f7a1c2d3e4b5
Revises: e1f2a3b4c5d6
Create Date: 2026-08-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7a1c2d3e4b5'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # F104: nullable, no backfill — historical orders have no measured spread and
    # keep the config flat rate in `compute_slippage_malus`.
    op.add_column('order_record', sa.Column('spread_bps', sa.Numeric(precision=10, scale=4), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('order_record', 'spread_bps')
