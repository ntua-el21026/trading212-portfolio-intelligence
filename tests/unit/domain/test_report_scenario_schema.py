"""All initial V3 table identities/columns are frozen independently of the registry."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    build_report_chunk,
    decode_report_chunk,
    encode_report_chunk,
)
from trading212_domain.report_scenario_schema import (
    SCENARIO_MEMBER_FIELDS,
    SCENARIO_PROOF_TABLES,
    SCENARIO_REPORT_TABLES,
)
from trading212_domain.report_schema import table_schema, validate_report_row

from tests.unit.domain.report_factories import uid

pytestmark = pytest.mark.unit
PLAN = json.loads(
    (Path(__file__).with_name("fixtures") / "report-scenario-v3-table-columns.json").read_text()
)
TABLES = {**PLAN["analytical_tables"], **PLAN["proof_tables"]}


def _member(
    owner: str = "subject", field: str = "identity_decision_ids", ordinal: int = 0
) -> r.ReportRow:
    return r.ReportRow(
        key="scenario.subject.member.0",
        context_key="scenario.context",
        cells=(
            r.ReportCell(kind=r.CellKind.ENUM, value=owner),
            r.ReportCell(kind=r.CellKind.IDENTIFIER, value="scenario.subject"),
            r.ReportCell(kind=r.CellKind.ENUM, value=field),
            r.ReportCell(kind=r.CellKind.INTEGER, value=ordinal),
            r.ReportCell(kind=r.CellKind.IDENTIFIER, value=str(uid(1))),
        ),
    )


def test_fixed_scenario_registry_is_exactly_ten_analytical_and_seventeen_proof_tables() -> None:
    assert tuple(x.value for x in SCENARIO_REPORT_TABLES) == tuple(PLAN["analytical_tables"])
    assert tuple(x.value for x in SCENARIO_PROOF_TABLES) == tuple(PLAN["proof_tables"])
    assert len(SCENARIO_REPORT_TABLES) == 10
    assert len(SCENARIO_PROOF_TABLES) == 17
    assert len(set((*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES))) == 27
    assert set(x.value for x in r.ReportTableKey if x.value.startswith("scenario_")) == set(TABLES)


@pytest.mark.parametrize("name", tuple(TABLES))
def test_each_scenario_table_has_its_fixed_ordered_scalar_columns(name: str) -> None:
    schema = table_schema(r.ReportTableKey(name))
    role = {
        "M": r.DecimalRole.MONEY,
        "R": r.DecimalRole.RATIO,
        "Q": r.DecimalRole.QUANTITY,
        "D(score)": r.DecimalRole.SCORE,
        "D(price)": r.DecimalRole.PRICE,
        "D(fx)": r.DecimalRole.FX,
        "D(residual)": r.DecimalRole.RESIDUAL,
    }
    scalar = {
        "id": r.CellKind.IDENTIFIER,
        "text": r.CellKind.TEXT,
        "enum": r.CellKind.ENUM,
        "date": r.CellKind.DATE,
        "utc": r.CellKind.INSTANT,
        "int": r.CellKind.INTEGER,
        "bool": r.CellKind.BOOLEAN,
    }
    expected = []
    for key, code in TABLES[name]:
        actual = code.removesuffix("?")
        expected.append(
            (
                key,
                r.CellKind.DECIMAL if actual in role else scalar[actual],
                role.get(actual),
                code.endswith("?"),
            )
        )
    assert [(x.key, x.kind, x.decimal_role, x.optional) for x in schema.columns] == expected
    assert schema.schema_version == "1.0.0"
    assert len(schema.columns) <= 64


@pytest.mark.parametrize(
    ("owner", "field"),
    [(owner, field) for owner, fields in SCENARIO_MEMBER_FIELDS.items() for field in fields],
)
def test_ordered_memberships_use_shared_lossless_chunk_codec(owner: str, field: str) -> None:
    row = _member(owner, field)
    chunk = build_report_chunk(r.ReportTableKey.SCENARIO_MEMBERS_V1, 0, (row,))
    assert decode_report_chunk(encode_report_chunk(chunk)) == chunk
    assert chunk.rows[0].cells[4].value == str(uid(1))


@pytest.mark.parametrize(
    ("owner", "field", "ordinal"),
    [
        ("arbitrary", "source_reference_ids", 0),
        ("subject", "arbitrary", 0),
        ("subject", "coefficient", 0),
        ("subject", "assumptions", 0),
        ("subject", "identity_decision_ids", -1),
    ],
)
def test_membership_cannot_be_an_untyped_property_bag(owner: str, field: str, ordinal: int) -> None:
    with pytest.raises(DomainError):
        validate_report_row(r.ReportTableKey.SCENARIO_MEMBERS_V1, _member(owner, field, ordinal))


def test_new_table_reuses_exact_cell_state_and_unknown_column_denial() -> None:
    original = _member()
    with pytest.raises(DomainError):
        validate_report_row(
            r.ReportTableKey.SCENARIO_MEMBERS_V1, replace(original, cells=original.cells[:-1])
        )
    with pytest.raises(DomainError):
        validate_report_row(
            r.ReportTableKey.SCENARIO_MEMBERS_V1,
            replace(
                original,
                cells=(r.ReportCell(kind=r.CellKind.TEXT, value="subject"), *original.cells[1:]),
            ),
        )
    with pytest.raises(DomainError):
        table_schema("scenario_arbitrary_v1")
