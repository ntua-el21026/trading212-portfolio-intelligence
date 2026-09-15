"""Schema metadata pins numerical identities and keeps private bytes deferred."""

import ast
from pathlib import Path
from typing import cast

from sqlalchemy import ForeignKeyConstraint, LargeBinary, Table
from trading212_persistence.projection_models import (
    PROJECTION_MODELS,
    ProjectionChunkModel,
    ProjectionInputModel,
    ProjectionPointModel,
    ProjectionResultModel,
    ProjectionRunSourceModel,
    ProjectionSourceProofModel,
)
from trading212_persistence.types import ExactNumeric


def test_private_financial_payloads_are_deferred_and_source_identity_is_separate() -> None:
    for model, name in (
        (ProjectionInputModel, "canonical_capture"),
        (ProjectionInputModel, "canonical_input"),
        (ProjectionChunkModel, "canonical_chunk"),
        (ProjectionResultModel, "canonical_result"),
        (ProjectionSourceProofModel, "canonical_proof"),
    ):
        assert model.__mapper__.column_attrs[name].deferred
    assert not any(
        isinstance(column.type, LargeBinary)
        for column in ProjectionRunSourceModel.__table__.columns
    )
    assert {"subject_id", "content_digest", "original_created_at", "source_expires_at"} <= set(
        ProjectionRunSourceModel.__table__.columns.keys()
    )


def test_every_retained_financial_amount_uses_existing_exact_numeric() -> None:
    for field in (
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
    ):
        assert isinstance(ProjectionPointModel.__table__.c[field].type, ExactNumeric)
    for model in PROJECTION_MODELS:
        assert {"id", "owner_id", "account_id", "created_at"} <= set(model.__table__.columns.keys())


def test_checkpoint_binding_includes_owner_account_and_numerical_digest() -> None:
    references = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in cast(Table, ProjectionChunkModel.__table__).constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        "projection_runs.owner_id",
        "projection_runs.account_id",
        "projection_runs.id",
        "projection_runs.numerical_input_digest",
    ) in references
    assert {
        "lease_token",
        "consumer_attempt",
        "job_id",
        "first_path",
        "path_count",
        "variant",
    } <= set(ProjectionChunkModel.__table__.columns.keys())


def test_migration_freezes_ddl_and_extends_shared_capacity_without_new_job_family() -> None:
    tree = ast.parse(Path("migrations/versions/20260915_0022_projections.py").read_text())
    constants = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert (
        constants["revision"] == "20260915_0022" and constants["down_revision"] == "20260915_0021"
    )
    assert set(constants["_TABLES"]) == {model.__tablename__ for model in PROJECTION_MODELS}
    assert not any(
        name.endswith("_jobs") or name.endswith("_outbox") for name in constants["_TABLES"]
    )
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name and name.startswith("trading212_") for name in imports)
    assert "projection_capture_complete(NEW.id)" in constants["_SHARED_GUARDS"]
    assert "projection_result_complete_check(result)" in constants["_SHARED_GUARDS"]
    assert (
        "Projection metadata prevents downgrade"
        in Path("migrations/versions/20260915_0022_projections.py").read_text()
    )
