"""add reddit_post

Revision ID: c59e1bad9f32
Revises: ce9754a967cb
Create Date: 2026-07-08 18:02:46.931858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c59e1bad9f32'
down_revision: Union[str, Sequence[str], None] = 'ce9754a967cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('reddit_post',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('post_id', sa.String(length=20), nullable=False),
    sa.Column('subreddit', sa.String(length=100), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('num_comments', sa.Integer(), nullable=False),
    sa.Column('created_utc', sa.DateTime(), nullable=False),
    sa.Column('permalink', sa.String(length=500), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('reddit_post')
