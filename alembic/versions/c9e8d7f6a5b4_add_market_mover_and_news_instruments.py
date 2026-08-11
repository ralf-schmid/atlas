"""add market_mover and market_news_headline.instruments

Revision ID: c9e8d7f6a5b4
Revises: f7a1c2d3e4b5
Create Date: 2026-08-11 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c9e8d7f6a5b4'
down_revision: Union[str, Sequence[str], None] = 'f7a1c2d3e4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # F105: server_default so the existing Yahoo rows (F058, no symbols in that
    # feed) get an empty array instead of NULL — the synthesis reads the column
    # unconditionally.
    op.add_column(
        'market_news_headline',
        sa.Column(
            'instruments',
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default='{}',
        ),
    )
    op.create_table('market_mover',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('market', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('price', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('change_pct', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('volume', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('screened_at', sa.DateTime(), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('market', 'category', 'symbol', 'screened_at', name='uq_market_mover_market_category_symbol_screened')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('market_mover')
    op.drop_column('market_news_headline', 'instruments')
