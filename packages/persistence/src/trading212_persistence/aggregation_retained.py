"""Authorized full saved aggregate inputs/results for fixed report capture consumers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer
from trading212_analytics.aggregation_validation import (
    validate_activity_binding,
    validate_holdings_binding,
)
from trading212_application import aggregation as app
from trading212_domain.aggregation import AggregateRecord
from trading212_domain.aggregation_codec import (
    aggregation_activity_input_from_json,
    aggregation_activity_result_from_json,
    aggregation_holdings_input_from_json,
    aggregation_holdings_result_from_json,
    aggregation_record_bytes,
)
from trading212_domain.aggregation_inputs import (
    AggregateActivityCandidate,
    AggregateActivityCoverage,
    AggregateActivityInput,
    AggregateFxUse,
    AggregateHoldingsInput,
    AggregateRevisionWitness,
    AggregateSnapshotPin,
)
from trading212_domain.aggregation_results import (
    AggregateAccountTotal,
    AggregateActivityResult,
    AggregateComponent,
    AggregateFlowLeg,
    AggregateHolding,
    AggregateHoldingsResult,
    AggregateTransferMatch,
)
from trading212_domain.sources import SourceUse
from trading212_domain.values import require_utc
from trading212_security.principals import Scope

from . import aggregation_models as m
from .aggregation_authorization import AggregateAuthorization
from .aggregation_sources import authorize_aggregate_sources


@dataclass(frozen=True, slots=True)
class RetainedAggregateRun:
    run_id: UUID
    selection_id: UUID
    selection_revision: int
    holdings_input: AggregateHoldingsInput
    holdings_result: AggregateHoldingsResult
    holdings_result_digest: str
    activity_input: AggregateActivityInput | None
    activity_result: AggregateActivityResult | None
    activity_result_digest: str | None
    created_at: datetime
    completed_at: datetime
    expires_at: datetime


def _unavailable() -> app.AggregateServiceError:
    return app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)


def _columns(value: AggregateRecord) -> dict[str, object]:
    # Internal closed projection mapping only. It never accepts caller-selected
    # field/table names and never serializes an arbitrary API object.
    if isinstance(value, AggregateSnapshotPin):
        return {
            "account_id": value.account_id,
            "snapshot_id": value.portfolio_snapshot_id,
            "calculation_run_id": value.calculation_run_id,
        }
    if isinstance(value, AggregateFxUse):
        return {
            "account_id": value.account_id,
            "source_currency": str(value.source_currency),
            "target_currency": str(value.target_currency),
            "fx_snapshot_id": value.fx_snapshot_id,
            "fx_observation_id": value.fx_observation_id,
            "license_version_id": value.license_version_id,
            "original_rate": value.original_rate,
            "state": value.state.value,
            "inverted": value.inverted,
        }
    if isinstance(value, AggregateComponent):
        native = value.native
        return {
            "component_id": native.component_id,
            "account_id": native.account_id,
            "snapshot_id": native.portfolio_snapshot_id,
            "kind": native.kind,
            "position_id": native.component_id if native.kind == "position" else None,
            "cash_id": native.component_id if native.kind == "cash" else None,
            "listing_id": native.listing_id,
            "instrument_id": native.instrument_id,
            "quantity": native.quantity,
            "native_currency": str(native.native_currency),
            "native_value": native.native_value,
            "reporting_currency": str(value.reporting_currency),
            "converted_value": value.converted_value,
            "fx_observation_id": value.fx_observation_id,
            "quality": value.quality.value,
            "origin": native.origin.value,
            "reason": None if value.reason is None else value.reason.value,
        }
    if isinstance(value, (AggregateHolding, AggregateAccountTotal)):
        money = value.money
        identity = (
            {"instrument_id": value.instrument_id, "quantity": value.quantity}
            if isinstance(value, AggregateHolding)
            else {"account_id": value.account_id}
        )
        return {
            **identity,
            "currency": str(money.currency),
            "value": money.value,
            "known_value": money.known_value,
            "known_count": money.known_count,
            "total_count": money.total_count,
        }
    if isinstance(value, AggregateActivityCandidate):
        return {
            "account_id": value.account_id,
            "source_record_id": value.source_record_id,
            "selected": value.selected,
            "amount": value.amount,
            "currency": None if value.currency is None else str(value.currency),
        }
    if isinstance(value, AggregateActivityCoverage):
        return {
            "account_id": value.account_id,
            "coverage_id": value.coverage_id,
            "evidence_id": value.historical_evidence_id,
            "evidence_digest": value.evidence_digest,
            "ingestion_run_id": value.ingestion_run_id,
            "capability": value.capability,
            "start_at": value.start_at,
            "end_at": value.end_at,
            "first_observed_at": value.first_observed_at,
            "complete": value.complete,
        }
    if isinstance(value, AggregateRevisionWitness):
        return {
            "account_id": value.account_id,
            "evidence_id": value.evidence_id,
            "new_source_record_id": value.new_source_record_id,
            "superseded_source_record_id": value.superseded_source_record_id,
        }
    if isinstance(value, AggregateFlowLeg):
        return {
            "account_id": value.account_id,
            "source_record_id": value.source_record_id,
            "amount": value.amount,
            "currency": None if value.currency is None else str(value.currency),
            "classification": value.classification,
            "counterpart_record_id": value.counterpart_record_id,
        }
    if isinstance(value, AggregateTransferMatch):
        return {
            "outgoing_record_id": value.outgoing_record_id,
            "incoming_record_id": value.incoming_record_id,
            "outgoing_account_id": value.outgoing_account_id,
            "incoming_account_id": value.incoming_account_id,
            "outgoing_principal": value.outgoing_principal,
            "incoming_principal": value.incoming_principal,
            "outgoing_currency": str(value.outgoing_currency),
            "incoming_currency": str(value.incoming_currency),
            "fx_rate": value.fx_rate,
        }
    raise _unavailable()


def _verify_rows(
    session: Session,
    owner: UUID,
    run: UUID,
    model: type[m.AggregateProjectionRow],
    values: tuple[AggregateRecord, ...],
    check: Callable[[], None],
) -> None:
    rows = tuple(
        session.scalars(
            select(model)
            .options(undefer("*"))
            .where(model.owner_id == owner, model.run_id == run)
            .order_by(model.ordinal)
            .limit(len(values) + 1)
        )
    )
    if len(rows) != len(values):
        raise _unavailable()
    for index, (row, value) in enumerate(zip(rows, values, strict=True)):
        if index % 64 == 0:
            check()
        expected = aggregation_record_bytes(value)
        digest = sha256(b"t212pi.aggregation.record.v1\0")
        digest.update(expected)
        if (
            row.ordinal != index
            or row.payload != expected
            or row.content_digest != digest.hexdigest()
            or any(getattr(row, name) != field for name, field in _columns(value).items())
        ):
            raise _unavailable()
    check()


def _root_current(
    session: Session, auth: AggregateAuthorization, root: m.AggregateRunModel, now: datetime
) -> None:
    if (
        root.owner_id != auth.owner_id
        or not root.sealed
        or root.completed_at is None
        or root.expires_at <= now
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.RUN_EXPIRED)
    if (
        session.scalar(
            select(m.AggregateRetentionModel.id).where(
                m.AggregateRetentionModel.owner_id == auth.owner_id,
                m.AggregateRetentionModel.run_id == root.id,
            )
        )
        is not None
    ):
        raise _unavailable()


def read_retained_aggregate(
    session: Session,
    auth: AggregateAuthorization,
    root: m.AggregateRunModel,
    *,
    include_activity: bool,
    required_copy_use: SourceUse | None,
    clock: Callable[[], datetime],
    check_deadline: Callable[[], None],
) -> RetainedAggregateRun:
    """Caller obtains root metadata and current batch member authority first.

    This full immutable capture seam is intentionally separate from the <=12SQL
    paginated public read. The caller retains its original transaction deadline.
    """
    check_deadline()
    if include_activity and Scope.ACTIVITY_READ not in auth.scopes:
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    _root_current(session, auth, root, require_utc(clock()))
    selected = session.scalar(
        select(m.AggregateSelectionModel).where(
            m.AggregateSelectionModel.owner_id == auth.owner_id,
            m.AggregateSelectionModel.id == root.selection_id,
        )
    )
    members = tuple(
        session.scalars(
            select(m.AggregateMemberModel.account_id)
            .where(
                m.AggregateMemberModel.owner_id == auth.owner_id,
                m.AggregateMemberModel.selection_id == root.selection_id,
            )
            .order_by(m.AggregateMemberModel.ordinal)
        )
    )
    if selected is None or not selected.sealed or members != auth.account_ids:
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    views = ("holdings", "activity") if include_activity else ("holdings",)
    source_rows = tuple(
        session.execute(
            select(
                m.AggregateSourceModel.view_kind,
                m.AggregateSourceModel.source_kind,
                m.AggregateSourceModel.source_id,
            ).where(
                m.AggregateSourceModel.owner_id == auth.owner_id,
                m.AggregateSourceModel.run_id == root.id,
                m.AggregateSourceModel.view_kind.in_(views),
            )
        ).all()
    )
    source_authority = authorize_aggregate_sources(
        session,
        auth,
        fx_ids=tuple(sorted({row[2] for row in source_rows if row[1] == "fx"})),
        evidence_ids=tuple(sorted({row[2] for row in source_rows if row[1] == "coverage_parent"})),
        cutoff=selected.source_cutoff_at,
        now=require_utc(clock()),
        required_copy_use=required_copy_use,
    )
    if source_authority.deadline is not None and root.expires_at > source_authority.deadline:
        raise _unavailable()
    check_deadline()
    h = session.scalar(
        select(m.AggregateHoldingsPayloadModel)
        .options(undefer("*"))
        .where(
            m.AggregateHoldingsPayloadModel.owner_id == auth.owner_id,
            m.AggregateHoldingsPayloadModel.run_id == root.id,
            func.octet_length(m.AggregateHoldingsPayloadModel.input_payload)
            + func.octet_length(m.AggregateHoldingsPayloadModel.result_payload)
            + func.octet_length(m.AggregateHoldingsPayloadModel.summary_payload)
            <= 33554432,
        )
    )
    if h is None:
        raise _unavailable()
    holdings_input = aggregation_holdings_input_from_json(
        h.input_payload, expected_digest=root.holdings_input_digest
    )
    check_deadline()
    holdings_result = aggregation_holdings_result_from_json(
        h.result_payload, expected_digest=root.holdings_result_digest
    )
    validate_holdings_binding(holdings_input, holdings_result, check_deadline=check_deadline)
    if (
        tuple(x.account_id for x in holdings_input.selection.members) != members
        or holdings_input.owner_id != auth.owner_id
    ):
        raise _unavailable()
    expected_sources: set[tuple[str, str, UUID]] = set()
    expected_sources.update(
        ("holdings", "snapshot", x.portfolio_snapshot_id) for x in holdings_input.snapshots
    )
    expected_sources.update(
        ("holdings", "calculation", x.calculation_run_id) for x in holdings_input.snapshots
    )
    expected_sources.update(
        ("holdings", "broker_record", source)
        for x in holdings_input.components
        for source in x.source_record_ids
    )
    expected_sources.update(("holdings", "fx", x.fx_snapshot_id) for x in holdings_input.fx_uses)
    expected_sources.update(
        ("holdings", "fx_observation", x.fx_observation_id) for x in holdings_input.fx_uses
    )
    _verify_rows(
        session,
        auth.owner_id,
        root.id,
        m.AggregateSnapshotModel,
        holdings_input.snapshots,
        check_deadline,
    )
    _verify_rows(
        session, auth.owner_id, root.id, m.AggregateFxModel, holdings_input.fx_uses, check_deadline
    )
    _verify_rows(
        session,
        auth.owner_id,
        root.id,
        m.AggregateComponentModel,
        holdings_result.components,
        check_deadline,
    )
    _verify_rows(
        session,
        auth.owner_id,
        root.id,
        m.AggregateHoldingModel,
        holdings_result.holdings,
        check_deadline,
    )
    _verify_rows(
        session,
        auth.owner_id,
        root.id,
        m.AggregateAccountTotalModel,
        holdings_result.accounts,
        check_deadline,
    )
    activity_input = None
    activity_result = None
    if include_activity and root.activity_requested:
        a = session.scalar(
            select(m.AggregateActivityPayloadModel)
            .options(undefer("*"))
            .where(
                m.AggregateActivityPayloadModel.owner_id == auth.owner_id,
                m.AggregateActivityPayloadModel.run_id == root.id,
                func.octet_length(m.AggregateActivityPayloadModel.input_payload)
                + func.octet_length(m.AggregateActivityPayloadModel.result_payload)
                + func.octet_length(m.AggregateActivityPayloadModel.summary_payload)
                <= 33554432,
            )
        )
        if a is None:
            raise _unavailable()
        activity_input = aggregation_activity_input_from_json(
            a.input_payload, expected_digest=root.activity_input_digest
        )
        check_deadline()
        activity_result = aggregation_activity_result_from_json(
            a.result_payload, expected_digest=root.activity_result_digest
        )
        validate_activity_binding(activity_input, activity_result, check_deadline=check_deadline)
        if (
            activity_input.account_ids != members
            or activity_input.holdings_input_digest != holdings_result.input_digest
        ):
            raise _unavailable()
        _verify_rows(
            session,
            auth.owner_id,
            root.id,
            m.AggregateActivityEvidenceModel,
            activity_input.candidates,
            check_deadline,
        )
        _verify_rows(
            session,
            auth.owner_id,
            root.id,
            m.AggregateCoverageModel,
            activity_input.coverage,
            check_deadline,
        )
        _verify_rows(
            session,
            auth.owner_id,
            root.id,
            m.AggregateRevisionModel,
            activity_input.revisions,
            check_deadline,
        )
        _verify_rows(
            session,
            auth.owner_id,
            root.id,
            m.AggregateFlowModel,
            activity_result.legs,
            check_deadline,
        )
        _verify_rows(
            session,
            auth.owner_id,
            root.id,
            m.AggregateTransferModel,
            activity_result.matches,
            check_deadline,
        )
        expected_sources.update(
            ("activity", "broker_record", x.source_record_id) for x in activity_input.candidates
        )
        expected_sources.update(
            ("activity", "coverage", x.coverage_id) for x in activity_input.coverage
        )
        expected_sources.update(
            ("activity", "coverage_parent", x.historical_evidence_id)
            for x in activity_input.coverage
        )
        expected_sources.update(
            ("activity", "revision", x.evidence_id) for x in activity_input.revisions
        )
    if (
        len(source_rows) != len(expected_sources)
        or {tuple(row) for row in source_rows} != expected_sources
    ):
        raise _unavailable()
    check_deadline()
    _root_current(session, auth, root, require_utc(clock()))
    source_authority.finish(session, auth, now=require_utc(clock()), expires_at=root.expires_at)
    auth.finish(session, now=require_utc(clock()))
    check_deadline()
    if root.completed_at is None or root.holdings_result_digest is None:
        raise _unavailable()
    return RetainedAggregateRun(
        root.id,
        root.selection_id,
        root.selection_revision,
        holdings_input,
        holdings_result,
        root.holdings_result_digest,
        activity_input,
        activity_result,
        root.activity_result_digest if include_activity else None,
        root.created_at,
        root.completed_at,
        root.expires_at,
    )
