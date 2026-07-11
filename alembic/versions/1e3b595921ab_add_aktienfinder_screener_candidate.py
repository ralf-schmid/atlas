"""add aktienfinder screener candidate

Revision ID: 1e3b595921ab
Revises: 4708e243f853
Create Date: 2026-07-11 09:54:10.997425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1e3b595921ab'
down_revision: Union[str, Sequence[str], None] = '4708e243f853'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('aktienfinder_screener_candidate',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('isin', sa.String(length=20), nullable=False),
    sa.Column('ticker', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('region', sa.String(length=50), nullable=False),
    sa.Column('discovered_at', sa.Date(), nullable=False),
    sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('isin', 'discovered_at', name='uq_aktienfinder_screener_candidate_isin_date')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('aktienfinder_screener_candidate')
