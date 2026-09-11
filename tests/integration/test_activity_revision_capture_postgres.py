"""Real ingestion corrections keep canonical identities and complete period groups."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics._historical_core import event_revision_key, selected_events
from trading212_application import activity_revisions as revision
from trading212_application import ingestion
from trading212_application.historical_evidence import HistoricalPolicyRegistration
from trading212_domain import alerts as a
from trading212_domain import historical as h
from trading212_domain.historical_serialization import (
    historical_value_from_json,
)
from trading212_domain.reports import ReportSourceKind
from trading212_domain.serialization import canonical_json
from trading212_domain.values import CurrencyCode
from trading212_persistence.activity_revision_store import PostgresActivityRevisionStore
from trading212_persistence.historical_models import HistoricalPolicyModel
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.models import SourceRecordModel
from trading212_persistence.source_models import MarketDataInstrumentModel, MarketSourceSeriesModel
from trading212_worker.historical_seed import CURSOR_KEY
from trading212_worker.postgres_store import PostgresIngestionStore

from tests.integration.report_history_cases import HistoryReportCase, history_report_case
from tests.integration.test_activity_revisions_postgres import registration
from tests.integration.test_alert_capture_matrix_postgres import Matrix
from tests.integration.test_alert_event_selection_postgres import Broker
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.unit.analytics.alert_factories import predicate

pytestmark = pytest.mark.integration
DAY = date(2025, 6, 15)


def request(case: HistoryReportCase, cutoff: datetime) -> h.HistoricalSelectionRequest:
    with case.sessions() as session:
        row = session.scalar(
            select(HistoricalPolicyModel).where(
                HistoricalPolicyModel.broker_account_id == case.account_id
            )
        )
        assert row is not None
        policy = historical_value_from_json(row.canonical_policy, HistoricalPolicyRegistration)
    return h.HistoricalSelectionRequest(
        window=h.HistoricalWindow(
            start_date=DAY,
            end_date=DAY,
            reporting_currency=CurrencyCode("EUR"),
            source_cutoff_at=cutoff,
            knowledge_policy=h.KnowledgePolicy.AS_OF_CUTOFF,
        ),
        accounting_policy=policy.accounting_policy,
        source_policy=policy.source_policy,
        reporting_calendar_ref=policy.reporting_calendar_ref,
    )


async def ingest(
    case: HistoryReportCase,
    capability: ingestion.IngestionCapability,
    record: ingestion.SourceRecord,
) -> UUID:
    broker = Broker()
    broker.rows = {capability: (record,)}
    result = await ingestion.IngestionCoordinator(
        provider=broker, store=PostgresIngestionStore(case.sessions, provider="synthetic")
    ).refresh(
        owner_id=case.principal.owner_id,
        account_id=str(case.account_id),
        mode=ingestion.RunMode.FULL,
        capabilities=ingestion.HISTORY_REFRESH_ORDER,
        idempotency_key=uuid4().hex,
        correlation_id="historical-revision-capture",
    )
    assert result.status is ingestion.RunStatus.SUCCEEDED
    with case.sessions() as session:
        row = session.scalar(
            select(SourceRecordModel).where(
                SourceRecordModel.ingestion_run_id == UUID(result.id),
                SourceRecordModel.capability == capability.value,
            )
        )
        assert row is not None
        return row.id


async def register(
    case: HistoryReportCase, new: UUID, old: UUID
) -> revision.ActivityRevisionEvidence:
    return await PostgresActivityRevisionStore(case.sessions).register_activity_revision(
        case.principal,
        case.account_id,
        registration(new, old),
        idempotency_key=uuid4().hex,
        correlation_id="historical-revision-capture",
    )


def test_mapped_order_revision_registers_the_identity_used_by_historical_and_alert_capture(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    async def run() -> None:
        case = history_report_case(*seeded_history)
        matrix = Matrix(case.sessions, case.principal, case.account_id, CURSOR_KEY)
        version = await matrix.activate(
            replace(
                predicate(a.AlertMetric.ACTIVITY_COUNT), activity_kind=h.HistoricalCashFlowKind.BUY
            )
        )
        with case.sessions() as session:
            mapping = session.scalar(
                select(MarketDataInstrumentModel)
                .join(
                    MarketSourceSeriesModel,
                    MarketSourceSeriesModel.mapping_id == MarketDataInstrumentModel.id,
                )
                .where(
                    MarketSourceSeriesModel.id.in_(
                        UUID(item)
                        for item in historical_value_from_json(
                            session.scalars(
                                select(HistoricalPolicyModel).where(
                                    HistoricalPolicyModel.broker_account_id == case.account_id
                                )
                            )
                            .one()
                            .canonical_policy,
                            HistoricalPolicyRegistration,
                        ).price_series_ids
                    )
                )
                .order_by(MarketDataInstrumentModel.id)
            )
            assert mapping is not None
            ticker, currency, instrument = (
                mapping.provider_key,
                mapping.currency,
                mapping.instrument_id,
            )
        economic = datetime.combine(DAY, datetime.min.time(), UTC) + timedelta(hours=12)

        async def observe(quantity: str, ticker_key: str = ticker) -> UUID:
            return await ingest(
                case,
                ingestion.IngestionCapability.HISTORICAL_ORDERS,
                ingestion.SourceRecord(
                    provider_record_id="explicit-order-fill",
                    source_timestamp=economic,
                    observed_at=datetime.now(UTC),
                    payload={
                        "order": {
                            "id": "explicit-order",
                            "ticker": ticker_key,
                            "side": "BUY",
                            "currency": currency,
                        },
                        "fill": {
                            "id": "explicit-fill",
                            "timestamp": economic,
                            "quantity": Decimal(quantity),
                            "price": Decimal("10"),
                            "walletImpact": {
                                "netValue": -Decimal(quantity) * 10,
                                "currency": currency,
                                "taxes": Decimal("0"),
                            },
                        },
                    },
                    schema_version="revision-capture-v1",
                ),
            )

        old = await observe("1")
        new = await observe("2")
        proof = await register(case, new, old)
        store = PostgresHistoricalStore(case.sessions, cursor_signing_key=CURSOR_KEY)
        captured = await store.capture(
            case.principal, str(case.account_id), request=request(case, datetime.now(UTC))
        )
        candidates = [
            item
            for item in captured.input.event_candidates
            if item.identity.source_record_id in {str(old), str(new)}
        ]
        assert len(candidates) == 2 and all(
            isinstance(item, h.HistoricalExecution) for item in candidates
        )
        assert all(event_revision_key(item) == proof.economic_key for item in candidates)
        selected, ambiguous = selected_events(
            captured.input, captured.input.selection.window.source_cutoff_at
        )
        assert not ambiguous
        winner = next(item for item in selected if item.identity.source_record_id == str(new))
        assert isinstance(winner, h.HistoricalExecution)
        assert winner.quantity == Decimal("2") and winner.instrument_id == str(instrument)
        assert winner.identity.supersedes_revision_id == str(old)
        assert str(old) not in {item.identity.source_record_id for item in selected}
        assert any(
            ref.kind == "activity_revision_evidence" and ref.id == str(proof.registration.id)
            for ref in captured.input.sources
        )
        alert, outcome = matrix.capture(version)
        assert outcome.outcome not in {
            a.AlertEvaluationOutcome.FAILED,
            a.AlertEvaluationOutcome.UNAVAILABLE,
        }
        assert (
            isinstance(alert.payload, a.AlertThresholdInput)
            and alert.payload.observation.observed.value == 0
        )
        assert any(
            ref.kind is ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            and ref.subject_id == proof.registration.id
            for ref in alert.source_references
        )
        assert any(binding.subject_id == new for binding in alert.canonical_bindings)
        # A raw order with no usable mapping must not acquire a permanently inapplicable proof.
        unmatched = await observe("3", "UNMAPPED_EXPLICIT_FILL")
        with pytest.raises(revision.ActivityRevisionError) as error:
            await register(case, unmatched, new)
        assert error.value.code is revision.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT

    asyncio.run(run())


def test_period_capture_keeps_later_correcting_group_and_original_cutoff_bytes(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    async def run() -> None:
        case = history_report_case(*seeded_history)
        matrix = Matrix(case.sessions, case.principal, case.account_id, CURSOR_KEY)
        version = await matrix.activate(predicate(a.AlertMetric.POSITIVE_DIVIDEND))
        store = PostgresHistoricalStore(case.sessions, cursor_signing_key=CURSOR_KEY)

        async def observe(day: date, key: str = "period-date-correction") -> UUID:
            at = datetime.combine(day, datetime.min.time(), UTC)
            return await ingest(
                case,
                ingestion.IngestionCapability.DIVIDENDS,
                ingestion.SourceRecord(
                    provider_record_id=key,
                    source_timestamp=at,
                    observed_at=datetime.now(UTC),
                    payload={
                        "reference": key,
                        "paidOn": day,
                        "amount": Decimal("7"),
                        "currency": "EUR",
                    },
                    schema_version="revision-capture-v1",
                ),
            )

        old = await observe(DAY)
        original_request = request(case, datetime.now(UTC))
        original = await store.capture(
            case.principal, str(case.account_id), request=original_request
        )
        original_bytes = canonical_json(original.input).encode()
        assert any(
            item.identity.source_record_id == str(old)
            for item in selected_events(original.input, original_request.window.source_cutoff_at)[0]
        )
        new = await observe(DAY + timedelta(days=1))
        unrelated = await observe(DAY + timedelta(days=1), "unrelated-post-period")
        conflicted = await store.capture(
            case.principal, str(case.account_id), request=request(case, datetime.now(UTC))
        )
        assert selected_events(
            conflicted.input, conflicted.input.selection.window.source_cutoff_at
        )[1]
        assert str(unrelated) not in {
            item.identity.source_record_id for item in conflicted.input.event_candidates
        }
        proof = await register(case, new, old)
        corrected = await store.capture(
            case.principal, str(case.account_id), request=request(case, datetime.now(UTC))
        )
        selected, ambiguous = selected_events(
            corrected.input, corrected.input.selection.window.source_cutoff_at
        )
        assert not ambiguous
        winner = next(item for item in selected if item.identity.source_record_id == str(new))
        assert winner.identity.economic_at == corrected.input.selection.window.end_at
        assert str(old) not in {item.identity.source_record_id for item in selected}
        assert not any(
            item.identity.source_record_id in {str(old), str(new)}
            for item in selected
            if item.identity.economic_at < corrected.input.selection.window.end_at
        )
        refs = {(ref.kind, ref.id) for ref in corrected.input.sources}
        assert {
            ("broker_source_record", str(old)),
            ("broker_source_record", str(new)),
            ("activity_revision_evidence", str(proof.registration.id)),
        } <= refs
        assert ("broker_source_record", str(unrelated)) not in refs
        replay = await store.capture(case.principal, str(case.account_id), request=original_request)
        assert replay.id == original.id and canonical_json(replay.input).encode() == original_bytes
        alert, outcome = matrix.capture(version)
        assert isinstance(alert.payload, a.AlertEventBatchInput) and outcome.decision is True
        events = [item for item in alert.payload.events if item.revision_id in {old, new}]
        assert len(events) == 1 and events[0].revision_id == new
        assert (
            events[0].correction_of == old
            and events[0].first_eligible_at == proof.first_observed_at
        )

    asyncio.run(run())
