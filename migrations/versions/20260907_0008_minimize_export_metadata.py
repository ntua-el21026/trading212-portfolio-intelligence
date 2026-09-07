"""Remove retained provider export download URLs without copying them.

Revision ID: 20260907_0008
Revises: 20260901_0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0008"
down_revision: str | None = "20260901_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE source_records
            SET sanitized_payload = sanitized_payload - 'downloadLink' - 'download_link'
            WHERE capability = 'historical_exports'
              AND jsonb_typeof(sanitized_payload) = 'object'
              AND (sanitized_payload ? 'downloadLink' OR sanitized_payload ? 'download_link')
            """
        )
    )


def downgrade() -> None:
    """Privacy deletion is intentionally irreversible; no URL copy exists."""
