"""meta_review for sampled reject_idea decisions (F099)

Own table rather than more rows in `review`: `review` is the competition's
evaluation record and everything that aggregates over it assumes a decision that
reached a market. See src/db/models.py::MetaReview.

`lessons_embedding` mirrors `review` (1024, multilingual-e5-large, ADR-0013) and is
written from day one so that wiring meta-lessons into the persona prompt later is a
query change, not a backfill. No index, for the same reason as c3d4e5f6a7b8: at most
5 rows a week.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

# Enum *names*, not values — SQLAlchemy's `Enum(PyEnum)` persists `.name` by
# default, and every other enum type in this schema (decision_action,
# review_verdict) is stored that way. Lowercase labels here would compile fine and
# then fail on the first INSERT.
_VERDICT_VALUES = ("RESEARCH_SUFFICIENT", "RESEARCH_GAP", "RESEARCH_IGNORED")
_VERDICT_NAME = "meta_review_verdict"


def upgrade() -> None:
    postgresql.ENUM(*_VERDICT_VALUES, name=_VERDICT_NAME).create(op.get_bind(), checkfirst=True)
    op.create_table(
        "meta_review",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        # create_type=False: the type is created explicitly above (checkfirst), so
        # the implicit CREATE TYPE this column emits must not fire a second time.
        sa.Column(
            "verdict",
            postgresql.ENUM(*_VERDICT_VALUES, name=_VERDICT_NAME, create_type=False),
            nullable=False,
        ),
        sa.Column("missing_source", sa.Text(), nullable=True),
        sa.Column("lessons_text", sa.Text(), nullable=True),
        sa.Column("lessons_embedding", Vector(1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["decision_id"], ["decision.id"]),
        sa.UniqueConstraint("decision_id", name="uq_meta_review_decision_id"),
    )


def downgrade() -> None:
    op.drop_table("meta_review")
    postgresql.ENUM(name=_VERDICT_NAME).drop(op.get_bind(), checkfirst=True)
