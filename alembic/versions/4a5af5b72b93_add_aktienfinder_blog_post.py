"""add aktienfinder_blog_post

Revision ID: 4a5af5b72b93
Revises: c59e1bad9f32
Create Date: 2026-07-08 22:15:41.802309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4a5af5b72b93'
down_revision: Union[str, Sequence[str], None] = 'c59e1bad9f32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('aktienfinder_blog_post',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('post_id', sa.String(length=20), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('categories', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('is_premium', sa.Boolean(), nullable=False),
    sa.Column('published_at', sa.Date(), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('aktienfinder_blog_post')
