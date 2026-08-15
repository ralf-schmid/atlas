"""add backtest_run

Revision ID: d7e8f9a0b1c2
Revises: c9e8d7f6a5b4
Create Date: 2026-08-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c9e8d7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # F111: the backtest artefact contract (strategy_spec / config / fingerprint /
    # lineage / caveats) as one row per strategy run. Self-referencing FK for the
    # lineage chain — a run points at the previous run of the same spec.
    op.create_table(
        'backtest_run',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('spec_name', sa.String(length=100), nullable=False),
        sa.Column('status', sa.Enum('OK', 'INSUFFICIENT_DATA', name='backtest_run_status'), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('strategy_spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('data_fingerprint', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('caveats', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('equity_curve', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('trades', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('parent_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('lineage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['parent_run_id'], ['backtest_run.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backtest_run_spec_name_created', 'backtest_run', ['spec_name', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_backtest_run_spec_name_created', table_name='backtest_run')
    op.drop_table('backtest_run')
    sa.Enum(name='backtest_run_status').drop(op.get_bind(), checkfirst=True)
