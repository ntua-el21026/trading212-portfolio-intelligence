"""Closed conservative physical work profiles for the Phase2 copy participants."""

from .projection_retention_costs import ProjectionMutationCost

# Includes target, immutable/planning guard, up to two counter writers, exact
# source/report/projection/premium parent barriers and fixed FK probes. No child
# aggregate or graph traversal is included:0028 replaces those with point facts.
PHASE2_PAYLOAD_MUTATION_ROWS = 64
PHASE2_COLLECTION_MUTATION_ROWS = 48
PHASE2_MEMBERSHIP_MUTATION_ROWS = 16
PHASE2_MARKER_ROWS = 32
SOURCE_MARKER_ROWS = 32  # includes acquisition witness12 and protected owner epoch3
SOURCE_PROGRESS_ROWS = 16
SOURCE_COMPLETION_ROWS = 48  # expiry insertion + work completion, epoch3 included
ENRICHMENT_MARKER_ROWS = 16  # header/work/FK and protected owner epoch3
ENRICHMENT_PROGRESS_ROWS = 12
ENRICHMENT_COMPLETION_ROWS = 40
ACQUISITION_SOURCE_PERMISSION_MAX_ROWS = 12

_XRAY = frozenset(
    (
        "xray_input_snapshots",
        "xray_input_positions",
        "xray_input_cash",
        "xray_input_dependencies",
        "xray_input_source_selections",
        "xray_run_sources",
        "xray_runs",
        "xray_dimensions",
        "xray_warnings",
        "xray_residuals",
        "xray_classification_decisions",
        "xray_direct_positions",
        "xray_held_funds",
        "xray_exposures",
        "xray_exposure_paths",
        "xray_path_edges",
        "xray_fund_compositions",
        "xray_fund_entities",
    )
)
_HISTORICAL = frozenset(
    (
        "historical_input_snapshots",
        "analytics_runs",
        "performance_points",
        "performance_period_returns",
        "income_components",
        "attribution_components",
        "historical_cash_flow_points",
        "historical_conversions",
        "historical_composite_benchmarks",
        "benchmark_composite_points",
    )
)
_SOURCES = frozenset(
    (
        "price_observations",
        "fx_observations",
        "corporate_action_observations",
        "benchmark_observations",
        "source_coverage_gaps",
        "constituent_holdings",
        "constituent_snapshots",
        "entity_evidence_references",
        "instrument_entity_relationships",
        "share_classes",
        "entity_evidence_versions",
        "classification_snapshot_assignments",
        "classification_assignments",
        "classification_snapshot_instruments",
        "classification_snapshots",
        "fund_source_mappings",
        "fund_definitions",
    )
)
_COLLECTIONS = frozenset(
    (
        "etf_overlap_entities",
        "etf_overlap_pairs",
        "xray_collection_bindings",
        "collection_query_snapshot_members",
        "collection_query_snapshots",
    )
)


def phase2_mutation_cost(table: str, *, delete_rows: bool) -> ProjectionMutationCost | None:
    if table in _XRAY | _HISTORICAL | _SOURCES:
        return ProjectionMutationCost(1, PHASE2_PAYLOAD_MUTATION_ROWS, 2)
    if table in _COLLECTIONS:
        return ProjectionMutationCost(1, PHASE2_COLLECTION_MUTATION_ROWS, 2)
    return None
