"""Conservative fixed SQL row work, charged before physical projection cleanup.

The profile includes the target mutation, counter, immutability and pending-report
checks. It is not permission to select any table or execute a generic SQL command.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectionMutationCost:
    scope_rows: int = 0
    mutation_rows: int = 1
    payload_inspections: int = 1


_DIRECT = frozenset(
    (
        "projection_inputs",
        "projection_run_allocations",
        "projection_calendar_boundaries",
        "projection_run_pauses",
        "projection_run_schedule_entries",
        "projection_source_proofs",
        "projection_chunks",
        "projection_paths",
        "projection_points",
        "projection_point_assets",
        "projection_results",
    )
)
_RESULT = frozenset(
    (
        "projection_zero_pivots",
        "projection_distributions",
        "projection_histograms",
        "projection_goal_analyses",
    )
)
_NESTED = frozenset(
    (
        "projection_distribution_quantiles",
        "projection_histogram_bins",
        "projection_goal_shortfall_quantiles",
    )
)
_PARENT_PAYLOADS = frozenset(
    (
        "price_observations",
        "fx_observations",
        "corporate_action_observations",
        "benchmark_observations",
        "source_coverage_gaps",
        "price_snapshots",
        "fx_snapshots",
        "corporate_action_snapshots",
        "benchmark_snapshots",
        "historical_input_snapshots",
    )
)
# Worst fixed participants per projection mutation: target1, counter6,
# immutable guard4, pending-report guard4, deferred capacity2, FK probes8.
# Empty FK probes are deliberately charged as one each; duplicates are not refunded.
# Source-membership deletion uses target1 + guard3 + counter4 + FK probes3.
# Per-run allowance covers two premium root updates, one terminal job/outbox/
# attempt/capacity transition, retention marker insert/completion and their fixed
# integrity/deferred-counter probes. Ordinary explicit reads remain charged too.
PROJECTION_RUN_MUTATION_RESERVE = 64
PROJECTION_MUTATION_MAX_ROWS = 25
PROJECTION_MEMBERSHIP_MUTATION_MAX_ROWS = 11


def projection_mutation_cost(table: str, *, delete_rows: bool) -> ProjectionMutationCost:
    if table == "projection_retained_source_memberships":
        if not delete_rows:
            raise ValueError("Projection retained memberships can only be deleted.")
        return ProjectionMutationCost(0, PROJECTION_MEMBERSHIP_MUTATION_MAX_ROWS, 2)
    if table in _DIRECT | _RESULT | _NESTED:
        return ProjectionMutationCost(
            1 if table in _RESULT else 0,
            PROJECTION_MUTATION_MAX_ROWS,
            2,
        )
    if table in _PARENT_PAYLOADS:
        # The new projection parent blocker performs one exact indexed membership
        # probe per mutation. Existing family-specific work is charged by its owner.
        return ProjectionMutationCost(0, 2, 1)
    return ProjectionMutationCost()
