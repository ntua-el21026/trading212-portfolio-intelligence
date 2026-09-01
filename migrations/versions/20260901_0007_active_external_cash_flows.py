"""Persist the active state of external cash-flow revisions.

Revision ID: 20260901_0007
Revises: 20260901_0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0007"
down_revision: str | None = "20260901_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cash_flows",
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    # Existing installations may already retain a status-only reversal revision.
    # The new server default is correct for ordinary historical rows, but reversed
    # source transactions must be deactivated during the schema transition itself.
    op.execute(
        sa.text(
            """
            UPDATE cash_flows AS cash_flow
            SET active = FALSE
            FROM transactions AS source_transaction
            WHERE cash_flow.source_transaction_id = source_transaction.id
              AND lower(source_transaction.status) = 'reversed'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("cash_flows", "active")
