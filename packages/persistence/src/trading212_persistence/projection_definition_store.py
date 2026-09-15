"""Immutable projection/goal definitions under current durable account authority.

Methods participate in their caller's transaction; none commit, dispatch, or fetch
provider data. The resolver is a server-owned metadata boundary and must authorize
original source identities/lifetimes and pinned/current rights without decoding
financial payloads. Unsupported calibration identities fail closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics._premium_numeric import semidefinite_factor
from trading212_application import projection as app
from trading212_application.projection_capture import (
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionGoalVersionContent,
    projection_definition_digest,
)
from trading212_application.projection_views import (
    AssumptionSetView,
    AssumptionVersionView,
    GoalVersionView,
    GoalView,
    ProjectionVersionMetadata,
)
from trading212_domain.errors import DomainError
from trading212_domain.projection import ProjectionAsset, ProjectionAssumptions, ProjectionSourcePin
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode, Money, require_utc
from trading212_security.principals import Scope

from .premium_models import (
    PremiumAuditModel,
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOwned,
    PremiumRunModel,
)
from .projection_models import (
    AssumptionSetModel,
    AssumptionVersionModel,
    GoalModel,
    GoalVersionModel,
    ProjectionAssumptionAssetModel,
    ProjectionCalibrationPinModel,
    ProjectionCorrelationCellModel,
    ProjectionGoalPauseModel,
    ProjectionGoalScheduleEntryModel,
)
from .report_authorization import ReportAuthorization
from .report_models import ApplicationCommandIdentityModel
from .risk_models import RiskVersionModel
from .scenario_models import ScenarioVersionModel

READ_SCOPES = frozenset((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ))
ProjectionDefinitionCommand = Literal[
    "projection.assumption.create.v1",
    "projection.assumption.version.create.v1",
    "projection.goal.create.v1",
    "projection.goal.version.create.v1",
]


@dataclass(slots=True)
class ProjectionStorageError(Exception):
    code: app.ProjectionErrorCode

    def __str__(self) -> str:
        return "The projection operation cannot be completed."


class ProjectionCalibrationResolver(Protocol):
    def __call__(
        self,
        session: Session,
        authorization: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        use: SourceUse,
        now: datetime,
    ) -> None:
        """Authorize exact existing source metadata; never derive authority from caller labels."""
        ...


def projection_owner_lock(session: Session, owner: UUID) -> None:
    # Same lock order as source cleanup and every other premium family.
    for namespace in ("sources", "xray", "historical", "premium"):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )


def projection_definition_command_digest(
    command: ProjectionDefinitionCommand,
    account_id: UUID,
    metadata: ProjectionVersionMetadata,
    content: ProjectionAssumptions | ProjectionGoalVersionContent,
    *,
    aggregate_id: UUID | None = None,
    expected_revision: int | None = None,
) -> str:
    """Bind complete semantic content and immutable labels; exclude tracing/retry metadata."""
    return sha256(
        ("t212pi.command." + command).encode("ascii")
        + b"\0"
        + canonical_json((account_id, aggregate_id, expected_revision, metadata, content)).encode(
            "utf-8"
        )
    ).hexdigest()


class ProjectionDefinitionStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        calibration_resolver: ProjectionCalibrationResolver | None = None,
    ) -> None:
        self._sessions = sessions
        self._cursor_key = cursor_signing_key
        self._clock = clock or (lambda: datetime.now(UTC))
        self._calibration_resolver = calibration_resolver

    def _now(self) -> datetime:
        return require_utc(self._clock())

    def authority(
        self,
        session: Session,
        auth: ReportAuthorization,
        *,
        write: Literal["assumption", "goal", "run"] | None = None,
    ) -> ReportAuthorization:
        scopes = READ_SCOPES
        if write == "goal":
            scopes = scopes | {Scope.GOALS_WRITE}
        elif write in ("assumption", "run"):
            scopes = scopes | {Scope.PROJECTIONS_WRITE}
        current = replace(auth, required_scopes=auth.required_scopes | scopes)
        current.check(session, now=self._now())
        return current

    def _owned[M: PremiumOwned](
        self, session: Session, auth: ReportAuthorization, model: type[M], identifier: UUID
    ) -> M:
        if type(identifier) is not UUID:
            raise ProjectionStorageError(app.ProjectionErrorCode.VALIDATION_FAILED)
        row = session.scalar(
            select(model)
            .where(
                model.id == identifier,
                model.owner_id == auth.owner_id,
                model.account_id == auth.account_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.NOT_FOUND)
        return row

    def _permit(
        self,
        session: Session,
        auth: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        write: bool = False,
    ) -> None:
        auth.check(session, now=self._now())
        if pins:
            if self._calibration_resolver is None:
                raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
            # Reads check STORE too: a later copy/read cannot revive a forbidden retained source.
            self._calibration_resolver(session, auth, pins, use=SourceUse.STORE, now=self._now())
            self._calibration_resolver(session, auth, pins, use=SourceUse.DISPLAY, now=self._now())
        auth.check(session, now=self._now())

    def _assumption_pins(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> tuple[ProjectionSourcePin, ...]:
        # Only identity/count metadata is selected before source authorization. In
        # particular, means, volatility, correlation and currency are not decoded.
        metadata = session.execute(
            select(AssumptionVersionModel.calibration_count, AssumptionVersionModel.sealed).where(
                AssumptionVersionModel.id == identifier,
                AssumptionVersionModel.owner_id == auth.owner_id,
                AssumptionVersionModel.account_id == auth.account_id,
            )
        ).one_or_none()
        if metadata is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.NOT_FOUND)
        rows = tuple(
            session.execute(
                select(
                    ProjectionCalibrationPinModel.subject_id,
                    ProjectionCalibrationPinModel.content_digest,
                )
                .where(
                    ProjectionCalibrationPinModel.version_id == identifier,
                    ProjectionCalibrationPinModel.owner_id == auth.owner_id,
                    ProjectionCalibrationPinModel.account_id == auth.account_id,
                )
                .order_by(ProjectionCalibrationPinModel.subject_id)
                .limit(257)
            )
        )
        if not metadata.sealed or len(rows) != metadata.calibration_count or len(rows) > 256:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        pins = tuple(
            ProjectionSourcePin(subject_id=str(row.subject_id), content_digest=row.content_digest)
            for row in rows
        )
        self._permit(session, auth, pins)
        return pins

    def read_assumption_version(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> AssumptionVersionView:
        auth = self.authority(session, auth)
        pins = self._assumption_pins(session, auth, identifier)
        row = self._owned(session, auth, AssumptionVersionModel, identifier)
        assets = tuple(
            session.scalars(
                select(ProjectionAssumptionAssetModel)
                .where(
                    ProjectionAssumptionAssetModel.version_id == row.id,
                    ProjectionAssumptionAssetModel.owner_id == auth.owner_id,
                    ProjectionAssumptionAssetModel.account_id == auth.account_id,
                )
                .order_by(ProjectionAssumptionAssetModel.asset_index)
                .limit(13)
            )
        )
        cells = tuple(
            session.scalars(
                select(ProjectionCorrelationCellModel)
                .where(
                    ProjectionCorrelationCellModel.version_id == row.id,
                    ProjectionCorrelationCellModel.owner_id == auth.owner_id,
                    ProjectionCorrelationCellModel.account_id == auth.account_id,
                )
                .order_by(
                    ProjectionCorrelationCellModel.row_index,
                    ProjectionCorrelationCellModel.column_index,
                )
                .limit(145)
            )
        )
        n = row.asset_count
        if (
            not row.sealed
            or not 1 <= n <= 12
            or len(assets) != n
            or len(cells) != n * n
            or tuple(a.asset_index for a in assets) != tuple(range(n))
            or tuple((c.row_index, c.column_index) for c in cells)
            != tuple((i, j) for i in range(n) for j in range(n))
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        try:
            content = ProjectionAssumptions(
                assets=tuple(
                    ProjectionAsset(
                        key=a.asset_key,
                        annual_mean_log_return=a.annual_mean_log_return,
                        annual_volatility=a.annual_volatility,
                        weight=a.weight,
                    )
                    for a in assets
                ),
                correlation=tuple(
                    tuple(cells[i * n + j].value for j in range(n)) for i in range(n)
                ),
                reporting_currency=CurrencyCode(row.reporting_currency),
                annual_inflation=row.annual_inflation,
                annual_fee=row.annual_fee,
                annual_tax_drag=row.annual_tax_drag,
                rebalance=cast(Literal["monthly", "annual", "none"], row.rebalance),
                calibration_pins=pins,
            )
            semidefinite_factor(content.correlation)
            metadata = ProjectionVersionMetadata(name=row.name, description=row.description)
            if (
                tuple(a.key for a in content.assets) != tuple(a.asset_key for a in assets)
                or projection_definition_digest(content) != row.content_digest
            ):
                raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        except DomainError:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE) from None
        self._permit(session, auth, pins)
        return AssumptionVersionView(
            id=row.id,
            account_id=row.account_id,
            set_id=row.set_id,
            version_number=row.version_number,
            predecessor_id=row.predecessor_id,
            metadata=metadata,
            content=content,
            content_digest=row.content_digest,
            created_at=row.created_at,
        )

    def read_goal_version(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> GoalVersionView:
        auth = self.authority(session, auth)
        assumption_id = session.scalar(
            select(GoalVersionModel.assumption_version_id).where(
                GoalVersionModel.id == identifier,
                GoalVersionModel.owner_id == auth.owner_id,
                GoalVersionModel.account_id == auth.account_id,
            )
        )
        if assumption_id is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.NOT_FOUND)
        pins = self._assumption_pins(session, auth, assumption_id)
        row = self._owned(session, auth, GoalVersionModel, identifier)
        pauses = tuple(
            session.scalars(
                select(ProjectionGoalPauseModel.on)
                .where(
                    ProjectionGoalPauseModel.version_id == row.id,
                    ProjectionGoalPauseModel.owner_id == auth.owner_id,
                    ProjectionGoalPauseModel.account_id == auth.account_id,
                )
                .order_by(ProjectionGoalPauseModel.on)
                .limit(129)
            )
        )
        entries = tuple(
            session.scalars(
                select(ProjectionGoalScheduleEntryModel)
                .where(
                    ProjectionGoalScheduleEntryModel.version_id == row.id,
                    ProjectionGoalScheduleEntryModel.owner_id == auth.owner_id,
                    ProjectionGoalScheduleEntryModel.account_id == auth.account_id,
                )
                .order_by(
                    ProjectionGoalScheduleEntryModel.on,
                    ProjectionGoalScheduleEntryModel.kind,
                    ProjectionGoalScheduleEntryModel.entry_key,
                )
                .limit(129)
            )
        )
        if (
            not row.sealed
            or len(pauses) != row.pause_count
            or len(entries) != row.entry_count
            or len(pauses) + len(entries) > 128
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        try:
            currency = CurrencyCode(row.reporting_currency)
            content = ProjectionGoalVersionContent(
                assumption_version_id=row.assumption_version_id,
                target=Money(row.target, currency),
                target_date=row.target_date,
                months=row.months,
                basis=cast(Literal["nominal", "real"], row.basis),
                probability_objective=row.probability_objective,
                schedule=ProjectionDatedSchedule(
                    base_monthly=Money(row.base_monthly, currency),
                    annual_growth=row.annual_growth,
                    paused_dates=pauses,
                    entries=tuple(
                        ProjectionDatedEntry(
                            key=e.entry_key,
                            on=e.on,
                            kind=cast(Literal["lump_sum", "withdrawal"], e.kind),
                            value=Money(e.value, currency),
                        )
                        for e in entries
                    ),
                ),
            )
            metadata = ProjectionVersionMetadata(name=row.name, description=row.description)
            if projection_definition_digest(content) != row.content_digest:
                raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        except DomainError:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE) from None
        self._permit(session, auth, pins)
        return GoalVersionView(
            id=row.id,
            account_id=row.account_id,
            goal_id=row.goal_id,
            version_number=row.version_number,
            predecessor_id=row.predecessor_id,
            metadata=metadata,
            content=content,
            content_digest=row.content_digest,
            created_at=row.created_at,
        )

    def read_assumption_set(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> AssumptionSetView:
        auth = self.authority(session, auth)
        row = self._owned(session, auth, AssumptionSetModel, identifier)
        current = session.scalar(
            select(AssumptionVersionModel.id).where(
                AssumptionVersionModel.set_id == row.id,
                AssumptionVersionModel.version_number == row.revision,
                AssumptionVersionModel.owner_id == auth.owner_id,
                AssumptionVersionModel.account_id == auth.account_id,
                AssumptionVersionModel.sealed.is_(True),
            )
        )
        if current is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        self._assumption_pins(session, auth, current)
        auth.check(session, now=self._now())
        return AssumptionSetView(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            revision=row.revision,
            current_version_id=current,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def read_goal(self, session: Session, auth: ReportAuthorization, identifier: UUID) -> GoalView:
        auth = self.authority(session, auth)
        row = self._owned(session, auth, GoalModel, identifier)
        current = session.execute(
            select(GoalVersionModel.id, GoalVersionModel.assumption_version_id).where(
                GoalVersionModel.goal_id == row.id,
                GoalVersionModel.version_number == row.revision,
                GoalVersionModel.owner_id == auth.owner_id,
                GoalVersionModel.account_id == auth.account_id,
                GoalVersionModel.sealed.is_(True),
            )
        ).one_or_none()
        if current is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        self._assumption_pins(session, auth, current.assumption_version_id)
        auth.check(session, now=self._now())
        return GoalView(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            revision=row.revision,
            current_version_id=current.id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def capacity(self, session: Session, auth: ReportAuthorization) -> PremiumCapacityModel:
        session.execute(
            insert(PremiumCapacityModel)
            .values(
                owner_id=auth.owner_id,
                reserved_bytes=0,
                retained_bytes=0,
                active_jobs=0,
                definition_versions=0,
                updated_at=self._now(),
            )
            .on_conflict_do_nothing(index_elements=["owner_id"])
        )
        row = session.scalar(
            select(PremiumCapacityModel)
            .where(PremiumCapacityModel.owner_id == auth.owner_id)
            .with_for_update()
        )
        if row is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        return row

    def reserve_run_capacity(self, session: Session, auth: ReportAuthorization) -> None:
        """Reserve one shared job/32 MiB; caller atomically publishes input/job/outbox."""
        auth = self.authority(session, auth, write="run")
        projection_owner_lock(session, auth.owner_id)
        capacity = self.capacity(session, auth)
        active = (
            session.scalar(
                select(func.count())
                .select_from(PremiumJobModel)
                .where(
                    PremiumJobModel.owner_id == auth.owner_id,
                    PremiumJobModel.state.in_(("queued", "running")),
                )
            )
            or 0
        )
        actual = (
            session.scalar(
                select(
                    func.coalesce(
                        func.sum(PremiumRunModel.reserved_bytes + PremiumRunModel.retained_bytes), 0
                    )
                ).where(PremiumRunModel.owner_id == auth.owner_id)
            )
            or 0
        )
        if (
            max(active, capacity.active_jobs) >= 2
            or max(actual, capacity.reserved_bytes + capacity.retained_bytes) + 33554432 > 268435456
        ):
            raise ProjectionStorageError(app.ProjectionErrorCode.RATE_LIMITED)
        capacity.active_jobs += 1
        capacity.reserved_bytes += 33554432
        capacity.updated_at = self._now()
        session.flush()

    def _version_capacity(self, session: Session, auth: ReportAuthorization) -> None:
        capacity = self.capacity(session, auth)
        count = sum(
            session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == auth.owner_id)
            )
            or 0
            for model in (
                RiskVersionModel,
                ScenarioVersionModel,
                AssumptionVersionModel,
                GoalVersionModel,
            )
        )
        if max(count, capacity.definition_versions) >= 512:
            raise ProjectionStorageError(app.ProjectionErrorCode.RATE_LIMITED)
        capacity.definition_versions += 1
        capacity.updated_at = self._now()
        session.flush()

    def prior_command(
        self, session: Session, auth: ReportAuthorization, command: str, key: str, digest: str
    ) -> ApplicationCommandIdentityModel | None:
        row = session.scalar(
            select(ApplicationCommandIdentityModel).where(
                ApplicationCommandIdentityModel.owner_id == auth.owner_id,
                ApplicationCommandIdentityModel.command == command,
                ApplicationCommandIdentityModel.idempotency_key == key,
            )
        )
        if row is not None and (row.account_id != auth.account_id or row.command_digest != digest):
            raise ProjectionStorageError(app.ProjectionErrorCode.CONFLICT)
        return row

    def _audit(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: ProjectionDefinitionCommand,
        request: app.ProjectionCommand,
        digest: str,
        resource: UUID,
    ) -> None:
        at = self._now()
        identity = ApplicationCommandIdentityModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            command=command,
            idempotency_key=request.idempotency_key,
            command_digest=digest,
            premium_resource_id=resource,
            premium_actor_id=auth.principal_id,
            premium_correlation_id=request.correlation_id,
            report_job_id=None,
            export_job_id=None,
            created_at=at,
        )
        session.add(identity)
        session.flush()
        session.add(
            PremiumAuditModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                command_id=identity.id,
                kind="created",
                created_at=at,
            )
        )
        session.flush()

    def _new_assumption_version(
        self,
        session: Session,
        auth: ReportAuthorization,
        head: AssumptionSetModel,
        metadata: ProjectionVersionMetadata,
        content: ProjectionAssumptions,
        predecessor: UUID | None,
    ) -> AssumptionVersionModel:
        self._version_capacity(session, auth)
        row = AssumptionVersionModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            set_id=head.id,
            version_number=head.revision,
            predecessor_id=predecessor,
            name=metadata.name,
            description=metadata.description,
            content_digest=projection_definition_digest(content),
            sealed=False,
            reporting_currency=content.reporting_currency.value,
            annual_inflation=content.annual_inflation,
            annual_fee=content.annual_fee,
            annual_tax_drag=content.annual_tax_drag,
            rebalance=content.rebalance,
            asset_count=len(content.assets),
            calibration_count=len(content.calibration_pins),
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        for i, a in enumerate(content.assets):
            session.add(
                ProjectionAssumptionAssetModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    version_id=row.id,
                    asset_index=i,
                    asset_key=a.key,
                    annual_mean_log_return=a.annual_mean_log_return,
                    annual_volatility=a.annual_volatility,
                    weight=a.weight,
                    created_at=self._now(),
                )
            )
        session.flush()
        for i, values in enumerate(content.correlation):
            for j, value in enumerate(values):
                session.add(
                    ProjectionCorrelationCellModel(
                        id=uuid4(),
                        owner_id=auth.owner_id,
                        account_id=auth.account_id,
                        version_id=row.id,
                        row_index=i,
                        column_index=j,
                        value=value,
                        created_at=self._now(),
                    )
                )
        for pin in content.calibration_pins:
            session.add(
                ProjectionCalibrationPinModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    version_id=row.id,
                    subject_id=UUID(pin.subject_id),
                    content_digest=pin.content_digest,
                    created_at=self._now(),
                )
            )
        session.flush()
        row.sealed = True
        session.flush()
        return row

    def _new_goal_version(
        self,
        session: Session,
        auth: ReportAuthorization,
        head: GoalModel,
        metadata: ProjectionVersionMetadata,
        content: ProjectionGoalVersionContent,
        predecessor: UUID | None,
    ) -> GoalVersionModel:
        self._version_capacity(session, auth)
        row = GoalVersionModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            goal_id=head.id,
            version_number=head.revision,
            predecessor_id=predecessor,
            name=metadata.name,
            description=metadata.description,
            content_digest=projection_definition_digest(content),
            sealed=False,
            assumption_version_id=content.assumption_version_id,
            reporting_currency=content.target.currency.value,
            target=content.target.amount,
            target_date=content.target_date,
            months=content.months,
            basis=content.basis,
            probability_objective=content.probability_objective,
            base_monthly=content.schedule.base_monthly.amount,
            annual_growth=content.schedule.annual_growth,
            pause_count=len(content.schedule.paused_dates),
            entry_count=len(content.schedule.entries),
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        for on in content.schedule.paused_dates:
            session.add(
                ProjectionGoalPauseModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    version_id=row.id,
                    on=on,
                    created_at=self._now(),
                )
            )
        for e in content.schedule.entries:
            session.add(
                ProjectionGoalScheduleEntryModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    version_id=row.id,
                    entry_key=e.key,
                    on=e.on,
                    kind=e.kind,
                    value=e.value.amount,
                    created_at=self._now(),
                )
            )
        session.flush()
        row.sealed = True
        session.flush()
        return row

    def publish_assumption_set(
        self, session: Session, auth: ReportAuthorization, request: app.CreateAssumptionSet
    ) -> AssumptionSetView:
        auth = self.authority(session, auth, write="assumption")
        if request.account_id != auth.account_id:
            raise ProjectionStorageError(app.ProjectionErrorCode.NOT_FOUND)
        projection_owner_lock(session, auth.owner_id)
        command: ProjectionDefinitionCommand = "projection.assumption.create.v1"
        digest = projection_definition_command_digest(
            command, auth.account_id, request.metadata, request.content
        )
        prior = self.prior_command(session, auth, command, request.idempotency_key, digest)
        if prior is not None:
            return self.read_assumption_set(session, auth, cast(UUID, prior.premium_resource_id))
        self._permit(session, auth, request.content.calibration_pins, write=True)
        self.capacity(session, auth)
        head = AssumptionSetModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            name=request.metadata.name,
            revision=1,
            created_at=self._now(),
            updated_at=self._now(),
        )
        session.add(head)
        session.flush()
        self._new_assumption_version(session, auth, head, request.metadata, request.content, None)
        self._audit(session, auth, command, request, digest, head.id)
        self._permit(session, auth, request.content.calibration_pins, write=True)
        return self.read_assumption_set(session, auth, head.id)

    def publish_assumption_version(
        self, session: Session, auth: ReportAuthorization, request: app.CreateAssumptionVersion
    ) -> AssumptionVersionView:
        auth = self.authority(session, auth, write="assumption")
        projection_owner_lock(session, auth.owner_id)
        command: ProjectionDefinitionCommand = "projection.assumption.version.create.v1"
        digest = projection_definition_command_digest(
            command,
            auth.account_id,
            request.metadata,
            request.content,
            aggregate_id=request.set_id,
            expected_revision=request.expected_revision,
        )
        prior = self.prior_command(session, auth, command, request.idempotency_key, digest)
        if prior is not None:
            return self.read_assumption_version(
                session, auth, cast(UUID, prior.premium_resource_id)
            )
        self._permit(session, auth, request.content.calibration_pins, write=True)
        head = self._owned(session, auth, AssumptionSetModel, request.set_id)
        if head.revision != request.expected_revision or head.revision >= 512:
            raise ProjectionStorageError(app.ProjectionErrorCode.REVISION_MISMATCH)
        previous = session.scalar(
            select(AssumptionVersionModel.id).where(
                AssumptionVersionModel.set_id == head.id,
                AssumptionVersionModel.version_number == head.revision,
                AssumptionVersionModel.sealed.is_(True),
            )
        )
        if previous is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        head.revision += 1
        head.name = request.metadata.name
        head.updated_at = self._now()
        row = self._new_assumption_version(
            session, auth, head, request.metadata, request.content, previous
        )
        self._audit(session, auth, command, request, digest, row.id)
        self._permit(session, auth, request.content.calibration_pins, write=True)
        return self.read_assumption_version(session, auth, row.id)

    def _goal_basis(
        self, session: Session, auth: ReportAuthorization, content: ProjectionGoalVersionContent
    ) -> tuple[ProjectionSourcePin, ...]:
        assumptions = self.read_assumption_version(session, auth, content.assumption_version_id)
        if content.target.currency != assumptions.content.reporting_currency:
            raise ProjectionStorageError(app.ProjectionErrorCode.VALIDATION_FAILED)
        return assumptions.content.calibration_pins

    def publish_goal(
        self, session: Session, auth: ReportAuthorization, request: app.CreateGoal
    ) -> GoalView:
        auth = self.authority(session, auth, write="goal")
        if request.account_id != auth.account_id:
            raise ProjectionStorageError(app.ProjectionErrorCode.NOT_FOUND)
        projection_owner_lock(session, auth.owner_id)
        command: ProjectionDefinitionCommand = "projection.goal.create.v1"
        digest = projection_definition_command_digest(
            command, auth.account_id, request.metadata, request.content
        )
        prior = self.prior_command(session, auth, command, request.idempotency_key, digest)
        if prior is not None:
            return self.read_goal(session, auth, cast(UUID, prior.premium_resource_id))
        pins = self._goal_basis(session, auth, request.content)
        self.capacity(session, auth)
        head = GoalModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            name=request.metadata.name,
            revision=1,
            created_at=self._now(),
            updated_at=self._now(),
        )
        session.add(head)
        session.flush()
        self._new_goal_version(session, auth, head, request.metadata, request.content, None)
        self._audit(session, auth, command, request, digest, head.id)
        self._permit(session, auth, pins, write=True)
        return self.read_goal(session, auth, head.id)

    def publish_goal_version(
        self, session: Session, auth: ReportAuthorization, request: app.CreateGoalVersion
    ) -> GoalVersionView:
        auth = self.authority(session, auth, write="goal")
        projection_owner_lock(session, auth.owner_id)
        command: ProjectionDefinitionCommand = "projection.goal.version.create.v1"
        digest = projection_definition_command_digest(
            command,
            auth.account_id,
            request.metadata,
            request.content,
            aggregate_id=request.goal_id,
            expected_revision=request.expected_revision,
        )
        prior = self.prior_command(session, auth, command, request.idempotency_key, digest)
        if prior is not None:
            return self.read_goal_version(session, auth, cast(UUID, prior.premium_resource_id))
        pins = self._goal_basis(session, auth, request.content)
        head = self._owned(session, auth, GoalModel, request.goal_id)
        if head.revision != request.expected_revision or head.revision >= 512:
            raise ProjectionStorageError(app.ProjectionErrorCode.REVISION_MISMATCH)
        previous = session.scalar(
            select(GoalVersionModel.id).where(
                GoalVersionModel.goal_id == head.id,
                GoalVersionModel.version_number == head.revision,
                GoalVersionModel.sealed.is_(True),
            )
        )
        if previous is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        head.revision += 1
        head.name = request.metadata.name
        head.updated_at = self._now()
        row = self._new_goal_version(
            session, auth, head, request.metadata, request.content, previous
        )
        self._audit(session, auth, command, request, digest, row.id)
        self._permit(session, auth, pins, write=True)
        return self.read_goal_version(session, auth, row.id)
