"""Portfolio reachability excludes unrelated expired enrichment and preserves gaps."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import pytest
from trading212_application import source_providers as ports
from trading212_application import xray as app
from trading212_application.xray_ingestion import (
    EconomicEntityRegistration,
    EntityEvidenceRegistration,
    EntityMappingRegistration,
    EntityRelationshipRegistration,
    ShareClassRegistration,
)
from trading212_domain import xray as d
from trading212_domain.sources import SourceLicense, SourceProvenance
from trading212_domain.xray_codec import decode_xray_input
from trading212_persistence.models import InstrumentModel, PortfolioSnapshotModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_capture_base import XrayCaptureState
from trading212_persistence.xray_capture_catalog import _catalog_scope
from trading212_persistence.xray_run_models import XrayInputSnapshotModel
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, XRAY_EFFECTIVE, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _instrument(case: XrayReadCase) -> str:
    identifier = uuid4()
    with case.sessions() as session, session.begin():
        session.add(
            InstrumentModel(
                id=identifier,
                canonical_name="Synthetic unrelated catalog instrument",
                instrument_type="equity",
                isin=None,
            )
        )
    return str(identifier)


def _captured(case: XrayReadCase, identifier: str) -> d.XrayInput:
    with case.sessions() as session:
        row = session.get(XrayInputSnapshotModel, UUID(identifier))
        assert row is not None
        return decode_xray_input(row.canonical_input)


async def _empty_classifications(
    case: XrayReadCase,
    instruments: tuple[str, ...],
    license: SourceLicense,
) -> str:
    request = ports.ClassificationRequest(
        instrument_ids=instruments,
        taxonomy="synthetic-xray-sector",
        taxonomy_version="1",
        source_cutoff_at=case.now[0],
    )
    page = ports.ClassificationPage(
        request=request,
        provenance=SourceProvenance(
            provider_id=license.provider_id,
            license_version_id=license.id,
            adapter_version="synthetic-catalog-scope-v1",
            schema_version="xray-fixture-v1",
            source_revision="synthetic-catalog-gap-2",
            revision_order=2,
            effective_at=case.now[0],
            first_observed_at=case.now[0],
            synthetic=True,
        ),
        observations=(),
    )
    receipt = await case.service.ingest_classifications(
        case.principal,
        request,
        (page,),
        idempotency_key="catalog-scope:classification",
        correlation_id="catalog-scope",
    )
    return receipt.id


async def _expired_evidence(
    case: XrayReadCase,
    family: Literal["entity", "classification"],
    instrument: str,
) -> str:
    case.now[0] = XRAY_AT - timedelta(days=3)
    license = replace(
        xray_license(),
        id=str(uuid4()),
        version="synthetic-one-day-scope-test",
        effective_at=case.now[0],
        retention_days=1,
    )
    source = PostgresSourceService(
        sessions=case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.now[0],
    )
    await source.register_source_license(
        case.principal,
        license,
        idempotency_key="catalog-scope:license",
        correlation_id="catalog-scope",
    )
    if family == "classification":
        result = await _empty_classifications(case, (instrument,), license)
    else:
        entity = str(uuid4())
        receipt = await case.service.register_entity_evidence(
            case.principal,
            EntityEvidenceRegistration(
                id=str(uuid4()),
                key="synthetic-catalog-scope-entities",
                provider_id=license.provider_id,
                license_version_id=license.id,
                revision=1,
                effective_at=case.now[0],
                valid_until=None,
                entities=(
                    EconomicEntityRegistration(
                        id=entity,
                        key="synthetic-catalog-scope-entity",
                        display_name="Synthetic catalog scope entity",
                    ),
                ),
                mappings=(
                    EntityMappingRegistration(
                        id=str(uuid4()),
                        instrument_id=instrument,
                        entity_id=entity,
                        listing_id=None,
                        effective_at=case.now[0],
                        valid_until=None,
                        confidence=Decimal("1"),
                    ),
                ),
            ),
            idempotency_key="catalog-scope:entity",
            correlation_id="catalog-scope",
        )
        result = receipt.id
    case.now[0] = XRAY_AT
    return result


@pytest.mark.parametrize("family", ["entity", "classification"])
@pytest.mark.parametrize("relevant", [False, True])
def test_expired_enrichment_denies_only_a_reachable_subject(
    xray_read_case: XrayReadCase,
    family: Literal["entity", "classification"],
    relevant: bool,
) -> None:
    case = xray_read_case
    instrument = xray_id("instrument/alpha-a") if relevant else _instrument(case)
    expired = asyncio.run(_expired_evidence(case, family, instrument))
    if relevant:
        with pytest.raises(app.XrayServiceError) as rejected:
            asyncio.run(company(case))
        assert rejected.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
    else:
        response = asyncio.run(company(case))
        value = _captured(case, response.context.input_snapshot_id)
        assert all(
            str(row.reference.record_id) != expired
            and str(row.reference.parent_record_id) != expired
            for row in value.source_dependencies
        )
        assert response.summary.total.value is not None
        assert response.summary.total.value.amount == Decimal("1000")


def test_new_empty_classification_batch_blocks_older_instrument_assignments(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    instruments = tuple(
        xray_id(f"instrument/{key}") for key in ("alpha-a", "alpha-b", "alpha-adr", "beta")
    )
    identifier = asyncio.run(_empty_classifications(case, instruments, xray_license()))
    response = asyncio.run(
        case.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=app.EffectiveExposureQuery(
                request=case.request(), options=app.Exposures(dimension=d.XrayDimension.SECTOR)
            ),
        )
    )
    assert isinstance(response, app.ExposuresView)
    assert response.dimension_summary.known_weight.value == Decimal("0")
    value = _captured(case, response.context.input_snapshot_id)
    batch = next(row for row in value.classification_batches if str(row.evidence.id) == identifier)
    assert batch.assignments == () and batch.evidence.state is d.XraySourceState.GAP
    assert {str(row.subject_id) for row in batch.requested_subjects} == set(instruments)


def test_issuer_parent_cycle_is_retained_without_equity_consolidation(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    license = xray_license()
    alpha = xray_id("entity/alpha")
    parents = (str(uuid4()), str(uuid4()))
    relation_ids = tuple(str(uuid4()) for _ in range(3))
    registration = EntityEvidenceRegistration(
        id=str(uuid4()),
        key="synthetic-parent-cycle",
        provider_id=license.provider_id,
        license_version_id=license.id,
        revision=1,
        effective_at=XRAY_EFFECTIVE,
        valid_until=None,
        entities=tuple(
            EconomicEntityRegistration(
                id=identifier,
                key=f"synthetic-parent-{ordinal}",
                display_name="Synthetic parent",
            )
            for ordinal, identifier in enumerate(parents)
        ),
        relationships=tuple(
            EntityRelationshipRegistration(
                id=identifier,
                kind="issuer_parent",
                entity_id=child,
                parent_entity_id=parent,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                confidence=Decimal("1"),
            )
            for identifier, (child, parent) in zip(
                relation_ids,
                ((alpha, parents[0]), (parents[0], parents[1]), (parents[1], parents[0])),
                strict=True,
            )
        ),
    )
    asyncio.run(
        case.service.register_entity_evidence(
            case.principal,
            registration,
            idempotency_key="catalog-scope:parent-cycle",
            correlation_id="catalog-scope",
        )
    )
    response = asyncio.run(company(case))
    value = _captured(case, response.context.input_snapshot_id)
    assert set(relation_ids).issubset({str(row.evidence.id) for row in value.relationship_versions})
    assert all(row.bucket_key not in parents for row in response.exposures.items)
    alpha_row = next(row for row in response.exposures.items if row.bucket_key == alpha)
    assert alpha_row.effective.value is not None
    assert alpha_row.effective.value.amount == Decimal("560")


def test_receipt_underlying_and_share_class_extend_the_metadata_scope(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    response = asyncio.run(company(case))
    value = _captured(case, response.context.input_snapshot_id)
    receipt, underlying = _instrument(case), _instrument(case)
    receipt_entity, share_entity = str(uuid4()), str(uuid4())
    share_id = str(uuid4())
    license = xray_license()
    registration = EntityEvidenceRegistration(
        id=str(uuid4()),
        key="synthetic-receipt-scope",
        provider_id=license.provider_id,
        license_version_id=license.id,
        revision=1,
        effective_at=XRAY_EFFECTIVE,
        valid_until=None,
        entities=tuple(
            EconomicEntityRegistration(
                id=identifier,
                key=f"synthetic-receipt-entity-{ordinal}",
                display_name="Synthetic receipt scope entity",
            )
            for ordinal, identifier in enumerate((receipt_entity, share_entity))
        ),
        share_classes=(
            ShareClassRegistration(
                id=share_id,
                instrument_id=underlying,
                entity_id=share_entity,
                class_key="synthetic-underlying-share",
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                confidence=Decimal("1"),
            ),
        ),
        relationships=(
            EntityRelationshipRegistration(
                id=str(uuid4()),
                kind="depositary_receipt_of",
                instrument_id=receipt,
                underlying_instrument_id=underlying,
                entity_id=receipt_entity,
                units_per_receipt=Decimal("2"),
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                confidence=Decimal("1"),
            ),
            EntityRelationshipRegistration(
                id=str(uuid4()),
                kind="share_class_of",
                instrument_id=underlying,
                share_class_id=share_id,
                entity_id=share_entity,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                confidence=Decimal("1"),
            ),
        ),
    )
    asyncio.run(
        case.service.register_entity_evidence(
            case.principal,
            registration,
            idempotency_key="catalog-scope:receipt",
            correlation_id="catalog-scope",
        )
    )
    with case.sessions() as session:
        snapshot = session.get(PortfolioSnapshotModel, value.snapshot_id)
        assert snapshot is not None
        state = XrayCaptureState(UUID(case.principal.owner_id), snapshot, XRAY_AT, value.policy)
        scope = _catalog_scope(session, state, {UUID(receipt)}, set())
        assert {UUID(receipt), UUID(underlying)}.issubset(scope.instruments)
        assert {UUID(receipt_entity), UUID(share_entity)}.issubset(scope.entities)
