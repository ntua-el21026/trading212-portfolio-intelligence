"""Authorized fixed projection capture, separate from durable job orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker, undefer
from trading212_application import projection as app
from trading212_application.projection_capture import (
    ProjectionAssumptionVersion,
    ProjectionCapturePlan,
    ProjectionGoalVersion,
    ProjectionRunSelection,
    preflight_projection,
    projection_capture_digest,
)
from trading212_domain.projection import PROJECTION_MAX_BYTES, ProjectionSourcePin
from trading212_domain.serialization import canonical_json

from . import projection_models as pm
from .premium_models import PremiumRetentionModel, PremiumRunLicenseModel, PremiumRunModel
from .projection_capture_codec import ProjectionCaptureBinding, ProjectionCodecError
from .projection_definition_store import (
    ProjectionDefinitionStore,
    ProjectionStorageError,
    projection_owner_lock,
)
from .projection_retained_codec import (
    ProjectionInputBytes,
    pack_projection_input,
    unpack_projection_input,
)
from .projection_source_memberships import retained_source_keys, verify_retained_source_keys
from .projection_source_store import ProjectionSourceBundle, ProjectionSourceStore
from .report_authorization import ReportAuthorization


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedProjectionInputs:
    plan: ProjectionCapturePlan
    sources: ProjectionSourceBundle
    stored: ProjectionInputBytes

    @property
    def input_digest(self) -> str:
        return projection_capture_digest(self.plan)

    @property
    def expires_at(self) -> datetime:
        return self.sources.expires_at


def projection_input_rows(plan: ProjectionCapturePlan) -> dict[Any, tuple[dict[str, Any], ...]]:
    """One exact normalized representation of accepted original dates and numerical fields."""
    selected, inputs = plan.selection, plan.inputs
    sensitivity = selected.sensitivity
    input_row = {
        "initial_value": inputs.initial.value.amount,
        "base_monthly": inputs.schedule.base_monthly.amount,
        "annual_growth": inputs.schedule.annual_growth,
        "contribution_delta": None
        if sensitivity is None
        else sensitivity.contribution_delta.amount,
        "annual_mean_log_delta": None if sensitivity is None else sensitivity.annual_mean_log_delta,
        "pause_count": len(selected.schedule.paused_dates),
        "entry_count": len(selected.schedule.entries),
    }
    points = {month: i for i, month in enumerate(selected.retained_months)}
    return {
        pm.ProjectionInputModel: (input_row,),
        pm.ProjectionRunAllocationModel: tuple(
            {"asset_index": i, "asset_key": a.key, "weight": a.weight}
            for i, a in enumerate(selected.allocation)
        ),
        pm.ProjectionCalendarBoundaryModel: tuple(
            {"month": i, "on": on, "point_index": points.get(i)}
            for i, on in enumerate(plan.calendar.boundaries)
        ),
        pm.ProjectionRunPauseModel: tuple(
            {"on": on, "month": plan.calendar.flow_month(on)}
            for on in selected.schedule.paused_dates
        ),
        pm.ProjectionRunScheduleEntryModel: tuple(
            {
                "entry_key": e.key,
                "on": e.on,
                "month": plan.calendar.flow_month(e.on),
                "kind": e.kind,
                "value": e.value.amount,
            }
            for e in selected.schedule.entries
        ),
    }


def projection_run_header(plan: ProjectionCapturePlan, source_count: int) -> dict[str, Any]:
    selection = plan.selection
    snapshot = plan.snapshot
    return {
        "assumption_version_id": selection.assumption_version_id,
        "assumption_digest": plan.assumption_version.content_digest,
        "goal_version_id": selection.goal_version_id,
        "goal_digest": None if plan.goal_version is None else plan.goal_version.content_digest,
        "numerical_input_digest": plan.numerical_input_digest,
        "capture_digest": projection_capture_digest(plan),
        "seed": selection.seed,
        "months": selection.months,
        "path_count": selection.paths,
        "asset_count": len(selection.allocation),
        "retained_point_count": len(selection.retained_months),
        "variant_count": 1 if selection.sensitivity is None else 3,
        "source_count": source_count,
        "initial_kind": selection.initial.kind,
        "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
        "snapshot_digest": None if snapshot is None else snapshot.content_digest,
        "snapshot_valuation_at": None if snapshot is None else snapshot.valuation_at,
        "anchor_date": plan.calendar.anchor_date,
        "reporting_currency": plan.inputs.assumptions.reporting_currency.value,
        "calendar_rule": plan.calendar.rule,
    }


class ProjectionInputStore(ProjectionDefinitionStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        sources = ProjectionSourceStore(
            sessions, cursor_signing_key=cursor_signing_key, clock=clock
        )
        super().__init__(
            sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
            calibration_resolver=sources.resolve_calibration,
        )
        self.sources = sources

    def capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        selection: ProjectionRunSelection,
        *,
        retained_at: datetime | None = None,
    ) -> CapturedProjectionInputs:
        auth = self.authority(session, auth)
        if selection.account_id != auth.account_id:
            raise ProjectionStorageError(app.ProjectionErrorCode.NOT_FOUND)
        projection_owner_lock(session, auth.owner_id)
        assumption = self.read_assumption_version(session, auth, selection.assumption_version_id)
        goal = None
        if selection.goal_version_id is not None:
            view = self.read_goal_version(session, auth, selection.goal_version_id)
            goal = ProjectionGoalVersion(
                account_id=view.account_id,
                version_id=view.id,
                content=view.content,
                content_digest=view.content_digest,
            )
        sources = self.sources.capture(
            session,
            auth,
            assumption.content.calibration_pins,
            snapshot_id=selection.initial.snapshot_id,
            retained_at=retained_at,
        )
        plan = preflight_projection(
            selection,
            ProjectionAssumptionVersion(
                account_id=assumption.account_id,
                version_id=assumption.id,
                content=assumption.content,
                content_digest=assumption.content_digest,
            ),
            goal_version=goal,
            snapshot=sources.snapshot,
        )
        stored = pack_projection_input(plan)
        size = (
            stored.capture_bytes
            + stored.input_bytes
            + sum(len(s.canonical_proof) for s in sources.sources)
        )
        if size > PROJECTION_MAX_BYTES:
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        auth.check(session, now=self._now())
        return CapturedProjectionInputs(plan=plan, sources=sources, stored=stored)

    def persist_capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
    ) -> pm.ProjectionRunModel:
        """Caller owns root command/capacity/job/outbox and must roll back any failure."""
        auth = self.authority(session, auth, write="run")
        projection_owner_lock(session, auth.owner_id)
        actual = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == root.id,
                PremiumRunModel.owner_id == auth.owner_id,
                PremiumRunModel.account_id == auth.account_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            actual is None
            or actual.kind != "projection"
            or actual.input_digest != captured.input_digest
            or actual.reserved_bytes != PROJECTION_MAX_BYTES
            or actual.expires_at <= self._now()
            or actual.expires_at > captured.expires_at
            or actual.created_at > self._now()
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        if (
            session.scalar(
                select(pm.ProjectionRunModel.id).where(pm.ProjectionRunModel.id == root.id)
            )
            is not None
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.CONFLICT)
        current = self.capture(
            session, auth, captured.plan.selection, retained_at=actual.created_at
        )
        if (
            current.plan != captured.plan
            or current.stored != captured.stored
            or tuple(
                (
                    s.header.kind,
                    s.header.subject_id,
                    s.header.content_digest,
                    s.quality,
                    s.canonical_proof,
                    s.header.license_version_ids,
                    s.header.retained_sources,
                )
                for s in current.sources.sources
            )
            != tuple(
                (
                    s.header.kind,
                    s.header.subject_id,
                    s.header.content_digest,
                    s.quality,
                    s.canonical_proof,
                    s.header.license_version_ids,
                    s.header.retained_sources,
                )
                for s in captured.sources.sources
            )
            or actual.expires_at > current.expires_at
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
        common = {
            "owner_id": auth.owner_id,
            "account_id": auth.account_id,
            "created_at": actual.created_at,
        }
        run = pm.ProjectionRunModel(
            id=actual.id,
            **common,
            **projection_run_header(current.plan, len(current.sources.sources)),
            sealed=False,
        )
        session.add(run)
        session.flush()
        input_rows = projection_input_rows(current.plan)
        for model, rows in input_rows.items():
            for ordinal, fields in enumerate(rows):
                values = dict(fields)
                if model is pm.ProjectionInputModel:
                    values.update(
                        canonical_capture=current.stored.canonical_capture,
                        canonical_input=current.stored.canonical_input,
                        capture_bytes=current.stored.capture_bytes,
                        input_bytes=current.stored.input_bytes,
                    )
                session.add(
                    model(
                        id=uuid5(run.id, f"{model.__tablename__}:{ordinal}"),
                        run_id=run.id,
                        **common,
                        **values,
                    )
                )
        license_rows = {}
        for identifier in current.sources.license_version_ids:
            license = self.sources._sources._license(session, auth.owner_id, identifier)
            license_row = PremiumRunLicenseModel(
                id=uuid5(run.id, f"license:{identifier}"),
                run_id=run.id,
                provider_id=UUID(license.provider_id),
                license_version_id=identifier,
                **common,
            )
            session.add(license_row)
            license_rows[identifier] = license_row
        session.flush()
        for source in current.sources.sources:
            header = source.header
            identifier = uuid5(run.id, f"source:{header.role}:{header.subject_id}")
            row = pm.ProjectionRunSourceModel(
                id=identifier,
                run_id=run.id,
                kind=header.role,
                subject_id=header.subject_id,
                content_digest=header.content_digest,
                original_created_at=header.original_created_at,
                source_expires_at=header.expires_at,
                quality=source.quality.value,
                proof_digest=source.proof_digest,
                proof_bytes=len(source.canonical_proof),
                **common,
            )
            session.add(row)
            session.flush()
            session.add(
                pm.ProjectionSourceProofModel(
                    id=uuid5(identifier, "proof"),
                    run_id=run.id,
                    source_id=identifier,
                    canonical_proof=source.canonical_proof,
                    **common,
                )
            )
            for license_id in header.license_version_ids:
                session.add(
                    pm.ProjectionSourceLicenseModel(
                        id=uuid5(identifier, f"license:{license_id}"),
                        run_id=run.id,
                        source_id=identifier,
                        run_license_id=license_rows[license_id].id,
                        **common,
                    )
                )
        memberships = retained_source_keys(tuple(s.header for s in current.sources.sources))
        for kind, identifier, original_at in memberships:
            session.add(
                pm.ProjectionRetainedSourceModel(
                    id=uuid5(run.id, f"retained-source:{kind}:{identifier}"),
                    run_id=run.id,
                    source_kind=kind,
                    source_id=identifier,
                    original_created_at=original_at,
                    **common,
                )
            )
        session.flush()
        # The root service owns queued work; every financial source is rechecked before sealing.
        _headers, deadline = self.sources.authorize_sources(
            session,
            auth,
            current.plan.assumption_version.content.calibration_pins,
            snapshot_id=current.plan.selection.initial.snapshot_id,
            retained_at=actual.created_at,
        )
        if retained_source_keys(_headers) != memberships:
            raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
        auth.check(session, now=self._now())
        if actual.expires_at > deadline or actual.expires_at <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        run.sealed = True
        session.flush()
        size = session.scalar(text("SELECT projection_storage_bytes(:run)"), {"run": run.id})
        if size is None or size > PROJECTION_MAX_BYTES:
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        # Active input bytes remain covered by the full run reservation.
        # Terminal job accounting converts that reservation to measured storage.
        session.flush()
        return run

    def read_retained_input(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> CapturedProjectionInputs:
        auth = self.authority(session, auth)
        projection_owner_lock(session, auth.owner_id)
        root = self._owned(session, auth, PremiumRunModel, run_id)
        run = self._owned(session, auth, pm.ProjectionRunModel, run_id)
        if (
            root.kind != "projection"
            or not run.sealed
            or root.expires_at <= self._now()
            or session.scalar(
                select(PremiumRetentionModel.id)
                .where(
                    PremiumRetentionModel.owner_id == auth.owner_id,
                    PremiumRetentionModel.run_id == run_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        headers = tuple(
            session.scalars(
                select(pm.ProjectionRunSourceModel)
                .where(
                    pm.ProjectionRunSourceModel.run_id == run.id,
                    pm.ProjectionRunSourceModel.owner_id == auth.owner_id,
                    pm.ProjectionRunSourceModel.account_id == auth.account_id,
                )
                .order_by(pm.ProjectionRunSourceModel.kind, pm.ProjectionRunSourceModel.subject_id)
                .limit(258)
            )
        )
        if len(headers) != run.source_count or len(headers) > 257:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        pins = tuple(
            ProjectionSourcePin(subject_id=str(h.subject_id), content_digest=h.content_digest)
            for h in headers
            if h.kind == "calibration"
        )
        # Check every retained license header, including corrupt/extra links, before
        # any original source or retained input financial fields are materialized.
        authorized, deadline = self.sources.authorize_sources(
            session, auth, pins, snapshot_id=run.snapshot_id, retained_at=root.created_at
        )
        verify_retained_source_keys(session, auth, run.id, authorized)
        expected_headers = {(str(h.role), h.subject_id): h for h in authorized}
        if len(expected_headers) != len(headers) or any(
            (expected := expected_headers.get((h.kind, h.subject_id))) is None
            or expected.content_digest != h.content_digest
            or expected.original_created_at != h.original_created_at
            or h.source_expires_at <= self._now()
            for h in headers
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        license_rows = tuple(
            session.scalars(
                select(PremiumRunLicenseModel)
                .where(
                    PremiumRunLicenseModel.run_id == run.id,
                    PremiumRunLicenseModel.owner_id == auth.owner_id,
                    PremiumRunLicenseModel.account_id == auth.account_id,
                )
                .limit(8193)
            )
        )
        if len(license_rows) > 8192:
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        for license_row in license_rows:
            self.sources._license(session, auth, license_row.license_version_id, root.created_at)
            pinned = self.sources._sources._license(
                session, auth.owner_id, license_row.license_version_id
            )
            if str(license_row.provider_id) != pinned.provider_id:
                raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        expected_licenses = {identifier for h in authorized for identifier in h.license_version_ids}
        if (
            len(license_rows) != len(expected_licenses)
            or {row.license_version_id for row in license_rows} != expected_licenses
            or root.expires_at > deadline
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        # Sources and original lifetimes precede normalized amounts and both private BYTEA parts.
        current_sources = self.sources.capture(
            session, auth, pins, snapshot_id=run.snapshot_id, retained_at=root.created_at
        )
        if root.expires_at > current_sources.expires_at:
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        stored = session.scalar(
            select(pm.ProjectionInputModel)
            .where(
                pm.ProjectionInputModel.run_id == run.id,
                pm.ProjectionInputModel.owner_id == auth.owner_id,
                pm.ProjectionInputModel.account_id == auth.account_id,
            )
            .options(
                undefer(pm.ProjectionInputModel.canonical_capture),
                undefer(pm.ProjectionInputModel.canonical_input),
            )
        )
        if stored is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        record = ProjectionInputBytes(
            canonical_capture=stored.canonical_capture,
            canonical_input=stored.canonical_input,
            capture_bytes=stored.capture_bytes,
            input_bytes=stored.input_bytes,
        )
        try:
            plan = unpack_projection_input(
                record,
                expected=ProjectionCaptureBinding(
                    account_id=auth.account_id,
                    assumption_version_id=run.assumption_version_id,
                    goal_version_id=run.goal_version_id,
                    capture_digest=root.input_digest,
                    numerical_input_digest=run.numerical_input_digest,
                ),
            )
        except ProjectionCodecError:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE) from None
        captured = self.capture(session, auth, plan.selection, retained_at=root.created_at)
        if (
            captured.plan != plan
            or captured.stored != record
            or any(
                getattr(run, key) != value
                for key, value in projection_run_header(plan, len(current_sources.sources)).items()
            )
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        for model, expected_rows in projection_input_rows(plan).items():
            actual = tuple(
                session.scalars(
                    select(model)
                    .where(
                        model.run_id == run.id,
                        model.owner_id == auth.owner_id,
                        model.account_id == auth.account_id,
                    )
                    .limit(len(expected_rows) + 1)
                )
            )
            keys = tuple(expected_rows[0]) if expected_rows else ()
            original_rows = sorted(
                canonical_json({key: getattr(row, key) for key in keys}) for row in actual
            )
            if len(actual) != len(expected_rows) or original_rows != sorted(
                canonical_json(fields) for fields in expected_rows
            ):
                raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        self._reconcile_sources(session, auth, run, headers, current_sources)
        _headers, deadline = self.sources.authorize_sources(
            session,
            auth,
            plan.assumption_version.content.calibration_pins,
            snapshot_id=run.snapshot_id,
            retained_at=root.created_at,
        )
        if root.expires_at > deadline or root.expires_at <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        auth.check(session, now=self._now())
        return captured

    def _reconcile_sources(
        self,
        session: Session,
        auth: ReportAuthorization,
        run: pm.ProjectionRunModel,
        headers: tuple[pm.ProjectionRunSourceModel, ...],
        sources: ProjectionSourceBundle,
    ) -> None:
        expected = {(str(s.header.role), s.header.subject_id): s for s in sources.sources}
        if len(expected) != len(headers):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        actual_licenses = tuple(
            session.scalars(
                select(PremiumRunLicenseModel)
                .where(
                    PremiumRunLicenseModel.run_id == run.id,
                    PremiumRunLicenseModel.owner_id == auth.owner_id,
                    PremiumRunLicenseModel.account_id == auth.account_id,
                )
                .limit(8193)
            )
        )
        if {row.license_version_id for row in actual_licenses} != set(
            sources.license_version_ids
        ) or len(actual_licenses) != len(sources.license_version_ids):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        license_ids = {row.license_version_id: row.id for row in actual_licenses}
        for row in headers:
            source = expected.get((row.kind, row.subject_id))
            if (
                source is None
                or row.content_digest != source.header.content_digest
                or row.original_created_at != source.header.original_created_at
                or row.quality != source.quality.value
                or row.proof_digest != source.proof_digest
                or row.proof_bytes != len(source.canonical_proof)
            ):
                raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
            payload = session.scalar(
                select(pm.ProjectionSourceProofModel.canonical_proof).where(
                    pm.ProjectionSourceProofModel.source_id == row.id,
                    pm.ProjectionSourceProofModel.run_id == run.id,
                    pm.ProjectionSourceProofModel.owner_id == auth.owner_id,
                    pm.ProjectionSourceProofModel.account_id == auth.account_id,
                )
            )
            links = tuple(
                session.scalars(
                    select(pm.ProjectionSourceLicenseModel.run_license_id)
                    .where(
                        pm.ProjectionSourceLicenseModel.source_id == row.id,
                        pm.ProjectionSourceLicenseModel.run_id == run.id,
                        pm.ProjectionSourceLicenseModel.owner_id == auth.owner_id,
                        pm.ProjectionSourceLicenseModel.account_id == auth.account_id,
                    )
                    .limit(8193)
                )
            )
            if (
                payload != source.canonical_proof
                or set(links) != {license_ids[i] for i in source.header.license_version_ids}
                or len(links) != len(source.header.license_version_ids)
            ):
                raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
