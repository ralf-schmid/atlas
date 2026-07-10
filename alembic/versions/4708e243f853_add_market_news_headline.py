"""add market_news_headline

Revision ID: 4708e243f853
Revises: 4a5af5b72b93
Create Date: 2026-07-10 22:04:25.466911

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4708e243f853"
down_revision: Union[str, Sequence[str], None] = "4a5af5b72b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "market_news_headline",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("guid", sa.String(length=300), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guid"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("market_news_headline")
