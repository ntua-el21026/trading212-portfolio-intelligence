"""Source maintenance also schedules licensed enrichment purge without blocking."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from trading212_application.xray_ingestion import (
    EconomicEntityRegistration,
    EntityEvidenceRegistration,
    FundDefinitionRegistration,
)
from trading212_domain import build_synthetic_identity
from trading212_persistence.phase2_retention_models import Phase2RetentionSweepModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.xray_catalog_models import (
    EntityEvidenceReferenceModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
)
from trading212_persistence.xray_enrichment_retention import expire_enrichment_payloads
from trading212_persistence.xray_lifecycle_models import (
    EnrichmentExpiryEventModel,
    EnrichmentRetentionWorkModel,
)
from trading212_persistence.xray_service import PostgresXrayService

from tests.integration.test_source_retention_dispatch_postgres import run_dispatcher_once
from tests.integration.test_sources_postgres import KEY, Case, source_case
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("held_lock", ["sources", "xray", "row"])
def test_busy_enrichment_retains_payload_then_resumes_on_next_dispatch_cycle(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
    held_lock: str,
) -> None:
    case = xray_read_case
    with case.sessions() as session:
        source = session.scalar(
            select(EntityEvidenceVersionModel).order_by(EntityEvidenceVersionModel.id).limit(1)
        )
        assert source is not None and source.confidence is None
        identifier, owner, digest = source.id, source.owner_id, source.content_digest
        at = source.expires_at + timedelta(seconds=1)
        references = (
            select(EntityEvidenceReferenceModel)
            .where(
                EntityEvidenceReferenceModel.owner_id == owner,
                EntityEvidenceReferenceModel.evidence_version_id == identifier,
                EntityEvidenceReferenceModel.kind == "entity",
            )
            .order_by(EntityEvidenceReferenceModel.id)
        )
        payload = [(row.id, row.display_name) for row in session.scalars(references)]
        assert payload and all(display_name is not None for _, display_name in payload)
    with case.sessions.begin() as blocker:
        if held_lock == "row":
            assert (
                blocker.scalar(
                    select(EntityEvidenceVersionModel)
                    .where(EntityEvidenceVersionModel.id == identifier)
                    .with_for_update()
                )
                is not None
            )
        else:
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"{held_lock}:{owner}"},
            )
        run_dispatcher_once(monkeypatch, case.engine, at=at)
        with case.sessions() as session:
            source = session.get(EntityEvidenceVersionModel, identifier)
            assert source is not None and source.content_digest == digest
            assert source.confidence is None
            assert [(row.id, row.display_name) for row in session.scalars(references)] == payload
            assert (
                session.scalar(
                    select(EnrichmentExpiryEventModel.id).where(
                        EnrichmentExpiryEventModel.entity_evidence_version_id == identifier
                    )
                )
                is None
            )
    # Bounded passes may first finish other expired sources from the real fixture.
    for _ in range(32):
        run_dispatcher_once(monkeypatch, case.engine, at=at)
        with case.sessions() as session:
            complete = session.scalar(
                select(EnrichmentExpiryEventModel).where(
                    EnrichmentExpiryEventModel.entity_evidence_version_id == identifier
                )
            )
            if complete is not None:
                assert complete.content_digest == digest
                source = session.get(EntityEvidenceVersionModel, identifier)
                assert source is not None and source.content_digest == digest
                assert source.confidence is None
                assert [(row.id, row.display_name) for row in session.scalars(references)] == [
                    (identifier, None) for identifier, _ in payload
                ]
                break
    else:
        pytest.fail("Enrichment maintenance did not complete its bounded pending work.")


async def _register_enrichment_prefix(case: Case, *, count: int, identifier_start: int) -> None:
    """Register payload-bearing evidence and funds with ordinary owner/license guards."""
    service = PostgresXrayService(
        sessions=case.sessions, cursor_signing_key=KEY, clock=lambda: case.now[0]
    )
    entity = EconomicEntityRegistration(
        id=str(uuid4()), key="retention-prefix-entity", display_name="Retained prefix entity"
    )
    instrument_id = str(build_synthetic_identity().instrument.id)
    for revision in range(1, count + 1):
        await service.register_entity_evidence(
            case.principal,
            EntityEvidenceRegistration(
                id=str(UUID(int=identifier_start + 2 * revision)),
                key="retention-prefix-evidence",
                provider_id=case.series.provider_id,
                license_version_id=case.license.id,
                revision=revision,
                effective_at=case.pages[0].provenance.effective_at,
                valid_until=None,
                entities=(entity,),
            ),
            idempotency_key=f"prefix-evidence-{revision}",
            correlation_id="enrichment-prefix-test",
        )
        await service.register_fund_definition(
            case.principal,
            FundDefinitionRegistration(
                id=str(UUID(int=identifier_start + 2 * revision + 1)),
                key="retention-prefix-fund",
                instrument_id=instrument_id,
                fund_type="etf",
                provider_id=case.series.provider_id,
                license_version_id=case.license.id,
                revision=revision,
                effective_at=case.pages[0].provenance.effective_at,
                valid_until=None,
                evidence_key="synthetic-retention-prefix",
                confidence=Decimal("0.9"),
            ),
            idempotency_key=f"prefix-fund-{revision}",
            correlation_id="enrichment-prefix-test",
        )


@pytest.mark.parametrize("held_lock", ["sources", "xray"])
def test_busy_owner_prefix_preserves_budget_for_other_owners_across_enrichment_families(
    xray_read_case: XrayReadCase, held_lock: str
) -> None:
    sessions = xray_read_case.sessions
    # One payload mutation reserves 64 inspections, before marker/phase/probe
    # costs. Keep the insufficient-budget probe separate from fairness work.
    allowance, prefix_size = 256, 257

    async def arrange() -> tuple[Case, Case, datetime]:
        busy = await source_case(sessions, retention_days=1)
        free = await source_case(sessions, retention_days=1)
        await _register_enrichment_prefix(busy, count=prefix_size, identifier_start=0)
        free.now[0] += timedelta(seconds=1)
        await _register_enrichment_prefix(free, count=1, identifier_start=1 << 127)
        return busy, free, free.now[0] + timedelta(days=2)

    busy, free, at = asyncio.run(arrange())
    busy_owner, free_owner = UUID(busy.principal.owner_id), UUID(free.principal.owner_id)
    owners = (busy_owner, free_owner)
    families = (
        (EntityEvidenceVersionModel, "entity_evidence_version_id"),
        (FundDefinitionModel, "fund_definition_id"),
    )
    before: dict[UUID, tuple[str, datetime, datetime]] = {}
    with sessions() as session:
        for model, _ in families:
            rows = list(session.scalars(select(model).where(model.owner_id.in_(owners))))
            assert len(rows) == prefix_size + 1
            busy_expiries = [row.expires_at for row in rows if row.owner_id == busy_owner]
            free_expiries = [row.expires_at for row in rows if row.owner_id == free_owner]
            assert len(busy_expiries) == prefix_size and len(free_expiries) == 1
            assert max(busy_expiries) < free_expiries[0] <= at
            # The current physical scan orders UUIDs, independently of expiry.
            assert max(row.id for row in rows if row.owner_id == busy_owner) < min(
                row.id for row in rows if row.owner_id == free_owner
            )
            before.update(
                (row.id, (row.content_digest, row.first_observed_at, row.expires_at))
                for row in rows
            )
        references = list(
            session.scalars(
                select(EntityEvidenceReferenceModel).where(
                    EntityEvidenceReferenceModel.owner_id.in_(owners)
                )
            )
        )
        assert len(references) == prefix_size + 1
        assert all(row.display_name == "Retained prefix entity" for row in references)
        assert all(
            fund.fund_type == "etf"
            and fund.evidence_key == "synthetic-retention-prefix"
            and fund.confidence == Decimal("0.9")
            for fund in session.scalars(
                select(FundDefinitionModel).where(FundDefinitionModel.owner_id.in_(owners))
            )
        )

    def payloads() -> tuple[object, ...]:
        with sessions() as session:
            return (
                tuple(
                    session.execute(
                        select(
                            EntityEvidenceReferenceModel.id,
                            EntityEvidenceReferenceModel.display_name,
                            EntityEvidenceReferenceModel.lei,
                            EntityEvidenceReferenceModel.confidence,
                        )
                        .where(EntityEvidenceReferenceModel.owner_id.in_(owners))
                        .order_by(EntityEvidenceReferenceModel.id)
                    )
                ),
                tuple(
                    session.execute(
                        select(
                            FundDefinitionModel.id,
                            FundDefinitionModel.fund_type,
                            FundDefinitionModel.evidence_key,
                            FundDefinitionModel.confidence,
                        )
                        .where(FundDefinitionModel.owner_id.in_(owners))
                        .order_by(FundDefinitionModel.id)
                    )
                ),
            )

    def progress() -> tuple[object, ...]:
        with sessions() as session:
            return (
                tuple(
                    session.execute(
                        select(
                            Phase2RetentionSweepModel.family,
                            Phase2RetentionSweepModel.after_id,
                            Phase2RetentionSweepModel.pending_id,
                        ).order_by(Phase2RetentionSweepModel.family)
                    )
                ),
                tuple(
                    session.execute(
                        select(
                            EnrichmentRetentionWorkModel.id,
                            EnrichmentRetentionWorkModel.phase,
                            EnrichmentRetentionWorkModel.removed_row_count,
                            EnrichmentRetentionWorkModel.completed_at,
                        )
                        .where(EnrichmentRetentionWorkModel.owner_id.in_(owners))
                        .order_by(EnrichmentRetentionWorkModel.id)
                    )
                ),
            )

    def maintain(*, inspections: int = allowance) -> tuple[int, SourcePurgeBudget]:
        before_progress = progress()
        with sessions.begin() as session:
            session.execute(text("SET LOCAL lock_timeout = '200ms'"))
            budget = SourcePurgeBudget(rows_inspected=inspections)
            completed = expire_enrichment_payloads(session, at=at, limit=100, budget=budget)
            assert 0 <= budget.rows_inspected < inspections
            assert 0 <= budget.rows_removed <= 4096
            assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
            assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024
        # Completing an expiry is not required on every physically bounded turn;
        # a zero-completion turn must still persist source/pending-work progress.
        if completed == 0:
            assert progress() != before_progress
        return completed, budget

    with sessions.begin() as blocker:
        blocker.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{held_lock}:{busy_owner}"},
        )
        before_payloads = payloads()
        completed, budget = maintain(inspections=32)
        assert completed == 0
        assert budget.rows_removed == 4096
        assert budget.bytes_removed == budget.bytes_inspected == 64 * 1024 * 1024
        assert payloads() == before_payloads
        with sessions() as session:
            assert (
                session.scalar(
                    select(EnrichmentExpiryEventModel.id).where(
                        EnrichmentExpiryEventModel.owner_id.in_(owners)
                    )
                )
                is None
            )
        free_completed = 0
        for _ in range(64):
            completed, _ = maintain()
            assert 0 <= completed <= len(families) - free_completed
            free_completed += completed
            with sessions() as session:
                assert (
                    session.scalar(
                        select(EnrichmentRetentionWorkModel.id).where(
                            EnrichmentRetentionWorkModel.owner_id == busy_owner
                        )
                    )
                    is None
                )
            if free_completed == len(families):
                break
        assert free_completed == len(families)
        with sessions() as session:
            assert (
                session.scalar(
                    select(EnrichmentRetentionWorkModel.id).where(
                        EnrichmentRetentionWorkModel.owner_id == busy_owner
                    )
                )
                is None
            )
            for _, reference in families:
                events = list(
                    session.scalars(
                        select(EnrichmentExpiryEventModel).where(
                            EnrichmentExpiryEventModel.owner_id.in_(owners),
                            getattr(EnrichmentExpiryEventModel, reference).is_not(None),
                        )
                    )
                )
                assert len(events) == 1 and events[0].owner_id == free_owner
                identifier = getattr(events[0], reference)
                assert events[0].content_digest == before[identifier][0]
                assert events[0].expired_at == at
                assert events[0].removed_row_count == 1
            for entity_reference in session.scalars(
                select(EntityEvidenceReferenceModel).where(
                    EntityEvidenceReferenceModel.owner_id.in_(owners)
                )
            ):
                expected = (
                    "Retained prefix entity" if entity_reference.owner_id == busy_owner else None
                )
                assert entity_reference.display_name == expected
            for fund in session.scalars(
                select(FundDefinitionModel).where(FundDefinitionModel.owner_id.in_(owners))
            ):
                expected_fund = (
                    ("etf", "synthetic-retention-prefix", Decimal("0.9"))
                    if fund.owner_id == busy_owner
                    else (None, None, None)
                )
                assert (fund.fund_type, fund.evidence_key, fund.confidence) == expected_fund
        completed, budget = maintain()
        assert completed == 0
        assert budget.rows_removed == 4096
        assert budget.bytes_removed == 64 * 1024 * 1024

    remaining = prefix_size * len(families)
    for _ in range(4 * remaining):
        completed, _ = maintain()
        assert 0 <= completed <= remaining
        remaining -= completed
        if remaining == 0:
            break
    assert remaining == 0
    with sessions() as session:
        for model, reference in families:
            rows = list(session.scalars(select(model).where(model.owner_id.in_(owners))))
            assert len(rows) == prefix_size + 1
            assert all(
                (row.content_digest, row.first_observed_at, row.expires_at) == before[row.id]
                for row in rows
            )
            events = list(
                session.scalars(
                    select(EnrichmentExpiryEventModel).where(
                        EnrichmentExpiryEventModel.owner_id.in_(owners),
                        getattr(EnrichmentExpiryEventModel, reference).is_not(None),
                    )
                )
            )
            assert {getattr(event, reference) for event in events} == {row.id for row in rows}
            assert all(
                event.content_digest == before[getattr(event, reference)][0]
                and event.expired_at == at
                and event.removed_row_count == 1
                for event in events
            )
        assert all(
            entity_reference.display_name is None
            for entity_reference in session.scalars(
                select(EntityEvidenceReferenceModel).where(
                    EntityEvidenceReferenceModel.owner_id.in_(owners)
                )
            )
        )
        assert all(
            fund.fund_type is None and fund.evidence_key is None and fund.confidence is None
            for fund in session.scalars(
                select(FundDefinitionModel).where(FundDefinitionModel.owner_id.in_(owners))
            )
        )
