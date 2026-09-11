"""Real broker ingestion retains relevant revisions without unrelated ambiguity or FX gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_application import activity_revisions as revision
from trading212_application import ingestion
from trading212_domain import alerts as d
from trading212_domain.historical import HistoricalCashFlowKind
from trading212_domain.reports import ReportSourceKind
from trading212_persistence.activity_revision_store import PostgresActivityRevisionStore
from trading212_persistence.models import SourceRecordModel
from trading212_worker.postgres_store import PostgresIngestionStore

from tests.integration.test_alert_capture_matrix_postgres import Matrix
from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.unit.analytics.alert_factories import predicate

pytestmark = pytest.mark.integration


class Broker:
    def __init__(self) -> None:
        self.rows: dict[ingestion.IngestionCapability, tuple[ingestion.SourceRecord, ...]] = {}

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: ingestion.IngestionCapability,
        checkpoint: ingestion.Checkpoint | None,
        correlation_id: str,
    ) -> ingestion.SourcePage:
        return ingestion.SourcePage(self.rows.get(capability, ()), None, True)


def dividend(reference: str, amount: str) -> ingestion.SourceRecord:
    now = datetime.now(UTC)
    return ingestion.SourceRecord(
        reference,
        now,
        now,
        {
            "reference": reference,
            "paidOn": (now - timedelta(days=1)).date(),
            "amount": Decimal(amount),
            "currency": "EUR",
        },
        "alert-relevant-event-v1",
    )


def test_real_ingestion_ignores_old_conflict_and_wrong_kind_fx_but_keeps_relevant_correction(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        matrix = Matrix(report_case.base.sessions, report_case.principal, report_case.account_id)
        broker = Broker()
        coordinator = ingestion.IngestionCoordinator(
            provider=broker, store=PostgresIngestionStore(matrix.sessions, provider="synthetic")
        )

        async def ingest() -> ingestion.IngestionRun:
            value = await coordinator.refresh(
                owner_id=matrix.principal.owner_id,
                account_id=str(matrix.account_id),
                mode=ingestion.RunMode.FULL,
                idempotency_key=uuid4().hex,
                capabilities=ingestion.HISTORY_REFRESH_ORDER,
                correlation_id="alert-event-selection",
            )
            assert value.status is ingestion.RunStatus.SUCCEEDED
            return value

        # Both genuine old revisions are known before activation. Neither their
        # economic time nor their first knowledge belongs to this live window.
        for amount in ("2", "3"):
            broker.rows = {ingestion.IngestionCapability.DIVIDENDS: (dividend("old", amount),)}
            await ingest()
        dividend_version = await matrix.activate(predicate(d.AlertMetric.POSITIVE_DIVIDEND))
        count_version = await matrix.activate(
            replace(
                predicate(d.AlertMetric.ACTIVITY_COUNT),
                activity_kind=HistoricalCashFlowKind.DEPOSIT,
            )
        )
        flow_version = await matrix.activate(
            replace(
                predicate(d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT),
                activity_kind=HistoricalCashFlowKind.DEPOSIT,
            )
        )
        all_flow_version = await matrix.activate(
            predicate(d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT)
        )
        now = datetime.now(UTC)
        broker.rows = {
            ingestion.IngestionCapability.DIVIDENDS: (dividend("current", "4"),),
            ingestion.IngestionCapability.TRANSACTIONS: tuple(
                ingestion.SourceRecord(
                    reference,
                    now,
                    now,
                    {
                        "reference": reference,
                        "dateTime": now,
                        "amount": Decimal(amount),
                        "currency": currency,
                        "type": kind,
                    },
                    "alert-relevant-event-v1",
                )
                for reference, amount, currency, kind in (
                    ("deposit", "10", "EUR", "DEPOSIT"),
                    ("withdrawal", "-50", "USD", "WITHDRAW"),
                )
            ),
        }
        first = await ingest()
        value, result = matrix.capture(dividend_version)
        assert isinstance(value.payload, d.AlertEventBatchInput) and result.decision is True
        assert len(value.payload.events) == 1
        previous = value.payload.events[0].revision_id
        assert previous is not None and value.payload.events[0].net_amount is not None
        assert value.payload.events[0].net_amount.amount == Decimal("4")
        count, _ = matrix.capture(count_version)
        assert isinstance(count.payload, d.AlertThresholdInput)
        assert count.payload.observation.observed.value == 1
        flow, outcome = matrix.capture(flow_version)
        assert isinstance(flow.payload, d.AlertEventBatchInput) and outcome.decision is True
        assert len(flow.payload.events) == 1 and flow.fx_conversions == ()
        assert flow.payload.events[0].activity_kind is HistoricalCashFlowKind.DEPOSIT
        assert flow.payload.events[0].observation.observed.value == Decimal("10")
        assert not flow.payload.complete  # Complete-ledger coverage is unchanged.
        _, unavailable = matrix.capture(all_flow_version)
        assert unavailable.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
        assert unavailable.reason is d.AlertReason.MISSING_FX

        before_correction = datetime.now(UTC)
        broker.rows = {ingestion.IngestionCapability.DIVIDENDS: (dividend("current", "5"),)}
        corrected = await ingest()
        _, ambiguous = matrix.capture(dividend_version)
        assert ambiguous.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
        assert ambiguous.reason is d.AlertReason.AMBIGUOUS_SOURCE
        with matrix.sessions() as session:
            old = session.get_one(SourceRecordModel, previous)
            assert old.ingestion_run_id == UUID(first.id)
            new = session.scalar(
                select(SourceRecordModel).where(
                    SourceRecordModel.ingestion_run_id == UUID(corrected.id),
                    SourceRecordModel.capability == "historical_dividends",
                )
            )
            assert new is not None
            revised = new.id
        evidence = await PostgresActivityRevisionStore(matrix.sessions).register_activity_revision(
            matrix.principal,
            matrix.account_id,
            revision.ActivityRevisionRegistration(
                id=uuid4(),
                new_source_record_id=revised,
                superseded_source_record_id=previous,
                authority=revision.ActivityRevisionAuthority.OWNER_ATTESTATION,
                evidence_key="reviewed-synthetic-event-correction",
            ),
            idempotency_key=uuid4().hex,
            correlation_id="alert-event-selection",
        )
        current, result = matrix.capture(dividend_version)
        assert isinstance(current.payload, d.AlertEventBatchInput) and result.decision is True
        assert len(current.payload.events) == 1
        event = current.payload.events[0]
        assert (event.revision_id, event.correction_of) == (revised, previous)
        assert event.first_eligible_at == evidence.first_observed_at
        assert event.economic_at < current.observation_window.start_at
        assert event.net_amount is not None and event.net_amount.amount == Decimal("5")
        assert any(
            ref.kind is ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            and ref.subject_id == evidence.registration.id
            and ref.content_digest == evidence.content_digest
            for ref in current.source_references
        )
        earlier, _ = matrix.capture(dividend_version, cutoff=before_correction)
        assert isinstance(earlier.payload, d.AlertEventBatchInput)
        assert [item.revision_id for item in earlier.payload.events] == [previous]
        assert all(
            ref.kind is not ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            for ref in earlier.source_references
        )

    asyncio.run(run())
