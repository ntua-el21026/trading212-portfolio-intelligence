"""Authorized immutable X-ray runs, exact dependency checks, and retained source headers."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.orm import Session
from trading212_application import xray as app
from trading212_domain import xray as d
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import (
    decode_xray_component,
    decode_xray_input,
    decode_xray_policy,
    decode_xray_result,
)
from trading212_domain.xray_result import (
    XrayCalculation,
    XrayDisplayResidual,
    XrayPortfolioSummary,
    XrayWarning,
)
from trading212_security.principals import Principal

from . import xray_catalog_models as cm
from . import xray_run_models as xm
from .models import (
    CalculationRunModel,
    PortfolioSnapshotModel,
    ReconciliationRunModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .planning_models import AnalyticsRunModel
from .source_models import (
    FxObservationModel,
    FxSnapshotModel,
    MarketDataProviderModel,
    SourceCoverageGapModel,
    SourceSnapshotFields,
)
from .xray_base import xray_error
from .xray_capture import capture_xray
from .xray_capture_base import bounded_rows
from .xray_ingestion import XrayIngestion
from .xray_publication import publish_xray
from .xray_store_contract import XrayRunHandle
from .xray_views import residual_view, warning_view

_SOURCE_TARGETS: dict[str, type[Any]] = {
    "fx_snapshot_id": FxSnapshotModel,
    "entity_evidence_version_id": cm.EntityEvidenceVersionModel,
    "classification_snapshot_id": cm.ClassificationSnapshotModel,
    "fund_definition_id": cm.FundDefinitionModel,
    "fund_mapping_id": cm.FundSourceMappingModel,
    "constituent_snapshot_id": cm.ConstituentSnapshotModel,
}
_INTERNAL_TARGETS: dict[str, type[Any]] = {
    "valuation_run_id": CalculationRunModel,
    "reconciliation_run_id": ReconciliationRunModel,
    "broker_source_record_id": SourceRecordModel,
    "threshold_policy_id": cm.XrayPolicyVersionModel,
}


class XrayRunStore(XrayIngestion):
    def _xray_storage_licenses(
        self, session: Session, owner: UUID, handle: XrayRunHandle
    ) -> tuple[UUID, ...]:
        """Read only license IDs after this handle's full source authorization.

        The caller retains sources/xray owner locks. The preceding run lookup
        verifies every normalized dependency against its actual parent and
        physical source record; no preview or bounded visible page defines this
        inventory, and no canonical reference needs to be decoded again.
        """
        table = xm.XrayInputDependencyModel
        identifiers = tuple(
            session.scalars(
                select(table.license_version_id)
                .where(
                    table.owner_id == owner,
                    table.input_id == handle.input_id,
                    table.license_version_id.is_not(None),
                )
                .distinct()
                .order_by(table.license_version_id)
                .limit(100_001)
            )
        )
        if len(identifiers) > 100_000:
            raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE)
        return tuple(identifier for identifier in identifiers if identifier is not None)

    def _resolve_xray_run(
        self,
        session: Session,
        principal: Principal,
        account_id: UUID,
        request: app.XrayRunRequest,
        *,
        retained_run_id: UUID | None = None,
    ) -> XrayRunHandle:
        self._account(session, principal, str(account_id))
        explicit = None if request.run_id is None else UUID(request.run_id)
        if explicit is not None and retained_run_id is not None and explicit != retained_run_id:
            raise xray_error(app.XrayServiceErrorCode.INPUT_SNAPSHOT_MISMATCH)
        pin = explicit or retained_run_id
        if pin is not None:
            handle = self._authorize_xray_run(session, principal, account_id, pin)
            snapshot = session.scalar(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.id == UUID(request.snapshot_id),
                    PortfolioSnapshotModel.broker_account_id == account_id,
                )
            )
            if snapshot is None:
                raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
            currency = (
                request.currency.reporting_currency.value
                if isinstance(request.currency, app.ExplicitCurrency)
                else snapshot.reporting_currency
            )
            if (
                handle.context.snapshot_id,
                handle.context.source_cutoff_at,
                handle.context.reporting_currency.value,
            ) != (request.snapshot_id, request.source_cutoff_at, currency):
                raise xray_error(app.XrayServiceErrorCode.INPUT_SNAPSHOT_MISMATCH)
            return handle
        try:
            captured = capture_xray(self, session, UUID(principal.owner_id), account_id, request)
            fingerprint = sha256(captured.canonical_input).hexdigest()
            previous = session.scalar(
                select(xm.XrayRunModel.id)
                .join(
                    xm.XrayInputSnapshotModel,
                    xm.XrayInputSnapshotModel.id == xm.XrayRunModel.input_id,
                )
                .where(
                    xm.XrayInputSnapshotModel.owner_id == UUID(principal.owner_id),
                    xm.XrayInputSnapshotModel.account_id == account_id,
                    xm.XrayInputSnapshotModel.input_digest == fingerprint,
                )
            )
            if previous is not None:
                return self._authorize_xray_run(session, principal, account_id, previous)
            run = publish_xray(self, session, captured)
            return self._authorize_xray_run(session, principal, account_id, run.id)
        except DomainError:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE) from None

    def _authorized_rows(
        self, session: Session, principal: Principal, account_id: UUID, run_id: UUID
    ) -> tuple[xm.XrayRunModel, xm.XrayInputSnapshotModel, dict[UUID, d.XraySourceDependency]]:
        self._account(session, principal, str(account_id))
        owner = UUID(principal.owner_id)
        pair = session.execute(
            select(xm.XrayRunModel, xm.XrayInputSnapshotModel)
            .join(
                xm.XrayInputSnapshotModel, xm.XrayInputSnapshotModel.id == xm.XrayRunModel.input_id
            )
            .where(
                xm.XrayRunModel.id == run_id,
                xm.XrayRunModel.owner_id == owner,
                xm.XrayInputSnapshotModel.owner_id == owner,
                xm.XrayInputSnapshotModel.account_id == account_id,
            )
        ).first()
        if pair is None:
            raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
        run, capture = pair
        if run.sealed_at is None or capture.sealed_at is None:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        if (
            session.scalar(
                select(xm.XrayRetentionEventModel.id)
                .where(
                    xm.XrayRetentionEventModel.owner_id == owner,
                    xm.XrayRetentionEventModel.input_id == capture.id,
                )
                .limit(1)
            )
            is not None
        ):
            raise xray_error(app.XrayServiceErrorCode.ACCESS_DENIED)
        # Header-only discovery and exact source permission checks precede every
        # canonical input/result/reference decode, including conditional reads.
        table = xm.XrayInputDependencyModel
        names = (*_SOURCE_TARGETS, *_INTERNAL_TARGETS)
        rows = session.execute(
            select(
                table.id,
                table.reference_id,
                table.provider_id,
                table.license_version_id,
                *(getattr(table, key) for key in names),
                func.octet_length(table.canonical_reference).label("payload_bytes"),
            )
            .where(table.owner_id == owner, table.input_id == capture.id)
            .order_by(table.id)
            .limit(100_001)
        ).all()
        if len(rows) > 100_000 or sum(row.payload_bytes for row in rows) > 33_554_432:
            raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE)
        parents: dict[tuple[str, UUID], Any] = {}
        for name, model in {**_SOURCE_TARGETS, **_INTERNAL_TARGETS}.items():
            identifiers = {getattr(row, name) for row in rows if getattr(row, name) is not None}
            ordered = sorted(identifiers, key=str)
            for offset in range(0, len(ordered), 512):
                query = select(model).where(model.id.in_(ordered[offset : offset + 512]))
                if hasattr(model, "owner_id"):
                    query = query.where(model.owner_id == owner)
                elif hasattr(model, "broker_account_id"):
                    query = query.where(model.broker_account_id == account_id)
                for parent in session.scalars(query):
                    parents[(name, parent.id)] = parent
        permitted_licenses: set[UUID] = set()
        checked_sources: set[tuple[str, UUID]] = set()
        for row in rows:
            selected = [
                (name, getattr(row, name)) for name in names if getattr(row, name) is not None
            ]
            if len(selected) != 1:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            key = selected[0]
            parent = parents.get(key)
            if parent is None:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            if key[0] in _SOURCE_TARGETS:
                if (row.provider_id, row.license_version_id) != (
                    parent.provider_id,
                    parent.license_version_id,
                ):
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
                if parent.license_version_id not in permitted_licenses:
                    self._permit(session, owner, parent.license_version_id, SourceUse.DISPLAY)
                    permitted_licenses.add(parent.license_version_id)
                if parent.expires_at <= self._now():
                    raise xray_error(app.XrayServiceErrorCode.ACCESS_DENIED)
                if key not in checked_sources:
                    if (
                        key[0] == "fx_snapshot_id"
                        and parent.adapter_version == "premium_fixed_get_v1"
                        and session.scalar(
                            text(
                                "SELECT acquisition_source_restricted(:owner, 'fx', :sou"
                                "rce, :at, :use)"
                            ),
                            {
                                "owner": owner,
                                "source": key[1],
                                "at": self._now(),
                                "use": (self._required_copy_use or SourceUse.DISPLAY).value,
                            },
                        )
                        is not False
                    ):
                        raise xray_error(app.XrayServiceErrorCode.ACCESS_DENIED)
                    from .source_models import SourceExpiryEventModel, SourceRetentionWorkModel
                    from .xray_lifecycle_models import (
                        EnrichmentExpiryEventModel,
                        EnrichmentRetentionWorkModel,
                    )

                    lifecycle = (
                        (SourceExpiryEventModel, SourceRetentionWorkModel)
                        if key[0] in ("fx_snapshot_id", "constituent_snapshot_id")
                        else (EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel)
                    )
                    if any(
                        session.scalar(
                            select(model.id)
                            .where(model.owner_id == owner, getattr(model, key[0]) == key[1])
                            .limit(1)
                        )
                        is not None
                        for model in lifecycle
                    ):
                        raise xray_error(app.XrayServiceErrorCode.ACCESS_DENIED)
                    checked_sources.add(key)
            elif (
                row.provider_id is not None
                or row.license_version_id is not None
                or (key[0] == "threshold_policy_id" and parent.account_id != account_id)
            ):
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        if not capture.canonical_input or any(row.payload_bytes == 0 for row in rows):
            raise xray_error(app.XrayServiceErrorCode.ACCESS_DENIED)
        decoded: dict[UUID, d.XraySourceDependency] = {}
        stored = bounded_rows(
            session,
            select(table)
            .where(table.owner_id == owner, table.input_id == capture.id)
            .order_by(table.id),
            100_000,
        )
        for row in stored:
            try:
                reference = decode_xray_component(row.canonical_reference, d.XraySourceDependency)
            except DomainError:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE) from None
            if (
                reference.id,
                reference.owner_id,
                reference.account_id,
                reference.snapshot_id,
                reference.provider_id,
                reference.license_version_id,
            ) != (
                row.reference_id,
                owner,
                account_id,
                capture.snapshot_id,
                None if row.provider_id is None else str(row.provider_id),
                row.license_version_id,
            ):
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            target = next(
                (name, getattr(row, name)) for name in names if getattr(row, name) is not None
            )
            parent = parents[target]
            if target[0] in _SOURCE_TARGETS and reference.content_digest != parent.content_digest:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            decoded[reference.id] = reference
        self._physical_references(session, capture, stored, decoded)
        return run, capture, decoded

    def _physical_references(
        self,
        session: Session,
        capture: xm.XrayInputSnapshotModel,
        rows: list[xm.XrayInputDependencyModel],
        references: dict[UUID, d.XraySourceDependency],
    ) -> None:
        direct = {
            d.XrayReferenceKind.CALCULATION_RUN: "valuation_run_id",
            d.XrayReferenceKind.BROKER_SOURCE_RECORD: "broker_source_record_id",
            d.XrayReferenceKind.RECONCILIATION_RUN: "reconciliation_run_id",
            d.XrayReferenceKind.OWNER_POLICY: "threshold_policy_id",
            d.XrayReferenceKind.FX_SNAPSHOT: "fx_snapshot_id",
            d.XrayReferenceKind.FUND_DEFINITION: "fund_definition_id",
            d.XrayReferenceKind.FUND_MAPPING: "fund_mapping_id",
            d.XrayReferenceKind.CONSTITUENT_SNAPSHOT: "constituent_snapshot_id",
            d.XrayReferenceKind.CLASSIFICATION_SNAPSHOT: "classification_snapshot_id",
            d.XrayReferenceKind.ENTITY_EVIDENCE_VERSION: "entity_evidence_version_id",
        }
        children: dict[d.XrayReferenceKind, tuple[type[Any], str, str]] = {
            d.XrayReferenceKind.SNAPSHOT_POSITION: (
                SnapshotPositionModel,
                "snapshot_id",
                "valuation_run_id",
            ),
            d.XrayReferenceKind.SNAPSHOT_CASH: (
                SnapshotCashModel,
                "snapshot_id",
                "valuation_run_id",
            ),
            d.XrayReferenceKind.FX_OBSERVATION: (
                FxObservationModel,
                "snapshot_id",
                "fx_snapshot_id",
            ),
            d.XrayReferenceKind.FX_COVERAGE_GAP: (
                SourceCoverageGapModel,
                "fx_snapshot_id",
                "fx_snapshot_id",
            ),
            d.XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE: (
                cm.EntityEvidenceReferenceModel,
                "evidence_version_id",
                "entity_evidence_version_id",
            ),
            d.XrayReferenceKind.RELATIONSHIP: (
                cm.InstrumentEntityRelationshipModel,
                "evidence_version_id",
                "entity_evidence_version_id",
            ),
            d.XrayReferenceKind.CLASSIFICATION_ASSIGNMENT: (
                cm.ClassificationAssignmentModel,
                "snapshot_id",
                "classification_snapshot_id",
            ),
            d.XrayReferenceKind.CONSTITUENT_HOLDING: (
                cm.ConstituentHoldingModel,
                "snapshot_id",
                "constituent_snapshot_id",
            ),
        }
        groups: dict[d.XrayReferenceKind, set[tuple[UUID, UUID]]] = {}
        for row in rows:
            physical = references[row.reference_id].reference
            if physical.kind in direct:
                valid = getattr(row, direct[physical.kind]) == physical.record_id
            elif physical.kind is d.XrayReferenceKind.PORTFOLIO_SNAPSHOT:
                valid = (
                    physical.record_id == capture.snapshot_id
                    and row.valuation_run_id == capture.valuation_run_id
                )
            elif physical.kind in children:
                _, _, field = children[physical.kind]
                parent = capture.snapshot_id if field == "valuation_run_id" else getattr(row, field)
                valid = parent is not None and physical.parent_record_id == parent
                if field == "valuation_run_id":
                    valid = valid and row.valuation_run_id == capture.valuation_run_id
                if valid:
                    groups.setdefault(physical.kind, set()).add((physical.record_id, parent))
            else:
                valid = False
            if not valid:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        for kind, pairs in groups.items():
            model, parent_column, _ = children[kind]
            ordered = sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1])))
            for offset in range(0, len(ordered), 512):
                expected = set(ordered[offset : offset + 512])
                query = select(model.id, getattr(model, parent_column)).where(
                    tuple_(model.id, getattr(model, parent_column)).in_(tuple(expected))
                )
                if hasattr(model, "owner_id"):
                    query = query.where(model.owner_id == capture.owner_id)
                if {tuple(row) for row in session.execute(query)} != expected:
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)

    def _authorize_xray_run(
        self, session: Session, principal: Principal, account_id: UUID, run_id: UUID
    ) -> XrayRunHandle:
        run, capture, references = self._authorized_rows(session, principal, account_id, run_id)
        try:
            summary = decode_xray_component(run.canonical_summary, XrayPortfolioSummary)
            policy_row = self._owned(
                session, capture.owner_id, cm.XrayPolicyVersionModel, capture.policy_id
            )
            policy = decode_xray_policy(policy_row.canonical_policy)
            if policy.id != capture.policy_id:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            policy_pairs: tuple[
                tuple[
                    Literal[
                        "provider_selection",
                        "identity",
                        "classification",
                        "freshness",
                        "quality",
                        "traversal",
                    ],
                    Any,
                ],
                ...,
            ] = (
                ("provider_selection", policy.provider_selection_policy),
                ("identity", policy.identity_policy),
                ("classification", policy.classification_policy),
                ("freshness", policy.freshness_policy),
                ("quality", policy.quality_policy),
                ("traversal", policy.traversal_policy),
            )
            policies: tuple[app.XrayPolicyReference, ...] = (
                app.XrayPolicyReference(
                    kind="calculation", id=str(policy.id), version=policy.version
                ),
                *(
                    app.XrayPolicyReference(kind=kind, id=str(item.id), version=item.version)
                    for kind, item in policy_pairs
                ),
            )
            if isinstance(policy.thresholds, d.ConcentrationThresholdPolicy):
                policies += (
                    app.XrayPolicyReference(
                        kind="threshold",
                        id=str(policy.thresholds.id),
                        version=policy.thresholds.version,
                    ),
                )
            warnings = tuple(
                decode_xray_component(row, XrayWarning)
                for row in session.scalars(
                    select(xm.XrayWarningModel.canonical_payload)
                    .where(
                        xm.XrayWarningModel.owner_id == capture.owner_id,
                        xm.XrayWarningModel.run_id == run.id,
                    )
                    .order_by(xm.XrayWarningModel.ordinal)
                    .limit(64)
                )
            )
            residuals = tuple(
                decode_xray_component(row, XrayDisplayResidual)
                for row in session.scalars(
                    select(xm.XrayResidualModel.canonical_payload)
                    .where(
                        xm.XrayResidualModel.owner_id == capture.owner_id,
                        xm.XrayResidualModel.run_id == run.id,
                    )
                    .order_by(xm.XrayResidualModel.ordinal)
                    .limit(64)
                )
            )
            warning_count = (
                session.scalar(
                    select(func.count())
                    .select_from(xm.XrayWarningModel)
                    .where(
                        xm.XrayWarningModel.owner_id == capture.owner_id,
                        xm.XrayWarningModel.run_id == run.id,
                    )
                )
                or 0
            )
            residual_count = (
                session.scalar(
                    select(func.count())
                    .select_from(xm.XrayResidualModel)
                    .where(
                        xm.XrayResidualModel.owner_id == capture.owner_id,
                        xm.XrayResidualModel.run_id == run.id,
                    )
                )
                or 0
            )
            source_views = tuple(
                self._source_view(session, capture.owner_id, references[identifier])
                for identifier in sorted(references, key=str)[:64]
            )
            context = app.XrayContext(
                account_id=str(account_id),
                snapshot_id=str(capture.snapshot_id),
                run_id=str(run.id),
                input_snapshot_id=str(capture.id),
                input_digest=capture.input_digest,
                content_digest=run.content_digest,
                valuation_at=capture.valuation_at,
                source_cutoff_at=capture.source_cutoff_at,
                reporting_currency=CurrencyCode(capture.reporting_currency),
                calculated_at=run.calculated_at,
                quality_evaluated_at=capture.valuation_at
                if policy.freshness_policy.evaluation_basis == "valuation_at"
                else capture.source_cutoff_at,
                method=app.XrayMethodView(),
                policies=policies,
                sources=source_views,
                source_count=len(references),
                source_omitted_count=max(0, len(references) - 64),
                warnings=tuple(warning_view(item) for item in warnings),
                warning_count=warning_count,
                warning_omitted_count=max(0, warning_count - 64),
                residuals=tuple(residual_view(item) for item in residuals),
                residual_count=residual_count,
                residual_omitted_count=max(0, residual_count - 64),
            )
            return XrayRunHandle(
                run_id=run.id, input_id=capture.id, context=context, summary=summary
            )
        except DomainError:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE) from None

    def _load_xray_result(
        self, session: Session, principal: Principal, account_id: UUID, handle: XrayRunHandle
    ) -> XrayCalculation:
        run, capture, references = self._authorized_rows(
            session, principal, account_id, handle.run_id
        )
        if capture.id != handle.input_id:
            raise xray_error(app.XrayServiceErrorCode.INPUT_SNAPSHOT_MISMATCH)
        stored = session.scalar(
            select(AnalyticsRunModel).where(
                AnalyticsRunModel.owner_id == capture.owner_id,
                AnalyticsRunModel.id == run.analytics_run_id,
            )
        )
        if stored is None:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        if len(stored.canonical_result) > 33_554_432 or len(capture.canonical_input) > 33_554_432:
            raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE)
        if (
            stored.broker_account_id != account_id
            or stored.kind != "xray"
            or sha256(stored.canonical_result).hexdigest() != run.content_digest
            or stored.content_digest != run.content_digest
            or stored.input_digest != capture.input_digest
            or sha256(capture.canonical_input).hexdigest() != capture.input_digest
            or stored.canonical_input != capture.canonical_input
        ):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        try:
            value = decode_xray_input(capture.canonical_input)
            result = decode_xray_result(stored.canonical_result)
        except DomainError:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE) from None
        if (
            (
                result.owner_id,
                result.account_id,
                result.snapshot_id,
                result.input_digest,
                result.reporting_currency.value,
                result.valuation_at.value,
                result.source_cutoff_at.value,
            )
            != (
                capture.owner_id,
                account_id,
                capture.snapshot_id,
                capture.input_digest,
                capture.reporting_currency,
                capture.valuation_at,
                capture.source_cutoff_at,
            )
            or {item.id: item for item in value.source_dependencies} != references
            or {item.id: item for item in result.source_dependencies} != references
        ):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        return result

    def _source_view(
        self, session: Session, owner: UUID, reference: d.XraySourceDependency
    ) -> app.XraySourceReferenceView:
        physical = reference.reference
        target_models = {
            d.XrayReferenceKind.FUND_DEFINITION: cm.FundDefinitionModel,
            d.XrayReferenceKind.FUND_MAPPING: cm.FundSourceMappingModel,
            d.XrayReferenceKind.CONSTITUENT_SNAPSHOT: cm.ConstituentSnapshotModel,
            d.XrayReferenceKind.CLASSIFICATION_SNAPSHOT: cm.ClassificationSnapshotModel,
            d.XrayReferenceKind.ENTITY_EVIDENCE_VERSION: cm.EntityEvidenceVersionModel,
            d.XrayReferenceKind.FX_SNAPSHOT: FxSnapshotModel,
        }
        model = target_models.get(physical.kind)
        identifier: UUID | None = physical.record_id
        if physical.kind in (
            d.XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE,
            d.XrayReferenceKind.RELATIONSHIP,
        ):
            model, identifier = cm.EntityEvidenceVersionModel, physical.parent_record_id
        elif physical.kind in (
            d.XrayReferenceKind.FX_OBSERVATION,
            d.XrayReferenceKind.FX_COVERAGE_GAP,
        ):
            model, identifier = FxSnapshotModel, physical.parent_record_id
        source = cast(
            cm.XrayEvidenceFields | SourceSnapshotFields | None,
            (
                None
                if model is None or identifier is None
                else self._owned(session, owner, model, identifier)
            ),
        )
        provider = (
            None
            if reference.provider_id is None
            else self._owned(session, owner, MarketDataProviderModel, reference.provider_id)
        )
        source_at = None if source is None else source.effective_at
        known_at = None if source is None else source.first_observed_at
        confidence = None if source is None else getattr(source, "confidence", None)
        quality = (
            QualityState.FRESH
            if source is None
            else QualityState(getattr(source, "quality", "fresh"))
        )
        if physical.kind is d.XrayReferenceKind.BROKER_SOURCE_RECORD:
            record = session.get(SourceRecordModel, physical.record_id)
            if record is not None:
                source_at, known_at = (
                    record.source_updated_at or record.observed_at,
                    record.observed_at,
                )
        return app.XraySourceReferenceView(
            id=str(reference.id),
            kind=reference.kind,
            subject_id=str(
                physical.record_id
                if reference.kind is d.XrayDependencyKind.CONSTITUENTS
                else reference.subject_id
            ),
            content_digest=reference.content_digest,
            source_at=source_at,
            first_observed_at=known_at,
            provider_id=reference.provider_id,
            provider_name=None if provider is None else provider.name,
            license_version_id=None
            if reference.license_version_id is None
            else str(reference.license_version_id),
            confidence=confidence,
            quality=quality,
        )

    def _xray_source_views(
        self, session: Session, owner: UUID, handle: XrayRunHandle, reference_ids: tuple[UUID, ...]
    ) -> tuple[app.XraySourceReferenceView, ...]:
        if len(reference_ids) > 256 or len(set(reference_ids)) != len(reference_ids):
            raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE)
        if not reference_ids:
            return ()
        run = session.scalar(
            select(xm.XrayRunModel).where(
                xm.XrayRunModel.owner_id == owner,
                xm.XrayRunModel.id == handle.run_id,
                xm.XrayRunModel.input_id == handle.input_id,
            )
        )
        if run is None or run.sealed_at is None:
            raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
        rows = bounded_rows(
            session,
            select(xm.XrayInputDependencyModel).where(
                xm.XrayInputDependencyModel.owner_id == owner,
                xm.XrayInputDependencyModel.input_id == handle.input_id,
                xm.XrayInputDependencyModel.reference_id.in_(reference_ids),
            ),
            256,
        )
        if {row.reference_id for row in rows} != set(reference_ids):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        sources = {
            row.reference_id: decode_xray_component(row.canonical_reference, d.XraySourceDependency)
            for row in rows
        }
        return tuple(
            self._source_view(session, owner, sources[identifier]) for identifier in reference_ids
        )
