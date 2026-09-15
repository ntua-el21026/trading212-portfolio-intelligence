"""Independent storage boundaries for scenario identities and sensitive payloads."""

import ast
from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, LargeBinary, String, Table
from trading212_persistence.scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioExclusionModel,
    ScenarioRunPayloadModel,
    ScenarioShockModel,
    ScenarioVersionModel,
)
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
)


def test_permanent_assumptions_and_source_headers_cannot_store_coefficients_or_payloads() -> None:
    for model in (
        ScenarioVersionModel,
        ScenarioShockModel,
        ScenarioExclusionModel,
        ScenarioSensitivityVersionModel,
        ScenarioSensitivityObservationModel,
        ScenarioSensitivityEvidenceModel,
    ):
        assert "coefficient" not in model.__table__.c
        assert not any(isinstance(column.type, LargeBinary) for column in model.__table__.c)
    assert "size" in ScenarioShockModel.__table__.c
    assert {
        "source_version_id",
        "source_version_digest",
        "driver_id",
        "driver_definition_version_id",
    } <= set(ScenarioShockModel.__table__.c.keys())


def test_source_payloads_are_deferred_for_authorization_before_decode() -> None:
    for model, name in (
        (ScenarioSensitivityVersionPayloadModel, "canonical_payload"),
        (ScenarioSensitivityObservationPayloadModel, "canonical_payload"),
        (ScenarioSensitivityEvidencePayloadModel, "canonical_payload"),
        (ScenarioRunPayloadModel, "canonical_input"),
    ):
        assert model.__mapper__.column_attrs[name].deferred
    assert ScenarioSensitivityObservationPayloadModel.__mapper__.column_attrs.coefficient.deferred
    assert ScenarioAppliedSensitivityModel.__mapper__.column_attrs.coefficient.deferred


def test_evidence_record_identity_is_not_a_broker_record_reference() -> None:
    assert not ScenarioSensitivityEvidenceModel.__table__.c.source_record_id.foreign_keys
    references = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in cast(Table, ScenarioSensitivityEvidenceModel.__table__).constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        "provider_license_versions.owner_id",
        "provider_license_versions.provider_id",
        "provider_license_versions.id",
    ) in references


def test_component_identity_preserves_xray_string_keys_and_zero_effect_diagnostics() -> None:
    table = ScenarioComponentModel.__table__
    assert cast(String, table.c.path_key.type).length == 1024
    assert cast(String, table.c.root_key.type).length == 1024
    assert {"position_id", "snapshot_cash_id", "root_instrument_id", "money_basis"} <= set(
        table.c.keys()
    )
    assert "component_key" not in table.c and "path_id" not in table.c
    use = ScenarioAppliedSensitivityModel.__table__
    assert {"reason", "effect_reason", "effect_quality", "effect_ratio"} <= set(use.c.keys())


def test_migration_is_frozen_and_preserves_unimplemented_projection_rejection() -> None:
    path = Path("migrations/versions/20260915_0020_scenarios.py")
    tree = ast.parse(path.read_text())
    constants = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert constants["down_revision"] == "20260915_0019"
    assert len(constants["_TABLES"]) == 23
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name and name.startswith("trading212_") for name in imported)
    guards = constants["_SHARED_GUARDS"]
    assert "IF NEW.kind NOT IN ('risk','scenario')" in guards
    assert "scenario_capture_complete(NEW.id)" in guards
    assert (
        "risk_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM scenar"
        "io_definition_versions" in guards
    )
    assert "scenarios.calculate.v1" in guards
    assert (
        "'scenario' THEN SELECT sealed INTO pinned FROM scenario_runs"
        in constants["_LICENSE_GUARD"]
    )


def test_scalar_availability_keeps_source_state_and_effect_state_separate() -> None:
    source = " ".join(
        str(item.sqltext)
        for item in cast(Table, ScenarioSensitivityObservationPayloadModel.__table__).constraints
        if isinstance(item, CheckConstraint)
    )
    assert (
        "state<>'available' OR (response_basis='local_economic_value' AND response_currency"
        " IS NOT NULL)" in source
    )
    effect = " ".join(
        str(item.sqltext)
        for item in cast(Table, ScenarioAppliedSensitivityModel.__table__).constraints
        if isinstance(item, CheckConstraint)
    )
    assert "(effect_ratio IS NULL)=(effect_reason IS NOT NULL)" in effect
    assert (
        "reason IS NOT NULL OR (observation_id IS NOT NULL AND coefficient IS NOT NULL)" in effect
    )
