"""Closed fixed tables for complete saved projection and goal proof."""

from .errors import fail_validation
from .reports import ReportRow
from .reports import ReportTableKey as T

PROJECTION_POINT_MONEY = (
    "nominal",
    "real",
    "contributions",
    "withdrawals_requested",
    "withdrawals_funded",
    "unpaid_withdrawals",
    "investment_effect",
    "fees",
    "tax_drag",
    "wealth_residual",
    "allocation_residual",
    "withdrawal_residual",
)
PROJECTION_TABLE_COLUMNS: dict[T, tuple[tuple[str, str], ...]] = {
    T.PROJECTION_BASIS_V1: (
        ("root_id", "id"),
        ("run_id", "id"),
        ("input_id", "id"),
        ("result_id", "id"),
        ("capture_digest", "id"),
        ("numerical_input_digest", "id"),
        ("result_digest", "id"),
        ("owner_id", "id"),
        ("account_id", "id"),
        ("reporting_currency", "enum"),
        ("created_at", "utc"),
        ("calculated_at", "utc"),
        ("completed_at", "utc"),
        ("expires_at", "utc"),
        ("initial_kind", "enum"),
        ("initial_value", "M"),
        ("observed_snapshot_id", "id?"),
        ("observed_snapshot_digest", "id?"),
        ("observed_valuation_at", "utc?"),
        ("original_source_cutoff_at", "utc?"),
        ("anchor_date", "date"),
        ("terminal_date", "date"),
        ("seed", "int"),
        ("months", "int"),
        ("paths", "int"),
        ("retained_point_count", "int"),
        ("variant_count", "int"),
        ("method", "id"),
        ("method_version", "id"),
        ("numeric_profile", "id"),
        ("sampler", "id"),
        ("calendar_rule", "id"),
        ("capture_schema_version", "id"),
        ("report_context_snapshot_id", "id"),
        ("report_context_snapshot_digest", "id"),
        ("report_context_valuation_at", "utc"),
        ("report_context_source_cutoff_at", "utc"),
    ),
    T.PROJECTION_DEFINITIONS_V1: (
        ("kind", "enum"),
        ("aggregate_id", "id"),
        ("version_id", "id"),
        ("version_number", "int"),
        ("predecessor_id", "id?"),
        ("name", "text"),
        ("description", "text"),
        ("content_digest", "id"),
        ("created_at", "utc"),
    ),
    T.PROJECTION_ASSUMPTIONS_V1: (
        ("annual_inflation", "R"),
        ("annual_fee", "R"),
        ("annual_tax_drag", "R?"),
        ("rebalance", "enum"),
        ("reporting_currency", "enum"),
        ("asset_count", "int"),
        ("calibration_count", "int"),
    ),
    T.PROJECTION_ASSETS_V1: (
        ("ordinal", "int"),
        ("key", "id"),
        ("annual_mean_log_return", "R"),
        ("annual_volatility", "R"),
        ("weight", "R"),
        ("initial_ordinal", "int"),
        ("initial_weight", "R"),
    ),
    T.PROJECTION_CORRELATIONS_V1: (
        ("row_index", "int"),
        ("column_index", "int"),
        ("row_key", "id"),
        ("column_key", "id"),
        ("coefficient", "R"),
    ),
    T.PROJECTION_CALENDAR_V1: (("month", "int"), ("on", "date"), ("point_index", "int?")),
    T.PROJECTION_SCHEDULE_V1: (
        ("scope", "enum"),
        ("kind", "enum"),
        ("ordinal", "int"),
        ("key", "id?"),
        ("on", "date?"),
        ("month", "int?"),
        ("value", "M?"),
        ("annual_growth", "R?"),
    ),
    T.PROJECTION_SENSITIVITY_V1: (("contribution_delta", "M"), ("annual_mean_log_delta", "R")),
    T.PROJECTION_VARIANTS_V1: (
        ("variant", "enum"),
        ("path_count", "int"),
        ("distribution_count", "int"),
        ("goal_present", "bool"),
    ),
    T.PROJECTION_PATHS_V1: (
        ("variant", "enum"),
        ("path_index", "int"),
        ("reporting_currency", "enum"),
        ("first_unpaid_month", "int?"),
    ),
    T.PROJECTION_POINTS_V1: (
        ("variant", "enum"),
        ("path_index", "int"),
        ("point_index", "int"),
        ("month", "int"),
        ("on", "date"),
        ("nominal", "M"),
        ("real", "M"),
        ("contributions", "M"),
        ("withdrawals_requested", "M"),
        ("withdrawals_funded", "M"),
        ("unpaid_withdrawals", "M"),
        ("investment_effect", "M"),
        ("fees", "M"),
        ("tax_drag", "M"),
        ("wealth_residual", "M"),
        ("allocation_residual", "M"),
        ("withdrawal_residual", "M"),
        ("funding_failed", "bool"),
        ("unpaid_positive_below_quantum", "bool"),
    ),
    T.PROJECTION_POINT_ASSETS_V1: (
        ("variant", "enum"),
        ("path_index", "int"),
        ("point_index", "int"),
        ("asset_index", "int"),
        ("key", "id"),
        ("value", "M"),
    ),
    T.PROJECTION_DISTRIBUTIONS_V1: (
        ("variant", "enum"),
        ("month", "int"),
        ("on", "date"),
        ("nominal_mean", "M"),
        ("real_mean", "M"),
        ("funding_failed_paths", "int"),
    ),
    T.PROJECTION_QUANTILES_V1: (
        ("variant", "enum"),
        ("kind", "enum"),
        ("month", "int?"),
        ("ordinal", "int"),
        ("probability", "R"),
        ("value", "M"),
    ),
    T.PROJECTION_HISTOGRAMS_V1: (
        ("variant", "enum"),
        ("basis", "enum"),
        ("observed_minimum", "M"),
        ("observed_maximum", "M"),
        ("boundary_rule", "enum"),
    ),
    T.PROJECTION_HISTOGRAM_BINS_V1: (
        ("variant", "enum"),
        ("basis", "enum"),
        ("ordinal", "int"),
        ("lower", "M"),
        ("upper", "M"),
        ("upper_inclusive", "bool"),
        ("count", "int"),
    ),
    T.PROJECTION_GOAL_STATE_V1: (
        ("available", "bool"),
        ("reason", "enum?"),
        ("goal_version_id", "id?"),
        ("automatic_goal_acceptance", "bool"),
    ),
    T.PROJECTION_GOAL_DEFINITION_V1: (
        ("assumption_version_id", "id"),
        ("target", "M"),
        ("target_date", "date"),
        ("months", "int"),
        ("basis", "enum"),
        ("probability_objective", "R"),
    ),
    T.PROJECTION_GOAL_RESULTS_V1: (
        ("variant", "enum"),
        ("goal_version_id", "id"),
        ("basis", "enum"),
        ("target", "M"),
        ("paths", "int"),
        ("successes", "int"),
        ("probability", "R"),
        ("interval_low", "R"),
        ("interval_high", "R"),
        ("probability_objective", "R"),
        ("objective_met", "bool"),
        ("mean_shortfall", "M"),
        ("funding_failed_paths", "int"),
        ("method", "id"),
        ("interval_method", "id"),
    ),
    T.PROJECTION_MEMBERS_V1: (
        ("kind", "enum"),
        ("ordinal", "int"),
        ("value", "int?"),
        ("subject_id", "id?"),
        ("content_digest", "id?"),
    ),
    T.PROJECTION_SOURCE_HEADERS_V1: (
        ("ordinal", "int"),
        ("kind", "enum"),
        ("role", "enum"),
        ("subject_id", "id"),
        ("content_digest", "id"),
        ("proof_digest", "id"),
        ("proof_bytes", "int"),
        ("original_created_at", "utc"),
        ("physical_expires_at", "utc?"),
        ("authorized_copy_expires_at", "utc"),
        ("source_cutoff_at", "utc?"),
        ("first_observed_at", "utc?"),
        ("quality", "enum"),
        ("historical_document_digest", "id?"),
    ),
    T.PROJECTION_SOURCE_NODES_V1: (
        ("source_ordinal", "int"),
        ("part", "enum"),
        ("node", "int"),
        ("kind", "enum"),
        ("child_count", "int"),
    ),
    T.PROJECTION_SOURCE_MEMBERS_V1: (
        ("source_ordinal", "int"),
        ("part", "enum"),
        ("parent_node", "int"),
        ("ordinal", "int"),
        ("member_key", "text?"),
        ("child_node", "int"),
    ),
    T.PROJECTION_SOURCE_SCALARS_V1: (
        ("source_ordinal", "int"),
        ("part", "enum"),
        ("node", "int"),
        ("kind", "enum"),
        ("text", "text?"),
        ("integer", "int?"),
        ("boolean", "bool?"),
    ),
}
PROJECTION_PROOF_TABLES = (
    T.PROJECTION_DEFINITIONS_V1,
    T.PROJECTION_MEMBERS_V1,
    T.PROJECTION_SOURCE_HEADERS_V1,
    T.PROJECTION_SOURCE_NODES_V1,
    T.PROJECTION_SOURCE_MEMBERS_V1,
    T.PROJECTION_SOURCE_SCALARS_V1,
)
GOAL_REPORT_TABLES = (
    T.PROJECTION_GOAL_STATE_V1,
    T.PROJECTION_GOAL_DEFINITION_V1,
    T.PROJECTION_GOAL_RESULTS_V1,
)
PROJECTION_REPORT_TABLES = tuple(
    table
    for table in PROJECTION_TABLE_COLUMNS
    if table not in PROJECTION_PROOF_TABLES and table not in GOAL_REPORT_TABLES
)
PROJECTION_SOURCE_PARTS = {
    "portfolio_snapshot": frozenset(
        {"header", "metadata", "licenses", "snapshot", "calculation", "positions", "cash"}
    ),
    "historical_input": frozenset({"header", "metadata", "licenses", "canonical_input"}),
    "price_total_return": frozenset(
        {
            "header",
            "metadata",
            "licenses",
            "snapshot",
            "original_observations",
            "original_gaps",
            "series",
            "mapping",
            "mapping_candidates",
            "calendar",
            "calendar_sessions",
        }
    ),
    "benchmark_total_return": frozenset(
        {
            "header",
            "metadata",
            "licenses",
            "snapshot",
            "original_observations",
            "original_gaps",
            "series",
            "mapping",
            "mapping_candidates",
            "calendar",
            "calendar_sessions",
        }
    ),
}


def validate_projection_report_row(table: T, row: ReportRow) -> None:
    if table not in PROJECTION_TABLE_COLUMNS:
        return
    values = {
        key: cell.value
        for (key, _), cell in zip(PROJECTION_TABLE_COLUMNS[table], row.cells, strict=True)
    }
    if "variant" in values and values["variant"] not in {
        "baseline",
        "contribution_delta",
        "mean_log_delta",
    }:
        fail_validation("Unknown saved projection variant.", field="variant")
    if table in {
        T.PROJECTION_SOURCE_NODES_V1,
        T.PROJECTION_SOURCE_MEMBERS_V1,
        T.PROJECTION_SOURCE_SCALARS_V1,
    } and values["part"] not in set().union(*PROJECTION_SOURCE_PARTS.values()):
        fail_validation("Unknown original source part.", field="part")
    if table is T.PROJECTION_SOURCE_SCALARS_V1:
        kind = values["kind"]
        expected = {"string": "text", "integer": "integer", "boolean": "boolean", "null": None}
        if (
            not isinstance(kind, str)
            or kind not in expected
            or any(
                (values[field] is not None) != (field == expected[kind])
                for field in ("text", "integer", "boolean")
            )
        ):
            fail_validation("Source scalar kind/value differs.", field="source")
    if table is T.PROJECTION_SOURCE_NODES_V1 and values["kind"] not in {
        "object",
        "array",
        "string",
        "integer",
        "boolean",
        "null",
    }:
        fail_validation("Unknown source node kind.", field="source")
    if table is T.PROJECTION_MEMBERS_V1 and values["kind"] not in {"zero_pivot", "calibration"}:
        fail_validation("Unknown projection membership.", field="kind")
    if table is T.PROJECTION_GOAL_STATE_V1 and (
        values["automatic_goal_acceptance"] is not False
        or (values["available"] is True) != (values["goal_version_id"] is not None)
        or values["reason"] != (None if values["available"] else "no_goal_pinned")
    ):
        fail_validation("Goal absence must remain explicit.", field="goal")

    closed = {
        T.PROJECTION_SCHEDULE_V1: {
            "scope": {"run", "goal"},
            "kind": {"base", "pause", "lump_sum", "withdrawal"},
        },
        T.PROJECTION_DEFINITIONS_V1: {"kind": {"assumption", "goal"}},
        T.PROJECTION_QUANTILES_V1: {"kind": {"nominal", "real", "goal_shortfall"}},
        T.PROJECTION_HISTOGRAMS_V1: {
            "basis": {"nominal", "real"},
            "boundary_rule": {"q18_enclosing_ceiling_v1"},
        },
        T.PROJECTION_HISTOGRAM_BINS_V1: {"basis": {"nominal", "real"}},
        T.PROJECTION_GOAL_RESULTS_V1: {
            "basis": {"nominal", "real"},
            "method": {"goal_analysis_v1"},
            "interval_method": {"wilson_95_v1"},
        },
        T.PROJECTION_GOAL_DEFINITION_V1: {"basis": {"nominal", "real"}},
        T.PROJECTION_BASIS_V1: {
            "initial_kind": {"modeled_value", "observed_snapshot"},
            "method": {"projection_v1"},
            "method_version": {"1.0.0"},
            "numeric_profile": {"premium_decimal96_q18_v1"},
            "sampler": {"sha256_counter_polar_v1"},
            "calendar_rule": {"calendar_anniversary_clamped_v1"},
            "capture_schema_version": {"1.0.0"},
        },
    }
    if any(values[key] not in allowed for key, allowed in closed.get(table, {}).items()):
        fail_validation("Unknown fixed projection table label.", field="row")
    if table is T.PROJECTION_SOURCE_HEADERS_V1 and (
        values["kind"] not in PROJECTION_SOURCE_PARTS
        or values["role"]
        != ("initial_snapshot" if values["kind"] == "portfolio_snapshot" else "calibration")
    ):
        fail_validation("Original source kind/role differs.", field="source")
