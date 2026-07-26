"""add portfolio archived_at for season reset

Revision ID: 8a25be33a9fe
Revises: 92ad7d28c742
Create Date: 2026-07-26 10:56:46.373873

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a25be33a9fe'
down_revision: Union[str, Sequence[str], None] = '92ad7d28c742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # F090: NULL = active (current) season, a timestamp = archived pre-season.
    # Additive and nullable, so every existing portfolio stays active (NULL) until
    # the competition reset explicitly archives it. Transactional DDL — no COMMIT
    # hack needed (unlike the enum ADD VALUE in 92ad7d28c742).
    op.add_column("portfolio", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio", "archived_at")
