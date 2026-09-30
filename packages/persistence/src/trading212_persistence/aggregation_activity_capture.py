"""Original immutable broker revisions and owner-attested coverage fragments only."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_analytics._historical_core import event_revision_key, selected_event_revisions
from trading212_application import aggregation as app
from trading212_application.ingestion import _fingerprint
from trading212_domain import historical as h
from trading212_domain.aggregation import AggregateActivityWindow, AggregateReason
from trading212_domain.aggregation_inputs import (
    AggregateActivityCandidate,
    AggregateActivityCoverage,
    AggregateActivityInput,
    AggregateRevisionWitness,
    AggregateTransferAttestation,
)
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Scope

from .activity_revision_models import ActivityRevisionEvidenceModel
from .activity_revision_store import (
    activity_revision_sources,
    apply_revision_evidence,
    revision_view,
)
from .aggregation_authorization import AggregateAuthorization
from .aggregation_sources import AggregateSourceAuthority, authorize_aggregate_sources
from .historical_models import HistoricalActivityCoverageModel, HistoricalEvidenceModel
from .historical_normalization import normalize_record, number, obj
from .models import IngestionRunModel, SourceRecordModel

_CAPABILITIES = ("historical_orders", "historical_transactions", "historical_dividends")
_NATIVE = "synthetic-custody-v1:historical_transactions"
_PROOF_FIELDS = frozenset(
    (
        "counterpartyAccountId",
        "transferReference",
        "principal",
        "currency",
        "fxRate",
        "fxBaseCurrency",
        "fxQuoteCurrency",
        "feeRecordKey",
        "feeAmount",
        "feeCurrency",
    )
)


@dataclass(frozen=True, slots=True)
class CapturedAggregateActivity:
    value: AggregateActivityInput
    authority: AggregateSourceAuthority


def _optional_currency(value: object) -> CurrencyCode | None:
    if value is None:
        return None
    if type(value) is not str:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    return CurrencyCode(value)


def _transfer(
    row: SourceRecordModel, selected_by_key: dict[tuple[UUID, str], tuple[SourceRecordModel, ...]]
) -> AggregateTransferAttestation | None:
    body = obj(row.sanitized_payload)
    if (
        row.provider != "synthetic"
        or row.schema_version != _NATIVE
        or body.get("type") != "TRANSFER"
    ):
        return None
    proof = body.get("custodyTransfer")
    if proof is None:
        return None
    if type(proof) is not dict or set(proof) != _PROOF_FIELDS:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    if any(
        type(proof[key]) is not str
        for key in ("counterpartyAccountId", "transferReference", "currency")
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    principal = number(proof["principal"])
    if principal is None:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    fee_id = None
    fee_key = proof["feeRecordKey"]
    if fee_key is not None:
        if type(fee_key) is not str:
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        actual = selected_by_key.get((row.broker_account_id, fee_key), ())
        # Ambiguous/missing original fee cannot become an invented zero fee.
        if len(actual) == 1:
            fee_id = actual[0].id
    return AggregateTransferAttestation(
        counterparty_account_id=UUID(proof["counterpartyAccountId"]),
        transfer_reference=proof["transferReference"],
        principal=principal,
        currency=CurrencyCode(proof["currency"]),
        fx_rate=number(proof["fxRate"]),
        fx_base_currency=_optional_currency(proof["fxBaseCurrency"]),
        fx_quote_currency=_optional_currency(proof["fxQuoteCurrency"]),
        fee_record_id=fee_id,
        fee_amount=number(proof["feeAmount"]),
        fee_currency=_optional_currency(proof["feeCurrency"]),
        fee_record_key=fee_key,
    )


def _economics(
    row: SourceRecordModel, event: h.HistoricalEvent
) -> tuple[
    Literal["external", "internal", "transfer", "fee", "unknown"],
    Decimal | None,
    CurrencyCode | None,
]:
    if isinstance(event, h.HistoricalExternalFlow):
        return "external", event.signed_amount.amount, event.signed_amount.currency
    if isinstance(event, h.HistoricalCashEffect):
        return (
            ("fee" if event.effect_kind in ("fee", "tax") else "internal"),
            event.signed_amount.amount,
            event.signed_amount.currency,
        )
    if isinstance(event, h.HistoricalExecution):
        return "internal", event.cash_impact.amount, event.cash_impact.currency
    if isinstance(event, h.HistoricalDividend):
        return "internal", event.net.amount, event.net.currency
    if isinstance(event, h.HistoricalUnknownActivity):
        kind: Literal["external", "internal", "transfer", "fee", "unknown"] = (
            "transfer" if event.category == "unmatched_transfer" else "unknown"
        )
        body = obj(row.sanitized_payload)
        if (
            row.provider == "synthetic"
            and row.schema_version == _NATIVE
            and body.get("type") in ("BUY", "SELL")
            and event.known_amount is not None
        ):
            kind = "internal"
        return (
            kind,
            None if event.known_amount is None else event.known_amount.amount,
            None if event.known_amount is None else event.known_amount.currency,
        )
    return "unknown", None, None


def capture_activity(
    session: Session,
    auth: AggregateAuthorization,
    *,
    holdings_input_digest: str,
    window: AggregateActivityWindow,
    cutoff: datetime,
    now: datetime,
    check_deadline: Callable[[], None],
) -> CapturedAggregateActivity:
    if Scope.ACTIVITY_READ not in auth.scopes:
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    check_deadline()
    eligible = (
        SourceRecordModel.broker_account_id.in_(auth.account_ids),
        SourceRecordModel.capability.in_(_CAPABILITIES),
        SourceRecordModel.observed_at <= cutoff,
        SourceRecordModel.source_updated_at.is_(None)
        | (SourceRecordModel.source_updated_at <= cutoff),
    )
    # Count bytes on the bounded raw-ID prefix before JSONB crosses the driver boundary.
    metadata = (
        select(
            SourceRecordModel.id,
            func.coalesce(func.pg_column_size(SourceRecordModel.sanitized_payload), 0).label(
                "size"
            ),
        )
        .where(*eligible)
        .order_by(SourceRecordModel.id)
        .limit(10001)
        .subquery()
    )
    count, size = session.execute(
        select(func.count(), func.coalesce(func.sum(metadata.c.size), 0)).select_from(metadata)
    ).one()
    if count > 10000 or size > 33554432:
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    rows = tuple(
        session.scalars(
            select(SourceRecordModel).where(*eligible).order_by(SourceRecordModel.id).limit(10001)
        )
    )
    if len(rows) != count:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    for index, row in enumerate(rows):
        if index % 64 == 0:
            check_deadline()
        if (
            row.sanitized_payload is None
            or _fingerprint(row.sanitized_payload) != row.payload_fingerprint
        ):
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    normalized = {
        row.id: event for row in rows if (event := normalize_record(row, None, ())) is not None
    }
    if len(normalized) != len(rows):
        # A retained unsupported/empty record is not silently dropped from proof.
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    proofs = tuple(
        session.scalars(
            select(ActivityRevisionEvidenceModel)
            .where(
                ActivityRevisionEvidenceModel.owner_id == auth.owner_id,
                ActivityRevisionEvidenceModel.broker_account_id.in_(auth.account_ids),
                ActivityRevisionEvidenceModel.new_source_record_id.in_(normalized),
                ActivityRevisionEvidenceModel.first_observed_at <= cutoff,
                ActivityRevisionEvidenceModel.created_at <= cutoff,
            )
            .order_by(ActivityRevisionEvidenceModel.id)
            .limit(10001)
        )
    )
    if len(proofs) > 10000:
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    selected_ids: set[UUID] = set()
    ambiguous_keys: set[tuple[UUID, str]] = set()
    for account in auth.account_ids:
        check_deadline()
        events = tuple(normalized[row.id] for row in rows if row.broker_account_id == account)
        evidence = tuple(revision_view(row) for row in proofs if row.broker_account_id == account)
        events = apply_revision_evidence(events, evidence, cutoff=cutoff)
        selected, _ = selected_event_revisions(
            events, cutoff, revision_sources=activity_revision_sources(evidence)
        )
        selected_ids.update(UUID(x.identity.source_record_id) for x in selected)
        groups: dict[str, list[h.HistoricalEvent]] = defaultdict(list)
        for event in events:
            groups[event_revision_key(event)].append(event)
        for key, group in groups.items():
            # Group-local selection exposes exactly which retained revisions remain ambiguous.
            group_ids = {x.identity.source_record_id for x in group}
            witnesses = tuple(
                x for x in evidence if str(x.registration.new_source_record_id) in group_ids
            )
            _, ambiguous = selected_event_revisions(
                tuple(group), cutoff, revision_sources=activity_revision_sources(witnesses)
            )
            if ambiguous:
                ambiguous_keys.add((account, key))
    selected_by_key: dict[tuple[UUID, str], tuple[SourceRecordModel, ...]] = {}
    for row in rows:
        if row.id in selected_ids and row.provider_record_id is not None:
            account_key = (row.broker_account_id, row.provider_record_id)
            selected_by_key[account_key] = (*selected_by_key.get(account_key, ()), row)
    candidates = []
    for index, row in enumerate(rows):
        if index % 64 == 0:
            check_deadline()
        event = normalized[row.id]
        kind, amount, currency = _economics(row, event)
        candidates.append(
            AggregateActivityCandidate(
                source_record_id=row.id,
                account_id=row.broker_account_id,
                provider=cast(Literal["synthetic", "trading212"], row.provider),
                external_record_id=row.provider_record_id,
                schema_version=row.schema_version,
                payload_digest=row.payload_fingerprint,
                source_updated_at=row.source_updated_at,
                first_observed_at=row.observed_at,
                occurred_at=event.identity.economic_at,
                kind=kind,
                amount=amount,
                currency=currency,
                selected=row.id in selected_ids,
                selection_reason=AggregateReason.AMBIGUOUS_REVISION
                if (row.broker_account_id, event_revision_key(event)) in ambiguous_keys
                else None,
                transfer=_transfer(row, selected_by_key),
            )
        )
    coverage_rows = session.execute(
        select(
            HistoricalActivityCoverageModel,
            HistoricalEvidenceModel.id,
            HistoricalEvidenceModel.content_digest,
        )
        .join(
            HistoricalEvidenceModel,
            (HistoricalEvidenceModel.owner_id == HistoricalActivityCoverageModel.owner_id)
            & (HistoricalEvidenceModel.id == HistoricalActivityCoverageModel.evidence_id),
        )
        .join(
            IngestionRunModel,
            IngestionRunModel.id == HistoricalActivityCoverageModel.ingestion_run_id,
        )
        .where(
            HistoricalActivityCoverageModel.owner_id == auth.owner_id,
            HistoricalEvidenceModel.broker_account_id.in_(auth.account_ids),
            IngestionRunModel.broker_account_id == HistoricalEvidenceModel.broker_account_id,
            HistoricalEvidenceModel.sealed,
            func.octet_length(HistoricalEvidenceModel.canonical_evidence) > 0,
            HistoricalEvidenceModel.first_observed_at <= cutoff,
            HistoricalActivityCoverageModel.first_observed_at <= cutoff,
        )
        .order_by(HistoricalActivityCoverageModel.id)
        .limit(10001)
    ).all()
    if len(coverage_rows) > 10000:
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    authority = authorize_aggregate_sources(
        session,
        auth,
        fx_ids=(),
        evidence_ids=tuple(sorted({row[1] for row in coverage_rows})),
        cutoff=cutoff,
        now=now,
    )
    # Exact account provenance comes from the already-scoped original ingestion headers.
    ingestion_accounts: dict[UUID, UUID] = dict(
        session.execute(
            select(IngestionRunModel.id, IngestionRunModel.broker_account_id).where(
                IngestionRunModel.id.in_(row[0].ingestion_run_id for row in coverage_rows)
            )
        )
        .tuples()
        .all()
    )
    coverage = tuple(
        AggregateActivityCoverage(
            account_id=ingestion_accounts[row.ingestion_run_id],
            ingestion_run_id=row.ingestion_run_id,
            coverage_id=row.id,
            historical_evidence_id=evidence_id,
            evidence_digest=digest,
            capability=cast(
                Literal["historical_orders", "historical_transactions", "historical_dividends"],
                row.capability,
            ),
            start_at=row.start_at,
            end_at=row.end_at,
            first_observed_at=row.first_observed_at,
            complete=row.coverage_complete,
        )
        for row, evidence_id, digest in coverage_rows
    )
    revisions = tuple(
        AggregateRevisionWitness(
            evidence_id=row.id,
            owner_id=row.owner_id,
            account_id=row.broker_account_id,
            principal_id=row.principal_id,
            new_source_record_id=row.new_source_record_id,
            superseded_source_record_id=row.superseded_source_record_id,
            authority=cast(Literal["owner_attestation", "provider_evidence"], row.authority),
            evidence_key=row.evidence_key,
            economic_key=row.economic_key,
            first_observed_at=row.first_observed_at,
            content_digest=row.content_digest,
        )
        for row in proofs
    )
    value = AggregateActivityInput(
        holdings_input_digest=holdings_input_digest,
        window=window,
        account_ids=auth.account_ids,
        source_cutoff_at=cutoff,
        candidates=tuple(candidates),
        coverage=coverage,
        revisions=revisions,
    )
    check_deadline()
    return CapturedAggregateActivity(value, authority)
