"""Permit explicit unconfigured broker credentials.

Revision ID: 20260901_0005
Revises: 20260901_0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0005"
down_revision: str | None = "20260901_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "broker_connections",
        "credential_reference",
        existing_type=sa.String(length=500),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE broker_connections SET credential_reference = '' "
            "WHERE credential_reference IS NULL"
        )
    )
    op.alter_column(
        "broker_connections",
        "credential_reference",
        existing_type=sa.String(length=500),
        nullable=False,
    )
