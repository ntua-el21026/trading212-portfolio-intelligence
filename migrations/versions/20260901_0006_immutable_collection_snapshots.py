"""Add immutable result snapshots for mutable Phase 1 collections.

Revision ID: 20260901_0006
Revises: 20260901_0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0006"
down_revision: str | None = "20260901_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_query_snapshots",
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("resource", sa.String(length=24), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("broker_account_id", sa.Uuid(), nullable=True),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("sort_specification", sa.String(length=100), nullable=False),
        sa.Column("filter_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("exact_total", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name=op.f("ck_collection_query_snapshots_schema_version_supported"),
        ),
        sa.CheckConstraint(
            "resource IN ('activity','dividends','instruments','positions_market_value',"
            "'positions_weight','positions_ticker')",
            name=op.f("ck_collection_query_snapshots_resource_allowed"),
        ),
        sa.CheckConstraint(
            "(resource = 'activity' AND "
            "sort_specification = 'occurred_at_desc_id_desc') OR "
            "(resource = 'dividends' AND "
            "sort_specification = 'paid_on_desc_id_desc') OR "
            "(resource = 'instruments' AND "
            "sort_specification = "
            "'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR "
            "(resource = 'positions_market_value' AND "
            "sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR "
            "(resource = 'positions_weight' AND "
            "sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR "
            "(resource = 'positions_ticker' AND "
            "sort_specification = 'ticker_asc_listing_id_asc')",
            name=op.f("ck_collection_query_snapshots_resource_sort_match"),
        ),
        sa.CheckConstraint(
            "((resource IN ('activity','dividends','positions_market_value',"
            "'positions_weight','positions_ticker') AND broker_account_id IS NOT NULL) OR "
            "(resource = 'instruments' AND broker_account_id IS NULL))",
            name=op.f("ck_collection_query_snapshots_account_scope_match"),
        ),
        sa.CheckConstraint(
            "((resource IN ('positions_market_value','positions_weight','positions_ticker') "
            "AND source_snapshot_id IS NOT NULL) OR "
            "(resource NOT IN ('positions_market_value','positions_weight','positions_ticker') "
            "AND source_snapshot_id IS NULL))",
            name=op.f("ck_collection_query_snapshots_source_snapshot_scope_match"),
        ),
        sa.CheckConstraint(
            "filter_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_collection_query_snapshots_filter_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "exact_total >= 0",
            name=op.f("ck_collection_query_snapshots_exact_total_nonnegative"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_collection_query_snapshots_expiry_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_collection_query_snapshots_broker_account_id_broker_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_collection_query_snapshots_owner_id_owners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["portfolio_snapshots.id"],
            name=op.f("fk_collection_query_snapshots_source_snapshot_id_portfolio_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_query_snapshots")),
    )
    op.create_index(
        "ix_collection_query_snapshots_expiry",
        "collection_query_snapshots",
        ["expires_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_query_snapshots_scope",
        "collection_query_snapshots",
        [
            "owner_id",
            "broker_account_id",
            "resource",
            "filter_fingerprint",
            "expires_at",
        ],
        unique=False,
    )
    op.create_index(
        "ix_collection_query_snapshots_owner_expiry",
        "collection_query_snapshots",
        ["owner_id", "expires_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_query_snapshots_broker_account",
        "collection_query_snapshots",
        ["broker_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_query_snapshots_source_snapshot",
        "collection_query_snapshots",
        ["source_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "collection_query_snapshot_members",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.BigInteger(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 1",
            name=op.f("ck_collection_query_snapshot_members_ordinal_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["collection_query_snapshots.id"],
            name="fk_collection_snapshot_member_snapshot",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id",
            "ordinal",
            name=op.f("pk_collection_query_snapshot_members"),
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "record_id",
            name="uq_collection_snapshot_member_record",
        ),
    )


def downgrade() -> None:
    op.drop_table("collection_query_snapshot_members")
    op.drop_index(
        "ix_collection_query_snapshots_source_snapshot",
        table_name="collection_query_snapshots",
    )
    op.drop_index(
        "ix_collection_query_snapshots_broker_account",
        table_name="collection_query_snapshots",
    )
    op.drop_index(
        "ix_collection_query_snapshots_scope",
        table_name="collection_query_snapshots",
    )
    op.drop_index(
        "ix_collection_query_snapshots_owner_expiry",
        table_name="collection_query_snapshots",
    )
    op.drop_index(
        "ix_collection_query_snapshots_expiry",
        table_name="collection_query_snapshots",
    )
    op.drop_table("collection_query_snapshots")
