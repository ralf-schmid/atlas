"""add_execution_failed_to_decision_status

Revision ID: 92ad7d28c742
Revises: 1e3b595921ab
Create Date: 2026-07-25 19:19:20.491905

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '92ad7d28c742'
down_revision: Union[str, Sequence[str], None] = '1e3b595921ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # F080: ALTER TYPE ADD VALUE cannot run inside a transaction block in
    # Postgres. The env.py wraps this in context.begin_transaction(), so
    # we commit that first, execute the ALTER, then Alembic's post-upgrade
    # COMMIT is harmless (no-op on a connection without an active xact).
    # The new value is appended at the end — order is irrelevant for
    # DecisionStatus (no ordinal comparison in the code).
    # Downgrade is a no-op: Postgres cannot remove an enum value without
    # rebuilding the type; a harmless unused value is acceptable.
    op.get_bind().exec_driver_sql("COMMIT")
    op.execute("ALTER TYPE decision_status ADD VALUE 'EXECUTION_FAILED'")


def downgrade() -> None:
    # Postgres does not support removing a value from an ENUM type without
    # recreating it. An unused extra value is harmless — no-op.
    pass
