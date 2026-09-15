"""Private complete saved-input capture; source authorization always precedes decode."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.scenario import validate_scenario_capacity
from trading212_application import historical as historical_app
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.historical import HistoricalInput
from trading212_domain.scenario import ScenarioFactorShock, ScenarioRateShock
from trading212_domain.scenario_execution import (
    ScenarioExecutionInput,
    ScenarioInputPins,
    ScenarioReplayInput,
    ScenarioReplaySelection,
)
from trading212_domain.scenario_serialization import scenario_input_digest
from trading212_domain.sources import SourceLicense, SourceUse
from trading212_domain.xray import XrayInput
from trading212_domain.xray_codec import decode_xray_input
from trading212_domain.xray_result import XrayCalculation
from trading212_security.principals import Scope

from .historical_capture import HistoricalCaptureStore
from .historical_models import HistoricalInputModel
from .premium_models import PremiumRunModel
from .report_authorization import ReportAuthorization
from .scenario_definition_store import ScenarioDefinitionStore
from .scenario_input_codec import pack_scenario_input
from .scenario_models import ScenarioRunModel
from .scenario_source_store import ScenarioCopySources
from .scenario_store_types import (
    CapturedScenarioInputs,
    ScenarioCaptureSelection,
    ScenarioStorageError,
)
from .scenario_store_types import ScenarioStorageErrorCode as Code
from .xray_run_models import XrayInputDependencyModel
from .xray_run_store import _SOURCE_TARGETS, XrayRunStore

ScenarioReplayResolver = Callable[
    [ScenarioReplaySelection, HistoricalInput, XrayInput, XrayCalculation], ScenarioReplayInput
]


class ScenarioCopyXray(XrayRunStore):
    copy_sources: ScenarioCopySources

    def _permit(
        self, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> SourceLicense:
        return self.copy_sources._permit(session, owner, license_id, use)


class ScenarioInputStore(ScenarioDefinitionStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        replay_resolver: ScenarioReplayResolver | None = None,
    ) -> None:
        super().__init__(sessions, cursor_signing_key=cursor_signing_key, clock=clock)
        self._replay_resolver = replay_resolver

    def capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        selection: ScenarioCaptureSelection,
        *,
        retained_at: datetime | None = None,
        required_copy_use: SourceUse | None = None,
    ) -> CapturedScenarioInputs:
        """Capture owned immutable saved parents; never resolve a latest financial version."""
        if type(selection) is not ScenarioCaptureSelection:
            raise ScenarioStorageError(Code.VALIDATION_FAILED)
        auth = self.authority(session, auth)
        try:
            return self._capture(
                session,
                auth,
                selection,
                retained_at=retained_at,
                required_copy_use=required_copy_use,
            )
        except (
            historical_app.HistoricalServiceError,
            source_app.SourceServiceError,
            xray_app.XrayServiceError,
        ):
            raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE) from None
        except DomainError as error:
            code = (
                Code.INPUT_BOUND_EXCEEDED
                if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                else Code.SCENARIO_UNAVAILABLE
            )
            raise ScenarioStorageError(code) from None

    def _capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        selection: ScenarioCaptureSelection,
        *,
        retained_at: datetime | None,
        required_copy_use: SourceUse | None,
    ) -> CapturedScenarioInputs:
        version = self.read_version(session, auth, selection.scenario_version_id)
        sources = self.copy_authority(retained_at=retained_at, required_copy_use=required_copy_use)
        history = None
        if selection.replay is not None:
            # Scope elevation uses owned metadata only, before any saved financial parent bytes.
            header = session.execute(
                select(
                    HistoricalInputModel.id,
                    HistoricalInputModel.target_version_id,
                    HistoricalInputModel.sealed,
                ).where(
                    HistoricalInputModel.id == selection.replay.historical_input_snapshot_id,
                    HistoricalInputModel.owner_id == auth.owner_id,
                    HistoricalInputModel.broker_account_id == auth.account_id,
                )
            ).one_or_none()
            if header is None or not header.sealed:
                raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
            scopes = {Scope.ACTIVITY_READ}
            if header.target_version_id is not None:
                scopes.add(Scope.TARGETS_READ)
            auth = replace(auth, required_scopes=auth.required_scopes | scopes)
            auth.check(session, now=self._now())
            if self._replay_resolver is None:
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
            history = self._history(session, auth, header.id, sources)
        store = ScenarioCopyXray(
            sessions=self._sessions, cursor_signing_key=self._cursor_key, clock=self._clock
        )
        store.copy_sources = sources
        principal = auth.as_principal(now=self._now())
        handle = store._authorize_xray_run(
            session, principal, auth.account_id, selection.xray_run_id
        )
        # Check all request pins before selecting the complete retained proof.
        if (
            handle.context.snapshot_id != str(selection.portfolio_snapshot_id)
            or handle.context.reporting_currency != selection.reporting_currency
            or handle.context.source_cutoff_at != selection.source_cutoff_at
        ):
            raise ScenarioStorageError(Code.CONFLICT)
        result = store._load_xray_result(session, principal, auth.account_id, handle)
        _, capture, _ = store._authorized_rows(
            session, principal, auth.account_id, selection.xray_run_id
        )
        source = decode_xray_input(capture.canonical_input)
        self._xray_deadline(session, auth, handle.input_id, sources)
        pins = {
            shock.source.version_id: shock.source
            for shock in version.content.shocks
            if isinstance(shock, (ScenarioRateShock, ScenarioFactorShock))
        }
        catalog = self.read_capture(
            session, auth, tuple(pins[key] for key in sorted(pins)), sources=sources
        )
        replay = None
        if history is not None and selection.replay is not None:
            resolver = self._replay_resolver
            if resolver is None:
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
            replay = resolver(selection.replay, history, source, result)
        value = ScenarioExecutionInput(
            pins=ScenarioInputPins(
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                scenario_id=version.definition_id,
                scenario_version_id=version.id,
                scenario_version_digest=version.content_digest,
                portfolio_snapshot_id=selection.portfolio_snapshot_id,
                portfolio_snapshot_digest=source.snapshot_digest,
                xray_run_id=handle.run_id,
                xray_input_id=handle.input_id,
                xray_input_digest=capture.input_digest,
                xray_result_digest=result.content_digest,
                reporting_currency=selection.reporting_currency,
                source_cutoff_at=selection.source_cutoff_at,
            ),
            definition=version.content,
            xray_input=source,
            xray_result=result,
            sensitivities=catalog.capture,
            replay=replay,
            input_digest="0" * 64,
            expires_at=sources.copy_deadline,
        )
        value = replace(value, input_digest=scenario_input_digest(value))
        validate_scenario_capacity(value)
        pack_scenario_input(value)
        for license_id in tuple(sources.copy_licenses):
            sources._permit(session, auth.owner_id, license_id, SourceUse.DISPLAY)
        if sources.copy_deadline <= self._now():
            raise ScenarioStorageError(Code.RUN_EXPIRED)
        value = replace(value, expires_at=sources.copy_deadline)
        auth.check(session, now=self._now())
        return CapturedScenarioInputs(
            value=value, license_version_ids=tuple(sorted(sources.copy_licenses))
        )

    def _history(
        self,
        session: Session,
        auth: ReportAuthorization,
        identifier: UUID,
        sources: ScenarioCopySources,
    ) -> HistoricalInput:
        store = HistoricalCaptureStore(
            self._sessions, cursor_signing_key=self._cursor_key, clock=self._clock
        )
        store._sources = sources
        store._reauthorize(session, auth.owner_id, auth.account_id, input_id=identifier)
        auth.check(session, now=self._now())
        row = session.scalar(
            select(HistoricalInputModel).where(
                HistoricalInputModel.id == identifier,
                HistoricalInputModel.owner_id == auth.owner_id,
                HistoricalInputModel.broker_account_id == auth.account_id,
            )
        )
        if row is None:
            raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
        capture = store._capture_view(session, auth.owner_id, row)
        return capture.input

    def _xray_deadline(
        self,
        session: Session,
        auth: ReportAuthorization,
        identifier: UUID,
        sources: ScenarioCopySources,
    ) -> None:
        dependencies = XrayInputDependencyModel
        expiries = session.scalars(
            union_all(
                *(
                    select(func.min(model.expires_at))
                    .join(dependencies, getattr(dependencies, name) == model.id)
                    .where(
                        dependencies.input_id == identifier,
                        dependencies.owner_id == auth.owner_id,
                        model.owner_id == auth.owner_id,
                    )
                    for name, model in _SOURCE_TARGETS.items()
                )
            )
        ).all()
        for expiry in expiries:
            if expiry is not None:
                sources.copy_deadline = min(sources.copy_deadline, expiry)

    def persist_capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedScenarioInputs,
    ) -> ScenarioRunModel:
        from .scenario_run_capture import persist_capture

        return persist_capture(self, session, auth, root, captured)

    def read_retained_input(
        self,
        session: Session,
        auth: ReportAuthorization,
        identifier: UUID,
        *,
        required_copy_use: SourceUse | None = None,
    ) -> ScenarioExecutionInput:
        from .scenario_run_capture import read_retained_input

        return read_retained_input(
            self, session, auth, identifier, required_copy_use=required_copy_use
        )
