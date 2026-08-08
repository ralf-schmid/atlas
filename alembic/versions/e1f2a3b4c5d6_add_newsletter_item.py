"""add newsletter_item

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('newsletter_item',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('newsletter_slug', sa.String(length=50), nullable=False),
    sa.Column('message_id', sa.String(length=300), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('section', sa.String(length=100), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=2000), nullable=True),
    sa.Column('issue_url', sa.String(length=2000), nullable=True),
    sa.Column('instruments', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('links', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id', 'seq', name='uq_newsletter_item_message_seq')
    )
    # research_synthesis windows every ingestion table by `synced_at` — the same
    # access pattern the other source tables have, and the only query that runs
    # against this table in the cycle hot path.
    op.create_index(
        'ix_newsletter_item_synced_at', 'newsletter_item', ['synced_at'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_newsletter_item_synced_at', table_name='newsletter_item')
    op.drop_table('newsletter_item')
