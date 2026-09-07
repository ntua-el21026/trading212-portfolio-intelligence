"""virtual targets

Revision ID: 20260907_0009
Revises: 20260907_0008
Create Date: 2026-09-07 16:18:52.393662
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0009"
down_revision: str | None = "20260907_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_collection_snapshots_owner_identity"),
        "collection_query_snapshots",
        ["owner_id", "id"],
    )
    op.create_table(
        "virtual_portfolios",
        sa.Column("broker_account_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reporting_currency ~ '^[A-Z]{3}$'", name=op.f("ck_virtual_portfolios_currency_format")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_virtual_portfolios_revision_positive")),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_virtual_portfolios_broker_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_virtual_portfolios_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_virtual_portfolios")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_virtual_portfolios_owner_id")),
    )
    op.create_index(
        "ix_virtual_portfolios_owner_updated",
        "virtual_portfolios",
        ["owner_id", "updated_at", "id"],
        unique=False,
    )
    op.create_table(
        "target_versions",
        sa.Column("virtual_portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(published_at IS NULL AND content_digest IS NULL AND state IN ('draft','archived')) OR (published_at IS NOT NULL AND content_digest IS NOT NULL AND content_digest ~ '^[0-9a-f]{64}$' AND state IN ('scheduled','active','superseded','archived'))",
            name=op.f("ck_target_versions_publication_fields"),
        ),
        sa.CheckConstraint(
            "state IN ('draft','scheduled','active','superseded','archived')",
            name=op.f("ck_target_versions_state_allowed"),
        ),
        sa.CheckConstraint(
            "revision >= 1 AND version_number >= 1",
            name=op.f("ck_target_versions_revisions_positive"),
        ),
        sa.CheckConstraint(
            "schema_version = 1", name=op.f("ck_target_versions_schema_version_supported")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_versions_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id", "parent_version_id"],
            [
                "target_versions.owner_id",
                "target_versions.virtual_portfolio_id",
                "target_versions.id",
            ],
            name="fk_target_version_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            name=op.f("fk_target_versions_owner_id_virtual_portfolios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_versions_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_versions")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_versions_owner_id")),
        sa.UniqueConstraint(
            "owner_id",
            "virtual_portfolio_id",
            "id",
            name="uq_target_versions_owner_portfolio_identity",
        ),
        sa.UniqueConstraint(
            "virtual_portfolio_id",
            "version_number",
            name=op.f("uq_target_versions_virtual_portfolio_id"),
        ),
    )
    op.create_index(
        "ix_target_versions_due", "target_versions", ["state", "effective_at", "id"], unique=False
    )
    op.create_index(
        "uq_target_versions_one_active",
        "target_versions",
        ["virtual_portfolio_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "virtual_portfolio_events",
        sa.Column("virtual_portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            name=op.f("fk_virtual_portfolio_events_owner_id_virtual_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_virtual_portfolio_events_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_virtual_portfolio_events")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_virtual_portfolio_events_owner_id")),
        sa.UniqueConstraint(
            "virtual_portfolio_id",
            "sequence",
            name=op.f("uq_virtual_portfolio_events_virtual_portfolio_id"),
        ),
    )
    op.create_table(
        "target_nodes",
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("sibling_order", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('group','holding','cash')", name=op.f("ck_target_nodes_kind_allowed")
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1 AND sibling_order >= 0 AND sibling_order < 256",
            name=op.f("ck_target_nodes_weight_order_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "parent_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
            name=op.f("fk_target_nodes_owner_id_target_nodes"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_nodes_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_nodes_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_nodes")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_nodes_owner_id")),
        sa.UniqueConstraint(
            "owner_id", "target_version_id", "id", name="uq_target_nodes_owner_version_identity"
        ),
        sa.UniqueConstraint(
            "target_version_id", "key", name=op.f("uq_target_nodes_target_version_id")
        ),
        sa.UniqueConstraint(
            "target_version_id",
            "parent_id",
            "sibling_order",
            name="uq_target_nodes_sibling_order",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "target_validation_results",
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("result_digest", sa.String(length=64), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("normalization_requested", sa.Boolean(), nullable=False),
        sa.Column("normalization_applied", sa.Boolean(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column(
            "effective_weight_rounding_residual", sa.Numeric(precision=38, scale=18), nullable=True
        ),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_revision > 0 AND result_revision = input_revision + 1",
            name=op.f("ck_target_validation_results_revision_order"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_validation_results_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_validation_results_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_validation_results")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_validation_results_owner_id")),
        sa.UniqueConstraint(
            "owner_id",
            "target_version_id",
            "id",
            name="uq_target_validations_owner_version_identity",
        ),
        sa.UniqueConstraint(
            "target_version_id",
            "result_revision",
            name=op.f("uq_target_validation_results_target_version_id"),
        ),
    )
    op.create_table(
        "target_collection_references",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("virtual_portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "snapshot_id"],
            ["collection_query_snapshots.owner_id", "collection_query_snapshots.id"],
            name=op.f("fk_target_collection_references_owner_id_collection_query_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id", "target_version_id"],
            [
                "target_versions.owner_id",
                "target_versions.virtual_portfolio_id",
                "target_versions.id",
            ],
            name=op.f("fk_target_collection_references_owner_id_target_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            name=op.f("fk_target_collection_references_owner_id_virtual_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_collection_references_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_collection_references")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_target_collection_references_owner_id")
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "virtual_portfolio_id",
            name=op.f("uq_target_collection_references_snapshot_id"),
        ),
    )
    op.create_table(
        "target_command_identities",
        sa.Column("broker_account_id", sa.Uuid(), nullable=True),
        sa.Column("command_kind", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("virtual_portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=True),
        sa.Column("validation_id", sa.Uuid(), nullable=True),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "command_kind IN ('create_portfolio','update_portfolio','archive_portfolio','create_version','replace_draft','validate_version','publish_version','archive_version')",
            name=op.f("ck_target_command_identities_command_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_target_command_identities_broker_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "validation_id"],
            [
                "target_validation_results.owner_id",
                "target_validation_results.target_version_id",
                "target_validation_results.id",
            ],
            name=op.f("fk_target_command_identities_owner_id_target_validation_results"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id", "target_version_id"],
            [
                "target_versions.owner_id",
                "target_versions.virtual_portfolio_id",
                "target_versions.id",
            ],
            name=op.f("fk_target_command_identities_owner_id_target_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            name=op.f("fk_target_command_identities_owner_id_virtual_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_command_identities_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_command_identities")),
        sa.UniqueConstraint(
            "owner_id",
            "broker_account_id",
            "command_kind",
            "idempotency_key",
            name="uq_target_commands_scope_key",
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_command_identities_owner_id")),
    )
    op.create_table(
        "target_constraints",
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("weight", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("line_count", sa.Integer(), nullable=True),
        sa.Column("coefficient", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind IN ('minimum_funded_amount','amount_increment','minimum_group_funding','maximum_group_funding') AND amount IS NOT NULL AND currency IS NOT NULL AND num_nonnulls(weight,enabled,line_count,coefficient)=0) OR (kind IN ('minimum_post_weight','maximum_post_weight') AND weight IS NOT NULL AND num_nonnulls(amount,currency,enabled,line_count,coefficient)=0) OR (kind='cash_reserve' AND num_nonnulls(enabled,line_count,coefficient)=0 AND ((amount IS NOT NULL AND currency IS NOT NULL) OR (amount IS NULL AND currency IS NULL AND weight IS NOT NULL))) OR (kind='eligible' AND enabled IS NOT NULL AND num_nonnulls(amount,currency,weight,line_count,coefficient)=0) OR (kind='maximum_funded_lines' AND line_count IS NOT NULL AND num_nonnulls(amount,currency,weight,enabled,coefficient)=0) OR (kind='priority' AND coefficient IS NOT NULL AND num_nonnulls(amount,currency,weight,enabled,line_count)=0)",
            name=op.f("ck_target_constraints_kind_fields"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR (amount >= 0 AND amount <> 'NaN'::numeric)",
            name=op.f("ck_target_constraints_amount_nonnegative"),
        ),
        sa.CheckConstraint(
            "kind <> 'amount_increment' OR amount > 0",
            name=op.f("ck_target_constraints_increment_positive"),
        ),
        sa.CheckConstraint(
            "kind IN ('minimum_funded_amount','amount_increment','minimum_post_weight','maximum_post_weight','minimum_group_funding','maximum_group_funding','cash_reserve','eligible','maximum_funded_lines','priority')",
            name=op.f("ck_target_constraints_kind_allowed"),
        ),
        sa.CheckConstraint(
            "coefficient IS NULL OR (coefficient >= 0.000001 AND coefficient <= 1000)",
            name=op.f("ck_target_constraints_coefficient_bounds"),
        ),
        sa.CheckConstraint(
            "line_count IS NULL OR (line_count >= 0 AND line_count <= 256)",
            name=op.f("ck_target_constraints_count_bounds"),
        ),
        sa.CheckConstraint(
            "weight IS NULL OR (weight >= 0 AND weight <= 1)",
            name=op.f("ck_target_constraints_weight_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "node_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
            name=op.f("fk_target_constraints_owner_id_target_nodes"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_constraints_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_constraints_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_constraints")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_constraints_owner_id")),
        sa.UniqueConstraint(
            "target_version_id", "key", name=op.f("uq_target_constraints_target_version_id")
        ),
    )
    op.create_table(
        "target_exclusions",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(node_id,instrument_id,listing_id) = 1",
            name=op.f("ck_target_exclusions_one_selector"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_target_exclusions_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_target_exclusions_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "node_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
            name=op.f("fk_target_exclusions_owner_id_target_nodes"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_exclusions_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_exclusions_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_exclusions")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_exclusions_owner_id")),
        sa.UniqueConstraint(
            "target_version_id", "key", name=op.f("uq_target_exclusions_target_version_id")
        ),
        sa.UniqueConstraint(
            "target_version_id",
            "node_id",
            "instrument_id",
            "listing_id",
            name="uq_target_exclusions_selector",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "target_holdings",
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("preferred_listing_id", sa.Uuid(), nullable=True),
        sa.Column("mapping_state", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mapping_state <> 'resolved' OR instrument_id IS NOT NULL",
            name=op.f("ck_target_holdings_resolved_instrument"),
        ),
        sa.CheckConstraint(
            "mapping_state IN ('resolved','unresolved','ambiguous')",
            name=op.f("ck_target_holdings_mapping_state_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_target_holdings_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_target_holdings_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "node_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
            name=op.f("fk_target_holdings_owner_id_target_nodes"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_holdings_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_holdings_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["preferred_listing_id"],
            ["listings.id"],
            name=op.f("fk_target_holdings_preferred_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_holdings")),
        sa.UniqueConstraint("node_id", name=op.f("uq_target_holdings_node_id")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_holdings_owner_id")),
        sa.UniqueConstraint(
            "owner_id", "target_version_id", "id", name="uq_target_holdings_owner_version_identity"
        ),
    )
    op.create_table(
        "target_normalization_adjustments",
        sa.Column("validation_id", sa.Uuid(), nullable=False),
        sa.Column("node_key", sa.String(length=80), nullable=False),
        sa.Column("parent_key", sa.String(length=80), nullable=True),
        sa.Column("original_weight", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("normalized_weight", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("original_sum", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("remainder_rank", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "validation_id"],
            ["target_validation_results.owner_id", "target_validation_results.id"],
            name=op.f("fk_target_normalization_adjustments_owner_id_target_validation_results"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_normalization_adjustments_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_normalization_adjustments")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_target_normalization_adjustments_owner_id")
        ),
        sa.UniqueConstraint(
            "validation_id",
            "node_key",
            name=op.f("uq_target_normalization_adjustments_validation_id"),
        ),
    )
    op.create_table(
        "target_validation_issues",
        sa.Column("validation_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("node_keys", sa.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("constraint_keys", sa.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "validation_id"],
            ["target_validation_results.owner_id", "target_validation_results.id"],
            name=op.f("fk_target_validation_issues_owner_id_target_validation_results"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_validation_issues_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_validation_issues")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_validation_issues_owner_id")),
        sa.UniqueConstraint(
            "validation_id", "ordinal", name=op.f("uq_target_validation_issues_validation_id")
        ),
    )
    op.create_table(
        "target_version_events",
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("validation_id", sa.Uuid(), nullable=True),
        sa.Column("previous_event_id", sa.Uuid(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('draft_created','draft_updated','validated','published','activated','superseded','archived')",
            name=op.f("ck_target_version_events_kind_allowed"),
        ),
        sa.CheckConstraint(
            "(sequence=1 AND previous_event_id IS NULL) OR (sequence>1 AND previous_event_id IS NOT NULL)",
            name=op.f("ck_target_version_events_predecessor_required"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "previous_event_id"],
            [
                "target_version_events.owner_id",
                "target_version_events.target_version_id",
                "target_version_events.id",
            ],
            name="fk_target_event_predecessor",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "validation_id"],
            [
                "target_validation_results.owner_id",
                "target_validation_results.target_version_id",
                "target_validation_results.id",
            ],
            name=op.f("fk_target_version_events_owner_id_target_validation_results"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_version_events_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_version_events_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_version_events")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_version_events_owner_id")),
        sa.UniqueConstraint(
            "owner_id", "target_version_id", "id", name="uq_target_events_owner_version_identity"
        ),
        sa.UniqueConstraint(
            "target_version_id", "sequence", name=op.f("uq_target_version_events_target_version_id")
        ),
    )
    op.create_index(
        "uq_target_version_activation",
        "target_version_events",
        ["target_version_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'activated'"),
    )
    op.create_table(
        "target_mapping_decisions",
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=False),
        sa.Column("identifier_kind", sa.String(length=30), nullable=True),
        sa.Column("identifier_value", sa.String(length=255), nullable=True),
        sa.Column("identifier_provider", sa.String(length=80), nullable=True),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind = 'owner'", name=op.f("ck_target_mapping_decisions_source_allowed")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_target_mapping_decisions_confidence_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id", "holding_id"],
            ["target_holdings.owner_id", "target_holdings.target_version_id", "target_holdings.id"],
            name=op.f("fk_target_mapping_decisions_owner_id_target_holdings"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_target_mapping_decisions_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_target_mapping_decisions_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_mapping_decisions")),
        sa.UniqueConstraint("holding_id", name=op.f("uq_target_mapping_decisions_holding_id")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_target_mapping_decisions_owner_id")),
    )

    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('activity','dividends','positions_market_value','positions_weight','positions_ticker') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes'))",
    )

    op.execute("""
CREATE FUNCTION target_portfolio_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'UPDATE' AND (NEW.owner_id,NEW.broker_account_id,NEW.reporting_currency)
   IS DISTINCT FROM (OLD.owner_id,OLD.broker_account_id,OLD.reporting_currency) THEN
   RAISE EXCEPTION 'target scope is immutable' USING ERRCODE='23514';
 END IF;
 IF NEW.broker_account_id IS NOT NULL AND NOT EXISTS (
   SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id
   WHERE a.id=NEW.broker_account_id AND c.owner_id=NEW.owner_id
 ) THEN RAISE EXCEPTION 'target account scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_portfolio_scope BEFORE INSERT OR UPDATE ON virtual_portfolios
 FOR EACH ROW EXECUTE FUNCTION target_portfolio_guard();

CREATE FUNCTION target_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
   IF OLD.published_at IS NOT NULL THEN
     RAISE EXCEPTION 'published target is immutable' USING ERRCODE='23514'; END IF;
   RETURN OLD;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM virtual_portfolios p WHERE p.id=NEW.virtual_portfolio_id
     AND p.owner_id=NEW.owner_id AND p.reporting_currency=NEW.reporting_currency) THEN
   RAISE EXCEPTION 'target portfolio scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_OP = 'UPDATE' THEN
   IF (NEW.owner_id,NEW.virtual_portfolio_id) IS DISTINCT FROM
      (OLD.owner_id,OLD.virtual_portfolio_id) THEN
     RAISE EXCEPTION 'target scope is immutable' USING ERRCODE='23514'; END IF;
   IF OLD.published_at IS NOT NULL AND
     (to_jsonb(NEW)-'state'-'revision'-'updated_at') IS DISTINCT FROM
     (to_jsonb(OLD)-'state'-'revision'-'updated_at') THEN
     RAISE EXCEPTION 'published target is immutable' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_version_content BEFORE INSERT OR UPDATE OR DELETE ON target_versions
 FOR EACH ROW EXECUTE FUNCTION target_version_guard();

CREATE FUNCTION target_content_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_uuid uuid; sealed timestamptz; lifecycle text;
BEGIN
 IF TG_OP = 'DELETE' THEN version_uuid=OLD.target_version_id;
 ELSE version_uuid=NEW.target_version_id; END IF;
 IF TG_OP = 'UPDATE' AND (NEW.owner_id,NEW.target_version_id) IS DISTINCT FROM
   (OLD.owner_id,OLD.target_version_id) THEN
   RAISE EXCEPTION 'target content scope is immutable' USING ERRCODE='23514'; END IF;
 SELECT published_at,state INTO sealed,lifecycle FROM target_versions
   WHERE id=version_uuid FOR UPDATE;
 IF sealed IS NOT NULL OR lifecycle='archived' THEN
   RAISE EXCEPTION 'published or archived target content is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION target_holding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM target_nodes n WHERE n.id=NEW.node_id AND n.kind='holding') THEN
   RAISE EXCEPTION 'target holding requires holding node' USING ERRCODE='23514'; END IF;
 IF NEW.listing_id IS NOT NULL AND NOT EXISTS
   (SELECT 1 FROM listings l WHERE l.id=NEW.listing_id AND l.instrument_id=NEW.instrument_id)
   THEN RAISE EXCEPTION 'listing instrument mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.preferred_listing_id IS NOT NULL AND (NOT EXISTS
   (SELECT 1 FROM listings l WHERE l.id=NEW.preferred_listing_id AND l.instrument_id=NEW.instrument_id)
   OR (NEW.listing_id IS NOT NULL AND NEW.listing_id<>NEW.preferred_listing_id))
   THEN RAISE EXCEPTION 'funding listing mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.mapping_state='resolved' AND EXISTS (SELECT 1 FROM target_holdings h
   WHERE h.target_version_id=NEW.target_version_id AND h.id<>NEW.id
     AND h.mapping_state='resolved' AND h.instrument_id=NEW.instrument_id
     AND (h.listing_id IS NULL OR NEW.listing_id IS NULL OR h.listing_id=NEW.listing_id))
   THEN RAISE EXCEPTION 'overlapping target selectors' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_holding_identity BEFORE INSERT OR UPDATE ON target_holdings
 FOR EACH ROW EXECUTE FUNCTION target_holding_guard();

CREATE FUNCTION target_constraint_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE currency_code text; node_kind text;
BEGIN
 SELECT reporting_currency INTO currency_code FROM target_versions
   WHERE id=NEW.target_version_id FOR UPDATE;
 IF NEW.currency IS NOT NULL AND NEW.currency <> currency_code THEN
   RAISE EXCEPTION 'target constraint currency mismatch' USING ERRCODE='23514'; END IF;
 SELECT kind INTO node_kind FROM target_nodes WHERE id=NEW.node_id;
 IF (NEW.kind IN ('cash_reserve','maximum_funded_lines') AND NEW.node_id IS NOT NULL)
   OR (NEW.kind IN ('minimum_funded_amount','amount_increment','eligible') AND
       node_kind IS DISTINCT FROM 'holding')
   OR (NEW.kind IN ('minimum_group_funding','maximum_group_funding') AND
       node_kind IS DISTINCT FROM 'group')
   OR (NEW.kind IN ('minimum_post_weight','maximum_post_weight','priority') AND
       (node_kind IS NULL OR node_kind NOT IN ('holding','group'))) THEN
   RAISE EXCEPTION 'target constraint scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_constraint_scope BEFORE INSERT OR UPDATE ON target_constraints
 FOR EACH ROW EXECUTE FUNCTION target_constraint_guard();

CREATE FUNCTION target_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE account_uuid uuid;
BEGIN
 SELECT broker_account_id INTO account_uuid FROM virtual_portfolios
   WHERE id=NEW.virtual_portfolio_id AND owner_id=NEW.owner_id;
 IF account_uuid IS DISTINCT FROM NEW.broker_account_id THEN
   RAISE EXCEPTION 'target command account mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_command_scope BEFORE INSERT ON target_command_identities
 FOR EACH ROW EXECUTE FUNCTION target_command_guard();

CREATE FUNCTION target_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.sequence>1 AND NOT EXISTS (SELECT 1 FROM target_version_events e
   WHERE e.id=NEW.previous_event_id AND e.target_version_id=NEW.target_version_id
     AND e.owner_id=NEW.owner_id AND e.sequence=NEW.sequence-1) THEN
   RAISE EXCEPTION 'target event predecessor mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.kind='published' AND NOT EXISTS (SELECT 1 FROM target_validation_results r
   JOIN target_versions v ON v.id=r.target_version_id
   WHERE r.id=NEW.validation_id AND r.valid AND r.target_version_id=NEW.target_version_id
     AND r.result_digest=v.content_digest AND r.result_revision+1=v.revision) THEN
   RAISE EXCEPTION 'target publication validation mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_event_sequence BEFORE INSERT ON target_version_events
 FOR EACH ROW EXECUTE FUNCTION target_event_guard();

CREATE FUNCTION target_append_only_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'target audit is append only' USING ERRCODE='23514'; END $$;

CREATE FUNCTION target_account_graph_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='broker_connections' THEN
   IF NEW.owner_id IS DISTINCT FROM OLD.owner_id AND EXISTS (
     SELECT 1 FROM broker_accounts a JOIN virtual_portfolios p
     ON p.broker_account_id=a.id WHERE a.connection_id=OLD.id)
   THEN RAISE EXCEPTION 'target account ownership is referenced' USING ERRCODE='23514'; END IF;
 ELSE
   IF NEW.connection_id IS DISTINCT FROM OLD.connection_id AND EXISTS (
     SELECT 1 FROM virtual_portfolios p WHERE p.broker_account_id=OLD.id)
   THEN RAISE EXCEPTION 'target account connection is referenced' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_connection_ownership BEFORE UPDATE OF owner_id ON broker_connections
 FOR EACH ROW EXECUTE FUNCTION target_account_graph_guard();
CREATE TRIGGER target_account_connection BEFORE UPDATE OF connection_id ON broker_accounts
 FOR EACH ROW EXECUTE FUNCTION target_account_graph_guard();
""")
    for table in (
        "target_nodes",
        "target_holdings",
        "target_mapping_decisions",
        "target_constraints",
        "target_exclusions",
    ):
        op.execute(
            f"CREATE TRIGGER target_content_sealed BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION target_content_guard()"
        )
    for table in (
        "target_validation_results",
        "target_validation_issues",
        "target_normalization_adjustments",
        "target_version_events",
        "virtual_portfolio_events",
        "target_command_identities",
    ):
        op.execute(
            f"CREATE TRIGGER target_audit_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION target_append_only_guard()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER target_connection_ownership ON broker_connections")
    op.execute("DROP TRIGGER target_account_connection ON broker_accounts")
    op.drop_table("target_mapping_decisions")
    op.drop_index(
        "uq_target_version_activation",
        table_name="target_version_events",
        postgresql_where=sa.text("kind = 'activated'"),
    )
    op.drop_table("target_version_events")
    op.drop_table("target_validation_issues")
    op.drop_table("target_normalization_adjustments")
    op.drop_table("target_holdings")
    op.drop_table("target_exclusions")
    op.drop_table("target_constraints")
    op.drop_table("target_command_identities")
    op.drop_table("target_collection_references")
    op.drop_constraint(
        "uq_collection_snapshots_owner_identity", "collection_query_snapshots", type_="unique"
    )
    # Only these short-lived query identities belong to this revision. Preserve
    # every Phase 1 traversal while restoring its resource and scope contracts.
    op.execute(
        "DELETE FROM collection_query_snapshots WHERE resource IN "
        "('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes')"
    )
    previous_checks = {
        "resource_allowed": (
            "resource IN ('activity','dividends','instruments','positions_market_value',"
            "'positions_weight','positions_ticker')"
        ),
        "resource_sort_match": (
            "(resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR "
            "(resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR "
            "(resource = 'instruments' AND sort_specification = "
            "'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR "
            "(resource = 'positions_market_value' AND "
            "sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR "
            "(resource = 'positions_weight' AND "
            "sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR "
            "(resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc')"
        ),
        "account_scope_match": (
            "((resource IN ('activity','dividends','positions_market_value',"
            "'positions_weight','positions_ticker') AND broker_account_id IS NOT NULL) OR "
            "(resource = 'instruments' AND broker_account_id IS NULL))"
        ),
    }
    for suffix, expression in previous_checks.items():
        name = op.f(f"ck_collection_query_snapshots_{suffix}")
        op.drop_constraint(name, "collection_query_snapshots", type_="check")
        op.create_check_constraint(name, "collection_query_snapshots", expression)
    op.drop_table("target_validation_results")
    op.drop_table("target_nodes")
    op.drop_table("virtual_portfolio_events")
    op.drop_index(
        "uq_target_versions_one_active",
        table_name="target_versions",
        postgresql_where=sa.text("state = 'active'"),
    )
    op.drop_index("ix_target_versions_due", table_name="target_versions")
    op.drop_table("target_versions")
    op.drop_index("ix_virtual_portfolios_owner_updated", table_name="virtual_portfolios")
    op.drop_table("virtual_portfolios")

    for name in (
        "target_portfolio_guard",
        "target_version_guard",
        "target_content_guard",
        "target_holding_guard",
        "target_constraint_guard",
        "target_command_guard",
        "target_event_guard",
        "target_append_only_guard",
        "target_account_graph_guard",
    ):
        op.execute(f"DROP FUNCTION {name}()")
