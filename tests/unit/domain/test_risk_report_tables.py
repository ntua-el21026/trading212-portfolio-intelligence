"""Independent fixed risk table contracts and exact financial cell semantics."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import decode_report_row, encode_report_row
from trading212_domain.report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
from trading212_domain.report_schema import report_tables, table_schema, validate_report_row
from trading212_domain.values import CurrencyCode

from tests.unit.domain.report_factories import selection

pytestmark = pytest.mark.unit

# Literal expected wire columns are deliberately independent of RISK_TABLE_COLUMNS.
_EXPECTED = {
    "risk_basis_v1": """
        run_id:id result_id:id result_digest:id input_digest:id definition_id:id
        definition_version_id:id definition_version_number:int definition_digest:id
        account_id:id portfolio_snapshot_id:id historical_input_snapshot_id:id
        historical_input_digest:id benchmark_version_id:id? xray_run_id:id?
        xray_input_id:id? xray_input_digest:id? xray_result_digest:id?
        window_start_date:date window_end_date:date window_start_at:utc window_end_at:utc
        source_cutoff_at:utc reporting_currency:enum coverage_policy:enum knowledge_policy:enum
        modeled_portfolio_snapshot_id:id? modeled_valuation_at:utc? run_created_at:utc
        run_completed_at:utc run_expires_at:utc family:enum method_key:id method_version:id
        schema_version:id numerical_profile:id annualization_factor:int
        covariance_degrees_of_freedom:int
    """,
    "risk_definition_v1": """
        name:text description:text calendar_id:id calendar_version:id frequency:enum
        return_kind:enum annual_risk_free:R annual_minimum_acceptable_return:R
        rolling_window:int confidence:R horizon:int regularization:enum shrinkage:R
        method_version:id
    """,
    "risk_observed_v1": """
        requested_observations:int used_observations:int omitted_observations:int
        outlier_observations:int mean_periodic_return:R volatility_periodic:R
        volatility_annualized:R downside_annualized:R beta:R alpha_annualized:R
        benchmark_pairs:int maximum_drawdown:R
    """,
    "risk_rolling_v1": "ordinal:int end_at:utc observations:int volatility:R",
    "risk_matrix_summary_v1": """
        asset_count:int requested_intervals:int used_intervals:int omitted_intervals:int
        numerical_zero_pivot_count:int
    """,
    "risk_matrix_axes_v1": "ordinal:int instrument_id:id numerical_zero_pivot:bool",
    "risk_matrix_cells_v1": """
        row_ordinal:int column_ordinal:int row_instrument_id:id column_instrument_id:id
        covariance_periodic:D(score) regularized_covariance_periodic:D(score) correlation:R
    """,
    "risk_tails_v1": """
        method:enum confidence:R horizon:int observations:int tail_mass:D(score)?
        value_at_risk:R expected_shortfall:R loss_sign:enum quantile:enum horizon_policy:enum
    """,
    "risk_modeled_v1": """
        coverage:R complete_universe:bool volatility_annualized:R diversification_ratio:D(score)
        component_sum:R component_display_residual:D(residual) weight_display_residual:D(residual)
    """,
    "risk_components_v1": """
        ordinal:int instrument_id:id weight:R marginal_annualized:R component_annualized:R
    """,
    "risk_concentration_v1": """
        hhi:D(score) effective_holdings:D(score) company_known_weight:R cash_weight:R
        unresolved_weight:R lower_bound:bool quality:enum basis:enum
    """,
    "risk_run_assets_v1": "ordinal:int instrument_id:id source_series_id:id",
    "risk_series_v1": """
        ordinal:int series_key:id role:enum instrument_id:id? reporting_currency:enum
        calendar_id:id calendar_version:id frequency:enum source_cutoff_at:utc basis:enum
        interval_count:int
    """,
    "risk_intervals_v1": """
        series_ordinal:int series_key:id ordinal:int start_at:utc end_at:utc simple_return:R
        quality:enum reason:enum?
    """,
    "risk_history_context_v1": """
        account_id:id input_digest:id window_start_date:date window_end_date:date
        source_cutoff_at:utc reporting_currency:enum coverage_policy:enum knowledge_policy:enum
        method_key:id method_version:id source_policy_version:id? accounting_policy_version:id
        quality:enum availability:enum reconstruction:enum schema_version:id
    """,
    "risk_history_members_v1": "kind:enum ordinal:int name:id version:id?",
    "risk_xray_paths_v1": """
        key:id root_key:id root_kind:enum position_id:id? instrument_id:id? entity_id:id?
        name:text explicit_cash:bool unresolved_reason:enum? reporting_value:M absolute_weight:R
        relative_weight:R normalized_known_weight:R? quality:enum confidence:R?
    """,
}

_KINDS = {
    r.CellKind.IDENTIFIER: "id",
    r.CellKind.TEXT: "text",
    r.CellKind.ENUM: "enum",
    r.CellKind.INSTANT: "utc",
    r.CellKind.DATE: "date",
    r.CellKind.INTEGER: "int",
    r.CellKind.BOOLEAN: "bool",
}
_ROLES = {
    r.DecimalRole.MONEY: "M",
    r.DecimalRole.RATIO: "R",
    r.DecimalRole.SCORE: "D(score)",
    r.DecimalRole.RESIDUAL: "D(residual)",
}


def _signature(column: r.ReportColumn) -> str:
    assert column.kind is not None
    if column.kind is r.CellKind.DECIMAL:
        assert column.decimal_role is not None
        kind = _ROLES[column.decimal_role]
    else:
        assert column.decimal_role is None
        kind = _KINDS[column.kind]
    return f"{column.key}:{kind}{'?' if column.optional else ''}"


@pytest.mark.parametrize(("name", "expected"), _EXPECTED.items())
def test_literal_risk_table_column_order_and_types(name: str, expected: str) -> None:
    schema = table_schema(r.ReportTableKey(name))
    assert tuple(_signature(column) for column in schema.columns) == tuple(expected.split())
    assert 1 <= len(schema.columns) <= 64
    assert len({column.key for column in schema.columns}) == len(schema.columns)
    assert schema.key.value == name


def test_risk_analytical_and_proof_inventory_is_ordered_and_disjoint() -> None:
    assert tuple(item.value for item in RISK_REPORT_TABLES) == (
        "risk_basis_v1",
        "risk_definition_v1",
        "risk_observed_v1",
        "risk_rolling_v1",
        "risk_matrix_summary_v1",
        "risk_matrix_axes_v1",
        "risk_matrix_cells_v1",
        "risk_tails_v1",
        "risk_modeled_v1",
        "risk_components_v1",
        "risk_concentration_v1",
    )
    assert tuple(item.value for item in RISK_PROOF_TABLES) == (
        "risk_run_assets_v1",
        "risk_series_v1",
        "risk_intervals_v1",
        "risk_history_context_v1",
        "risk_history_members_v1",
        "risk_xray_paths_v1",
    )
    combined = (*RISK_REPORT_TABLES, *RISK_PROOF_TABLES)
    assert len(set(combined)) == 17
    assert set(item.value for item in combined) == set(_EXPECTED)
    assert tuple(item for item in r.ReportTableKey if item in combined) == combined


def test_registration_does_not_add_risk_tables_to_legacy_selection() -> None:
    assert set(report_tables(selection())).isdisjoint((*RISK_REPORT_TABLES, *RISK_PROOF_TABLES))


def _row(table: r.ReportTableKey) -> r.ReportRow:
    cells = []
    for column in table_schema(table).columns:
        kind = column.kind
        assert kind is not None
        value: str | Decimal | int | bool | date | datetime
        if kind is r.CellKind.DECIMAL:
            value = Decimal("0")
        elif kind is r.CellKind.INTEGER:
            value = 0
        elif kind is r.CellKind.BOOLEAN:
            value = False
        elif kind is r.CellKind.INSTANT:
            value = datetime(2026, 9, 1, tzinfo=UTC)
        elif kind is r.CellKind.DATE:
            value = date(2026, 9, 1)
        else:
            value = "fixture"
        cells.append(
            r.ReportCell(
                kind=kind,
                value=value,
                decimal_role=column.decimal_role,
                currency=CurrencyCode("EUR")
                if column.decimal_role is r.DecimalRole.MONEY
                else None,
            )
        )
    return r.ReportRow(key="risk.fixture", context_key="risk.context", cells=tuple(cells))


def _replace_cell(
    row: r.ReportRow, table: r.ReportTableKey, key: str, cell: r.ReportCell
) -> r.ReportRow:
    ordinal = tuple(column.key for column in table_schema(table).columns).index(key)
    return replace(row, cells=(*row.cells[:ordinal], cell, *row.cells[ordinal + 1 :]))


@pytest.mark.parametrize("name", tuple(_EXPECTED))
def test_each_fixed_risk_table_has_typed_roundtrippable_rows(name: str) -> None:
    table = r.ReportTableKey(name)
    row = _row(table)
    validate_report_row(table, row)
    assert decode_report_row(encode_report_row(row)) == row


@pytest.mark.parametrize(
    ("value", "state", "reason"),
    [
        (Decimal("0"), r.CellState.AVAILABLE, None),
        (Decimal("-0.000000000000000001"), r.CellState.AVAILABLE, None),
        (None, r.CellState.UNAVAILABLE, "risk.insufficient_tail"),
    ],
)
def test_tail_zero_signed_exact_value_and_unavailable_reason_remain_distinct(
    value: Decimal | None, state: r.CellState, reason: str | None
) -> None:
    table = r.ReportTableKey.RISK_TAILS_V1
    cell = r.ReportCell(
        kind=r.CellKind.DECIMAL,
        decimal_role=r.DecimalRole.RATIO,
        value=value,
        state=state,
        reason_key=reason,
        confidence=Decimal("0.95"),
    )
    row = _replace_cell(_row(table), table, "value_at_risk", cell)
    validate_report_row(table, row)
    restored = decode_report_row(encode_report_row(row))
    assert restored == row
    assert restored.cells[5].value == value
    assert restored.cells[5].state is state
    assert restored.cells[5].reason_key == reason


def test_fractional_historical_tail_mass_is_a_score_and_parametric_mass_is_inapplicable() -> None:
    table = r.ReportTableKey.RISK_TAILS_V1
    fractional = r.ReportCell(
        kind=r.CellKind.DECIMAL, decimal_role=r.DecimalRole.SCORE, value=Decimal("5.25")
    )
    historical = _replace_cell(_row(table), table, "tail_mass", fractional)
    validate_report_row(table, historical)
    assert decode_report_row(encode_report_row(historical)).cells[4] == fractional
    absent = replace(fractional, value=None, state=r.CellState.NOT_APPLICABLE)
    parametric = _replace_cell(_row(table), table, "tail_mass", absent)
    validate_report_row(table, parametric)
    assert decode_report_row(encode_report_row(parametric)).cells[4] == absent


@pytest.mark.parametrize(
    ("table", "key", "role"),
    [
        (r.ReportTableKey.RISK_OBSERVED_V1, "beta", r.DecimalRole.RATIO),
        (r.ReportTableKey.RISK_MODELED_V1, "volatility_annualized", r.DecimalRole.RATIO),
        (r.ReportTableKey.RISK_CONCENTRATION_V1, "effective_holdings", r.DecimalRole.SCORE),
        (r.ReportTableKey.RISK_INTERVALS_V1, "simple_return", r.DecimalRole.RATIO),
    ],
)
def test_required_financial_metric_cannot_be_silently_made_inapplicable(
    table: r.ReportTableKey, key: str, role: r.DecimalRole
) -> None:
    absent = r.ReportCell(
        kind=r.CellKind.DECIMAL,
        decimal_role=role,
        value=None,
        state=r.CellState.NOT_APPLICABLE,
    )
    with pytest.raises(DomainError):
        validate_report_row(table, _replace_cell(_row(table), table, key, absent))
    unavailable = replace(absent, state=r.CellState.UNAVAILABLE, reason_key="risk.missing")
    validate_report_row(table, _replace_cell(_row(table), table, key, unavailable))


def test_covariance_and_correlation_keep_different_declared_decimal_roles() -> None:
    table = r.ReportTableKey.RISK_MATRIX_CELLS_V1
    wrong_ratio = r.ReportCell(
        kind=r.CellKind.DECIMAL, decimal_role=r.DecimalRole.RATIO, value=Decimal("0.25")
    )
    with pytest.raises(DomainError):
        validate_report_row(
            table, _replace_cell(_row(table), table, "covariance_periodic", wrong_ratio)
        )
    correct_score = replace(wrong_ratio, decimal_role=r.DecimalRole.SCORE)
    validate_report_row(
        table, _replace_cell(_row(table), table, "covariance_periodic", correct_score)
    )


def test_financial_residuals_are_decimal_cells_and_pivot_markers_are_booleans() -> None:
    residual_table = r.ReportTableKey.RISK_MODELED_V1
    residual = r.ReportCell(
        kind=r.CellKind.DECIMAL,
        decimal_role=r.DecimalRole.RESIDUAL,
        value=Decimal("-0.000000000000000001"),
    )
    row = _replace_cell(
        _row(residual_table), residual_table, "component_display_residual", residual
    )
    validate_report_row(residual_table, row)
    assert decode_report_row(encode_report_row(row)).cells[5] == residual
    axes = r.ReportTableKey.RISK_MATRIX_AXES_V1
    with pytest.raises(DomainError):
        validate_report_row(
            axes,
            _replace_cell(
                _row(axes),
                axes,
                "numerical_zero_pivot",
                r.ReportCell(kind=r.CellKind.INTEGER, value=0),
            ),
        )


@pytest.mark.parametrize("invalid", [0.95, True, "0.95", Decimal("NaN"), Decimal("1e-19")])
def test_risk_financial_cells_reject_float_coercion_strings_and_noncanonical_decimals(
    invalid: object,
) -> None:
    with pytest.raises(DomainError):
        r.ReportCell(
            kind=r.CellKind.DECIMAL,
            decimal_role=r.DecimalRole.RATIO,
            value=cast(Any, invalid),
        )
