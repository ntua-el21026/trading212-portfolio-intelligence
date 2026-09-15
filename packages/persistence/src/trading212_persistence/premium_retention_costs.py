"""Fixed closed SQL work for risk/scenario cleanup; metadata reads are separate.

A payload mutation reserves target1, immutable/report checks8, counter4,
capacity2, reverse FK probes12 and trigger/constraint headroom5. Source payloads
reserve target1, source/header/marker/membership checks8, flag update6 and FK7.
Each size/remaining query also reserves one indexed empty/tombstone probe.
These are conservative per-row maxima after migration0026; no graph scan is
included or permitted. Original read/publication validators are outside cleanup.
"""

from .projection_retention_costs import ProjectionMutationCost

PREMIUM_MARKER_ROWS = 24
PREMIUM_JOB_ROWS = 40
PREMIUM_COMPLETE_ROWS = 32
PREMIUM_PARENT_ROWS = 12
SCENARIO_SOURCE_MARKER_ROWS = 16  # Includes the protected owner epoch upsert3.
SCENARIO_SOURCE_COMPLETE_ROWS = 24
SCENARIO_LINK_ROWS = 16
ENRICHMENT_MARKER_EPOCH_ROWS = 3

_RUN_PAYLOADS = frozenset(
    (
        "risk_run_assets",
        "risk_results",
        "risk_series",
        "risk_intervals",
        "risk_matrix_cells",
        "risk_metrics",
        "risk_components",
        "scenario_run_payloads",
        "scenario_results",
        "scenario_components",
        "scenario_applied_sensitivities",
    )
)
_SOURCE_PAYLOADS = frozenset(
    (
        "scenario_sensitivity_version_payloads",
        "scenario_sensitivity_observation_payloads",
        "scenario_sensitivity_evidence_payloads",
    )
)


def premium_mutation_cost(table: str, *, delete_rows: bool) -> ProjectionMutationCost | None:
    if table in _RUN_PAYLOADS:
        return ProjectionMutationCost(scope_rows=1, mutation_rows=32, payload_inspections=2)
    if table in _SOURCE_PAYLOADS:
        return ProjectionMutationCost(scope_rows=1, mutation_rows=24, payload_inspections=2)
    return None
