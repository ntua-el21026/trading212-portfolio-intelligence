"""Persist complete calculation and reconciliation metadata.

Revision ID: 20260831_0002
Revises: 20260831_0001
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0002"
down_revision: str | None = "20260831_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calculation_runs",
        sa.Column(
            "input_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "reconciliation_runs",
        sa.Column(
            "quality_state",
            sa.String(length=30),
            server_default="partial",
            nullable=False,
        ),
    )
    op.add_column(
        "reconciliation_runs",
        sa.Column("coverage_complete", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "reconciliation_runs",
        sa.Column(
            "coverage_gaps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "reconciliation_runs",
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("reconciliation_runs", "quality_state", server_default=None)
    op.alter_column("reconciliation_runs", "coverage_complete", server_default=None)
    op.alter_column("reconciliation_runs", "provenance", server_default=None)


def downgrade() -> None:
    op.drop_column("reconciliation_runs", "provenance")
    op.drop_column("reconciliation_runs", "coverage_gaps")
    op.drop_column("reconciliation_runs", "coverage_complete")
    op.drop_column("reconciliation_runs", "quality_state")
    op.drop_column("calculation_runs", "input_ids")
