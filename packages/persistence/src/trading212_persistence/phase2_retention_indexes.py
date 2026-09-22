"""Exact pending predicates; called once by model registration."""

from sqlalchemy import Index, text

from . import historical_models as hm
from . import source_models as sm
from . import xray_catalog_models as cm
from . import xray_run_models as xm
from .phase2_retention_models import (
    HistoricalCompositeErasureModel,
    HistoricalRetainedSourceModel,
    XrayRetainedSourceModel,
)
from .xray_lifecycle_models import EnrichmentRetentionWorkModel


def register_phase2_indexes() -> None:
    Index(
        "ix_p2_performance_points_pending",
        hm.PerformancePointModel.run_id,
        hm.PerformancePointModel.id,
        postgresql_where=text(
            "(canonical_row <> '\\x'::bytea OR portfolio_value IS NOT"
            " NULL OR cash_value IS NOT NULL OR wealth IS NOT NULL O"
            "R period_return IS NOT NULL)"
        ),
    )
    Index(
        "ix_p2_performance_period_returns_pending",
        hm.PerformancePeriodModel.run_id,
        hm.PerformancePeriodModel.id,
        postgresql_where=text("(canonical_row <> '\\x'::bytea OR period_return IS NOT NULL)"),
    )
    Index(
        "ix_p2_income_components_pending",
        hm.HistoricalIncomeRowModel.run_id,
        hm.HistoricalIncomeRowModel.id,
        postgresql_where=text(
            "(canonical_row <> '\\x'::bytea OR net IS NOT NULL OR gro"
            "ss IS NOT NULL OR withholding IS NOT NULL)"
        ),
    )
    Index(
        "ix_p2_attribution_components_pending",
        hm.HistoricalAttributionRowModel.run_id,
        hm.HistoricalAttributionRowModel.id,
        postgresql_where=text(
            "(canonical_row <> '\\x'::bytea OR gain IS NOT NULL OR return_contribution IS NOT NULL)"
        ),
    )
    Index(
        "ix_p2_historical_cash_flow_points_pending",
        hm.HistoricalCashFlowRowModel.run_id,
        hm.HistoricalCashFlowRowModel.id,
        postgresql_where=text("(canonical_row <> '\\x'::bytea OR amount IS NOT NULL)"),
    )
    Index(
        "ix_p2_historical_conversions_pending",
        hm.HistoricalConversionModel.run_id,
        hm.HistoricalConversionModel.id,
        postgresql_where=text("(rate IS NOT NULL)"),
    )
    Index(
        "ix_p2_historical_composite_benchmarks_pending",
        hm.HistoricalCompositeModel.run_id,
        hm.HistoricalCompositeModel.id,
        postgresql_where=text("(canonical_composite <> '\\x'::bytea)"),
    )
    Index(
        "ix_p2_benchmark_composite_points_pending",
        hm.BenchmarkCompositePointModel.snapshot_id,
        hm.BenchmarkCompositePointModel.id,
        postgresql_where=text(
            "(canonical_point <> '\\x'::bytea OR wealth IS NOT NULL OR interval_return IS NOT NULL)"
        ),
    )
    Index(
        "ix_p2_entity_evidence_references_pending",
        cm.EntityEvidenceReferenceModel.evidence_version_id,
        cm.EntityEvidenceReferenceModel.id,
        postgresql_where=text(
            "(display_name IS NOT NULL OR lei IS NOT NULL OR confidence IS NOT NULL)"
        ),
    )
    Index(
        "ix_p2_instrument_entity_relationships_pending",
        cm.InstrumentEntityRelationshipModel.evidence_version_id,
        cm.InstrumentEntityRelationshipModel.id,
        postgresql_where=text("(units_per_receipt IS NOT NULL OR confidence IS NOT NULL)"),
    )
    Index(
        "ix_p2_share_classes_pending",
        cm.ShareClassModel.evidence_version_id,
        cm.ShareClassModel.id,
        postgresql_where=text("(class_key IS NOT NULL OR confidence IS NOT NULL)"),
    )
    Index(
        "ix_p2_work_price_snapshot",
        sm.SourceRetentionWorkModel.id,
        postgresql_where=text("price_snapshot_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_fx_snapshot",
        sm.SourceRetentionWorkModel.id,
        postgresql_where=text("fx_snapshot_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_benchmark_snapshot",
        sm.SourceRetentionWorkModel.id,
        postgresql_where=text("benchmark_snapshot_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_corporate_action_snapshot",
        sm.SourceRetentionWorkModel.id,
        postgresql_where=text("corporate_action_snapshot_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_constituent_snapshot",
        sm.SourceRetentionWorkModel.id,
        postgresql_where=text("constituent_snapshot_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_entity_evidence_version",
        EnrichmentRetentionWorkModel.id,
        postgresql_where=text("entity_evidence_version_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_classification_snapshot",
        EnrichmentRetentionWorkModel.id,
        postgresql_where=text("classification_snapshot_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_fund_definition",
        EnrichmentRetentionWorkModel.id,
        postgresql_where=text("fund_definition_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_work_fund_mapping",
        EnrichmentRetentionWorkModel.id,
        postgresql_where=text("fund_mapping_id IS NOT NULL AND completed_at IS NULL"),
    )
    Index(
        "ix_p2_history_marker_leaf",
        hm.HistoricalRetentionEventModel.owner_id,
        hm.HistoricalRetentionEventModel.source_dependency_id,
    )
    Index(
        "ix_p2_erasure_event",
        HistoricalCompositeErasureModel.owner_id,
        HistoricalCompositeErasureModel.event_id,
    )
    Index(
        "ix_p2_erasure_run",
        HistoricalCompositeErasureModel.owner_id,
        HistoricalCompositeErasureModel.run_id,
    )
    Index(
        "ix_p2_history_leaf",
        HistoricalRetainedSourceModel.owner_id,
        HistoricalRetainedSourceModel.leaf_id,
    )
    Index(
        "ix_p2_history_root",
        HistoricalRetainedSourceModel.owner_id,
        HistoricalRetainedSourceModel.dependency_id,
    )
    Index(
        "ix_p2_xray_dependency",
        XrayRetainedSourceModel.owner_id,
        XrayRetainedSourceModel.dependency_id,
    )
    Index("ix_p2_edge_holding", xm.XrayPathEdgeModel.owner_id, xm.XrayPathEdgeModel.holding_id)
    Index(
        "ix_p2_assignment_reference",
        cm.ClassificationSnapshotAssignmentModel.owner_id,
        cm.ClassificationSnapshotAssignmentModel.assignment_id,
    )
