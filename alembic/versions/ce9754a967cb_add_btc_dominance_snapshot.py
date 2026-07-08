"""add btc_dominance_snapshot

Revision ID: ce9754a967cb
Revises: b8bf07d06546
Create Date: 2026-07-08 17:54:37.393090

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ce9754a967cb'
down_revision: Union[str, Sequence[str], None] = 'b8bf07d06546'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('btc_dominance_snapshot',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('snapshot_at', sa.DateTime(), nullable=False),
    sa.Column('btc_dominance_pct', sa.Numeric(precision=6, scale=3), nullable=False),
    sa.Column('total_market_cap_usd', sa.Numeric(precision=24, scale=2), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('btc_dominance_snapshot')
