"""Temporary intelligence-quality selection and visible identity bindings.

Revision ID: 20260911_0016
Revises: 20260910_0015

No mutable application/model imports. No licensed bytes are stored here.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260911_0016"
down_revision = "20260910_0015"
branch_labels = None
depends_on = None

_PREVIOUS = {
    "resource_allowed": "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "(resource IN ('historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc')",
    "account_scope_match": "((resource IN ('alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
}


def _constraints(*, quality: bool) -> None:
    for name, previous in _PREVIOUS.items():
        value = previous
        if quality:
            if name == "resource_sort_match":
                value = "(" + previous + ") OR (resource = 'intelligence_quality_sources' AND sort_specification = 'ordinal_asc')"
            elif name == "account_scope_match":
                value = "(" + previous + ") OR (resource = 'intelligence_quality_sources' AND broker_account_id IS NOT NULL)"
            else:
                value = previous.replace("resource IN (", "resource IN ('intelligence_quality_sources',", 1)
        constraint = op.f("ck_collection_query_snapshots_" + name)
        op.drop_constraint(constraint, "collection_query_snapshots", type_="check")
        op.create_check_constraint(constraint, "collection_query_snapshots", value)


def upgrade() -> None:
    _constraints(quality=True)
    op.create_table(
        "intelligence_quality_collection_bindings",
        sa.Column("collection_id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("analytics_kind", sa.String(30), nullable=False),
        sa.Column("valuation_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("analytics_run_id", sa.Uuid(), nullable=True),
        sa.Column("historical_input_id", sa.Uuid(), nullable=True),
        sa.Column("xray_input_id", sa.Uuid(), nullable=True),
        sa.Column("selection_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["valuation_snapshot_id"], ["portfolio_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id", "collection_id"], ["collection_query_snapshots.owner_id", "collection_query_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id", "analytics_run_id"], ["analytics_runs.owner_id", "analytics_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id", "historical_input_id"], ["historical_input_snapshots.owner_id", "historical_input_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id", "xray_input_id"], ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"], ondelete="CASCADE"),
        sa.CheckConstraint("analytics_kind IN ('valuation','actual_vs_target','drift','performance','benchmark','income','attribution','cash_flow','xray')", name="kind_allowed"),
        sa.CheckConstraint("(analytics_kind='valuation' AND valuation_snapshot_id IS NOT NULL AND analytics_run_id IS NULL) OR (analytics_kind<>'valuation' AND valuation_snapshot_id IS NULL AND analytics_run_id IS NOT NULL)", name="selected_parent"),
        sa.CheckConstraint("(analytics_kind IN ('performance','benchmark','income','attribution','cash_flow') AND historical_input_id IS NOT NULL AND xray_input_id IS NULL) OR (analytics_kind='xray' AND historical_input_id IS NULL AND xray_input_id IS NOT NULL) OR (analytics_kind IN ('valuation','actual_vs_target','drift') AND historical_input_id IS NULL AND xray_input_id IS NULL)", name="input_parent"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        sa.UniqueConstraint("owner_id", "collection_id"),
    )
    op.create_table(
        "intelligence_quality_collection_sources",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id", "collection_id"], ["intelligence_quality_collection_bindings.owner_id", "intelligence_quality_collection_bindings.collection_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("collection_id", "ordinal"),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 8192", name="ordinal_bound"),
        sa.CheckConstraint("source_kind IN ('portfolio_snapshot','snapshot_position','snapshot_cash','calculation_run','ingestion_run','broker_source_record','broker_source_occurrence','reconciliation_run','price_snapshot','fx_snapshot','provider_benchmark_snapshot','corporate_action_snapshot','instrument_mapping','calendar_version','provider_license_version','benchmark_version','target_version','classification_evidence','historical_evidence','activity_revision_evidence','entity_evidence_version','classification_snapshot','fund_definition','fund_mapping','constituent_snapshot','xray_policy')", name="source_kind_allowed"),
    )


def downgrade() -> None:
    # Only this resource owns these short-lived identities; financial sources are untouched.
    op.execute(sa.text("DELETE FROM collection_query_snapshots WHERE resource = 'intelligence_quality_sources'"))
    op.drop_table("intelligence_quality_collection_sources")
    op.drop_table("intelligence_quality_collection_bindings")
    _constraints(quality=False)
