"""Canonical scenario result publication and complete normalized replay verification."""

from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session, undefer
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    encode_scenario_execution,
    scenario_result_digest,
    scenario_result_from_json,
)
from trading212_domain.sources import SourceUse

from .premium_models import PremiumJobModel, PremiumOwned, PremiumRunLicenseModel, PremiumRunModel
from .report_authorization import ReportAuthorization
from .scenario_input_store import ScenarioInputStore
from .scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
)
from .scenario_original_source_authorization import reauthorize_original_sensitivity_sources
from .scenario_result_projection import ScenarioResultProjection, normalized_scenario_result
from .scenario_result_verification import verify_scenario_result_inputs
from .scenario_retention_boundary import require_scenario_retention
from .scenario_run_capture import _conditional_auth
from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code

_RESULT_MODELS = (ScenarioComponentModel, ScenarioAppliedSensitivityModel)
_FIELDS = {
    model: frozenset(
        column.name
        for column in model.__table__.columns
        if column.name not in {"owner_id", "account_id", "result_id", "created_at"}
    )
    for model in _RESULT_MODELS
}


def _canonical_result(result: ScenarioCalculation) -> tuple[ScenarioCalculation, str]:
    try:
        digest = scenario_result_digest(result)
        value = scenario_result_from_json(canonical_scenario_bytes(result), expected_digest=digest)
        return value, digest
    except DomainError as error:
        code = (
            Code.INPUT_BOUND_EXCEEDED
            if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
            else Code.SCENARIO_UNAVAILABLE
        )
        raise ScenarioStorageError(code) from None


def _projected(
    projection: ScenarioResultProjection,
) -> dict[type[PremiumOwned], tuple[dict[str, object], ...]]:
    return {
        ScenarioComponentModel: projection.components,
        ScenarioAppliedSensitivityModel: projection.applied_uses,
    }


class ScenarioResultStore(ScenarioInputStore):
    def _result_authority(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        inputs: ScenarioExecutionInput,
        *,
        write: bool,
    ) -> tuple[ReportAuthorization, PremiumRunModel]:
        auth = self.authority(session, auth, write=write)
        current = self._owned(session, auth, PremiumRunModel, root.id)
        if (
            current.kind != "scenario"
            or current.owner_id != root.owner_id
            or current.account_id != root.account_id
            or current.input_digest != inputs.input_digest
            or current.expires_at != inputs.expires_at
            or current.expires_at <= self._now()
        ):
            raise ScenarioStorageError(Code.CONFLICT)
        history_id = (
            None if inputs.replay is None else inputs.replay.selection.historical_input_snapshot_id
        )
        auth = _conditional_auth(self, session, auth, history_id)
        retained = self.read_retained_input(session, auth, current.id)
        if encode_scenario_execution(retained) != encode_scenario_execution(inputs):
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        return auth, current

    def _finish_result_authority(
        self, session: Session, auth: ReportAuthorization, root: PremiumRunModel
    ) -> None:
        sources = self.copy_authority(retained_at=root.created_at)
        identifiers = tuple(
            session.scalars(
                select(PremiumRunLicenseModel.license_version_id)
                .where(
                    PremiumRunLicenseModel.run_id == root.id,
                    PremiumRunLicenseModel.owner_id == auth.owner_id,
                    PremiumRunLicenseModel.account_id == auth.account_id,
                )
                .order_by(PremiumRunLicenseModel.license_version_id)
                .limit(8193)
            )
        )
        if len(identifiers) > 8192:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        for identifier in identifiers:
            sources._permit(session, auth.owner_id, identifier, SourceUse.DISPLAY)
        auth.check(session, now=self._now())
        require_scenario_retention(
            expires_at=root.expires_at, copy_deadline=sources.copy_deadline, now=self._now()
        )
        reauthorize_original_sensitivity_sources(session, auth, root.id, sources)
        require_scenario_retention(
            expires_at=root.expires_at, copy_deadline=sources.copy_deadline, now=self._now()
        )

    def _result_bytes(self, session: Session, root: PremiumRunModel) -> int:
        size = session.scalar(text("SELECT scenario_storage_bytes(:run)"), {"run": root.id})
        if (
            type(size) is not int
            or size < 0
            or size > 33554432
            or size > root.reserved_bytes + root.retained_bytes
        ):
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        return size

    def publish_result(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        inputs: ScenarioExecutionInput,
        result: ScenarioCalculation,
    ) -> ScenarioResultModel:
        """Caller owns the active fenced job, capacity accounting and same-transaction success."""
        auth, root = self._result_authority(session, auth, root, inputs, write=True)
        value, digest = _canonical_result(result)
        verify_scenario_result_inputs(inputs, value)
        if (
            session.scalar(
                select(ScenarioResultModel.id).where(ScenarioResultModel.run_id == root.id)
            )
            is not None
        ):
            raise ScenarioStorageError(Code.CONFLICT)
        identifier = uuid5(root.id, "scenario_results")
        projection = normalized_scenario_result(value, identifier)
        self._finish_result_authority(session, auth, root)
        current_bytes = self._result_bytes(session, root)
        private_bytes = len(projection.canonical_result) + sum(
            len(cast(bytes, row["canonical_component"])) for row in projection.components
        )
        if current_bytes + private_bytes > 33554432:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        row = ScenarioResultModel(
            id=identifier,
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            run_id=root.id,
            content_digest=digest,
            canonical_result=projection.canonical_result,
            component_count=len(projection.components),
            sensitivity_source_row_count=value.sensitivity_source_row_count,
            applied_use_count=len(projection.applied_uses),
            sealed=False,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        rows = _projected(projection)
        for model in _RESULT_MODELS:
            for fields in rows[model]:
                if set(fields) != _FIELDS[model]:
                    raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
            for begin in range(0, len(rows[model]), 256):
                auth.check(session, now=self._now())
                session.execute(
                    insert(model).execution_options(render_nulls=True),
                    [
                        dict(
                            fields,
                            owner_id=auth.owner_id,
                            account_id=auth.account_id,
                            result_id=row.id,
                            created_at=row.created_at,
                        )
                        for fields in rows[model][begin : begin + 256]
                    ],
                )
        session.flush()
        row.sealed = True
        session.flush()
        self._result_bytes(session, root)
        self._finish_result_authority(session, auth, root)
        return row

    def read_result(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        inputs: ScenarioExecutionInput,
    ) -> ScenarioCalculation:
        auth, root = self._result_authority(session, auth, root, inputs, write=False)
        state = session.scalar(
            select(PremiumJobModel.state).where(
                PremiumJobModel.run_id == root.id,
                PremiumJobModel.owner_id == auth.owner_id,
                PremiumJobModel.account_id == auth.account_id,
            )
        )
        row = session.scalar(
            select(ScenarioResultModel).where(
                ScenarioResultModel.run_id == root.id,
                ScenarioResultModel.owner_id == auth.owner_id,
                ScenarioResultModel.account_id == auth.account_id,
            )
        )
        if state != "succeeded" or row is None or not row.sealed:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        self._result_bytes(session, root)
        self._finish_result_authority(session, auth, root)
        payload = session.scalar(
            select(ScenarioResultModel.canonical_result).where(
                ScenarioResultModel.id == row.id,
                ScenarioResultModel.owner_id == auth.owner_id,
                ScenarioResultModel.account_id == auth.account_id,
            )
        )
        if not payload:
            raise ScenarioStorageError(Code.RUN_EXPIRED)
        try:
            value = scenario_result_from_json(payload, expected_digest=row.content_digest)
        except DomainError:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE) from None
        verify_scenario_result_inputs(inputs, value)
        projection = normalized_scenario_result(value, row.id)
        if (
            payload != projection.canonical_result
            or row.component_count != len(projection.components)
            or row.applied_use_count != len(projection.applied_uses)
            or row.sensitivity_source_row_count != value.sensitivity_source_row_count
        ):
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        expected = _projected(projection)
        for model in _RESULT_MODELS:
            stored = tuple(
                session.scalars(
                    select(model)
                    .options(undefer("*"))
                    .where(
                        model.result_id == row.id,
                        model.owner_id == auth.owner_id,
                        model.account_id == auth.account_id,
                    )
                    .limit(len(expected[model]) + 1)
                )
            )
            if len(stored) != len(expected[model]):
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
            by_id = {item.id: item for item in stored}
            for fields in expected[model]:
                actual = by_id.get(cast(UUID, fields["id"]))
                if (
                    actual is None
                    or set(fields) != _FIELDS[model]
                    or any(getattr(actual, name) != value for name, value in fields.items())
                ):
                    raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        self._finish_result_authority(session, auth, root)
        return value
