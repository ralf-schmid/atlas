"""unique review per decision (F084)

The review agent's idempotency rests on "decision has no review yet". Without a
DB-level unique index that holds only as long as no two sweeps overlap — and the
sweep is a scheduler job that can be triggered manually while the cron run is in
flight. The constraint turns a race into an IntegrityError instead of a duplicate
row in the record the competition is evaluated on.

Revision ID: a1b2c3d4e5f6
Revises: 8a25be33a9fe
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "8a25be33a9fe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_review_decision_id", "review", ["decision_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_review_decision_id", table_name="review")
