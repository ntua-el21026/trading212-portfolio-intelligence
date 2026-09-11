"""Sourced alert money conversion using the established calendar-aware FX selector."""

from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from trading212_analytics._decimal import multiply, persisted_decimal
from trading212_analytics.source_policy import select_fx
from trading212_application.historical_evidence import HistoricalPolicyRegistration
from trading212_domain import alerts as d
from trading212_domain.historical_serialization import historical_value_from_json
from trading212_domain.reports import ReportSourceKind
from trading212_domain.sources import FxOperation, FxSnapshot, SourceAvailability
from trading212_domain.values import CurrencyCode, Money

from .alert_capture_common import AlertCaptureState, AlertCaptureUnavailable, bounded
from .alert_sources import PhysicalSource, authorize_alert_physical
from .historical_models import HistoricalPolicyModel
from .planning_inputs import digest
from .source_models import (
    FxObservationModel,
    FxSnapshotModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
)


def capture_physical(state: AlertCaptureState, row: PhysicalSource, kind: ReportSourceKind) -> None:
    license = authorize_alert_physical(state.session, state.authorization, row, now=state.now)
    if max(row.effective_at, row.first_observed_at, row.created_at) > state.cutoff:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    state.licenses[license.id] = license
    state.reference(
        kind=kind,
        identifier=row.id,
        digest=row.content_digest,
        effective_at=row.effective_at,
        known_at=max(row.first_observed_at, row.created_at),
        provider_id=row.provider_id,
        license_id=row.license_version_id,
        expires_at=row.expires_at,
    )


def captured_policy(state: AlertCaptureState) -> HistoricalPolicyRegistration | None:
    model = HistoricalPolicyModel
    query = select(model).where(
        model.owner_id == state.version.owner_id,
        model.broker_account_id == state.version.account_id,
        model.effective_at <= state.cutoff,
        model.first_observed_at <= state.cutoff,
        model.created_at <= state.cutoff,
        model.sealed.is_(True),
    )
    if state.version.definition.source_policy_version_id is not None:
        query = query.where(model.id == state.version.definition.source_policy_version_id)
    rows = list(
        state.session.scalars(
            query.order_by(
                model.effective_at.desc(), model.first_observed_at.desc(), model.id
            ).limit(2)
        )
    )
    if not rows:
        return None
    row = rows[0]
    if (
        len(rows) > 1
        and row.effective_at == rows[1].effective_at
        and row.content_digest != rows[1].content_digest
    ):
        raise AlertCaptureUnavailable(d.AlertReason.AMBIGUOUS_SOURCE)
    if sha256(row.canonical_policy).hexdigest() != row.content_digest:
        raise AlertCaptureUnavailable(d.AlertReason.COMPUTATION_FAILED)
    value = historical_value_from_json(row.canonical_policy, HistoricalPolicyRegistration)
    state.reference(
        kind=ReportSourceKind.POLICY,
        identifier=row.id,
        digest=row.content_digest,
        effective_at=row.effective_at,
        known_at=max(row.first_observed_at, row.created_at),
    )
    return value


def convert_captured_money(
    state: AlertCaptureState, value: Money, currency: CurrencyCode, *, at: datetime
) -> Money:
    if value.currency == currency:
        return value
    policy = captured_policy(state)
    if policy is None or policy.source_policy is None:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
    selection_policy = policy.source_policy
    model = FxSnapshotModel
    rows = bounded(
        list(
            state.session.scalars(
                select(model)
                .where(
                    model.owner_id == state.version.owner_id,
                    model.provider_id.in_(
                        [UUID(item) for item in selection_policy.provider_priority]
                    ),
                    model.effective_at <= state.cutoff,
                    model.first_observed_at <= state.cutoff,
                    model.created_at <= state.cutoff,
                )
                .order_by(model.id)
                .limit(257)
            )
        ),
        256,
    )
    snapshots: dict[str, FxSnapshot] = {}
    headers = {str(row.id): row for row in rows}
    # License checks precede reading normalized observations, including rejected candidates.
    for row in rows:
        authorize_alert_physical(state.session, state.authorization, row, now=state.now)
        snapshot = state.sources._load_snapshot(state.session, row)
        assert isinstance(snapshot, FxSnapshot)
        snapshots[snapshot.id] = snapshot
    alternatives = []
    for identifier in sorted({row.calendar_id for row in rows}):
        calendar_row = state.session.get(SourceCalendarModel, identifier)
        if (
            calendar_row is None
            or calendar_row.owner_id != state.version.owner_id
            or calendar_row.created_at > state.cutoff
        ):
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
        if (
            state.session.scalar(
                select(SourceCalendarSessionModel.id)
                .where(
                    SourceCalendarSessionModel.calendar_id == identifier,
                    SourceCalendarSessionModel.owner_id == state.version.owner_id,
                    SourceCalendarSessionModel.created_at > state.cutoff,
                )
                .limit(1)
            )
            is not None
        ):
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
        calendar = state.sources._calendar(state.session, state.version.owner_id, identifier)
        grouped = tuple(
            item for item in snapshots.values() if headers[item.id].calendar_id == identifier
        )
        selected = select_fx(
            grouped,
            base=value.currency,
            quote=currency,
            at=at,
            source_cutoff_at=state.cutoff,
            policy=selection_policy,
            calendar=calendar,
        )
        if selected.availability is not SourceAvailability.AVAILABLE:
            continue
        rank = (
            {
                FxOperation.DIRECT: 0,
                FxOperation.RECIPROCAL: 1,
                FxOperation.TRIANGULATED: 2,
                FxOperation.IDENTITY: 0,
            }[selected.operation],
            min(
                selection_policy.provider_priority.index(item.provider_id)
                for item in selected.sources
            ),
        )
        alternatives.append((rank, str(identifier), selected, calendar_row))
    if not alternatives:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
    alternatives.sort(key=lambda item: (item[0], item[1]))
    rank, _, selected, calendar_row = alternatives[0]
    if any(item[0] == rank and item[2].rate != selected.rate for item in alternatives[1:]):
        raise AlertCaptureUnavailable(d.AlertReason.AMBIGUOUS_SOURCE)
    state.reference(
        kind=ReportSourceKind.CALENDAR,
        identifier=calendar_row.id,
        digest=calendar_row.content_digest,
        effective_at=calendar_row.created_at,
        known_at=calendar_row.created_at,
    )
    legs = []
    current_currency = value.currency
    for source in selected.sources:
        header = headers[source.snapshot_id]
        capture_physical(state, header, ReportSourceKind.FX_SNAPSHOT)
        observation = state.session.scalar(
            select(FxObservationModel).where(
                FxObservationModel.owner_id == state.version.owner_id,
                FxObservationModel.snapshot_id == header.id,
                FxObservationModel.ordinal == source.observation_index,
            )
        )
        if observation is None or observation.created_at > state.cutoff:
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
        state.reference(
            kind=ReportSourceKind.FX_OBSERVATION,
            identifier=observation.id,
            parent_id=header.id,
            digest=digest(
                (
                    observation.id,
                    observation.snapshot_id,
                    observation.ordinal,
                    observation.session_date,
                    observation.effective_at,
                    observation.state,
                    observation.base,
                    observation.quote,
                    observation.rate,
                    observation.batch_key,
                )
            ),
            effective_at=observation.effective_at,
            known_at=max(header.first_observed_at, observation.created_at),
            provider_id=header.provider_id,
            license_id=header.license_version_id,
            expires_at=header.expires_at,
        )
        base, quote = CurrencyCode(observation.base), CurrencyCode(observation.quote)
        inverse = current_currency != base
        if current_currency != (quote if inverse else base) or observation.rate is None:
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
        legs.append(
            d.AlertFxLeg(
                base=base,
                quote=quote,
                rate=observation.rate,
                source_reference_key=f"{ReportSourceKind.FX_OBSERVATION.value}.{observation.id}",
                snapshot_id=header.id,
                provider_id=header.provider_id,
                observed_at=observation.effective_at,
                inverse=inverse,
            )
        )
        current_currency = base if inverse else quote
    assert selected.rate is not None
    converted = Money(persisted_decimal(multiply(value.amount, selected.rate)), currency)
    state.fx_conversions.append(
        d.AlertMoneyConversion(
            original=value,
            reporting_currency=currency,
            converted=converted,
            comparison_basis=converted.amount,
            legs=tuple(legs),
        )
    )
    return converted
