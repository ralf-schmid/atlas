"""lessons embedding for the review-to-analysis feedback loop (F098)

Enables pgvector and adds `review.lessons_embedding`. Dimension 1024 = bge-m3
(CLAUDE.md names the model); changing the model means changing this column, so it
is deliberately not configurable.

No index: the retrieval is scoped to a single persona's reviews, which is a handful
of rows for the whole competition. An ivfflat/hnsw index on a table this small costs
more than the sequential scan it replaces, and both need tuning against a row count
that does not exist yet.

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "c3d4e5f6a7b8"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("review", sa.Column("lessons_embedding", Vector(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("review", "lessons_embedding")
    # The extension stays: dropping it would break any other vector column.
