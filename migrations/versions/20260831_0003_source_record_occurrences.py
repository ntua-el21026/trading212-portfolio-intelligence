"""Retain source-record membership for every ingestion run.

Revision ID: 20260831_0003
Revises: 20260831_0002
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0003"
down_revision: str | None = "20260831_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_record_occurrences",
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f(
                "fk_source_record_occurrences_ingestion_run_id_ingestion_runs"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_source_record_occurrences_source_record_id_source_records"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_record_occurrences")),
        sa.UniqueConstraint(
            "ingestion_run_id",
            "source_record_id",
            name="uq_source_record_occurrences_run_record",
        ),
    )
    op.create_index(
        "ix_source_record_occurrences_record",
        "source_record_occurrences",
        ["source_record_id"],
        unique=False,
    )
    op.create_index(
        "ix_source_record_occurrences_run",
        "source_record_occurrences",
        ["ingestion_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_record_occurrences_run",
        table_name="source_record_occurrences",
    )
    op.drop_index(
        "ix_source_record_occurrences_record",
        table_name="source_record_occurrences",
    )
    op.drop_table("source_record_occurrences")
