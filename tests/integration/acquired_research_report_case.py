"""Current acquired FX, real X-ray and exact research report fixtures without HTTP."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_application import xray as xray_app
from trading212_application.ingestion import (
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
)
from trading212_application.xray_ingestion import XrayPolicyRegistration, XrayTaxonomyRegistration
from trading212_domain.sources import FxSnapshot
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import decode_xray_policy
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel
from trading212_persistence.acquisition_records import AcquisitionCapability
from trading212_persistence.models import PortfolioSnapshotModel, SourceRecordModel
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.xray_catalog_models import XrayPolicyVersionModel
from trading212_persistence.xray_run_models import XrayInputDependencyModel, XrayInputSnapshotModel
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.premium_acquisition_runtime import PostgresPremiumAcquisitionRuntime
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_provider import SyntheticXrayBrokerProvider
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.provider_acquisition_case import AcquisitionCase, acquisition_case
from tests.integration.report_runtime_sources import fresh_report_xray
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import ResearchReportCase
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_provider_publication_postgres import batch
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case


class CurrentXrayBrokerProvider(SyntheticXrayBrokerProvider):
    """A declared new synthetic valuation observation, retaining economic amounts.

    Observation-scoped record identities distinguish this new current response
    from the historical source records. No historical receipt or quote is edited.
    The fixture's explicit synthetic broker quote is re-observed at the same
    exact rate; the separate licensed ECB quote converts EUR reporting to USD.
    """

    def __init__(self, observed_at: datetime) -> None:
        super().__init__()
        self.observed_at = observed_at

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        page = await super().read_page(
            owner_id=owner_id,
            account_id=account_id,
            capability=capability,
            checkpoint=checkpoint,
            correlation_id=correlation_id,
        )
        if capability not in {IngestionCapability.ACCOUNT, IngestionCapability.POSITIONS}:
            return page
        records = []
        prefix = f"current:{self.observed_at.isoformat()}"
        for ordinal, record in enumerate(page.records):
            payload = dict(record.payload)
            wallet = payload.get("walletImpact")
            if isinstance(wallet, Mapping) and isinstance(wallet.get("fxRate"), Mapping):
                quote = dict(wallet["fxRate"])
                assert quote["rate"] == Decimal("0.8")
                payload["walletImpact"] = {
                    **wallet,
                    "fxRate": {**quote, "observedAt": self.observed_at},
                }
            records.append(
                replace(
                    record,
                    provider_record_id=f"{prefix}:{record.provider_record_id or ordinal}",
                    source_timestamp=self.observed_at,
                    observed_at=self.observed_at,
                    payload=payload,
                    schema_version=f"synthetic-current-xray-v1:{capability.value}",
                )
            )
        return replace(page, records=tuple(records))


@dataclass(frozen=True)
class AcquiredResearchReportCase:
    report: ResearchReportCase
    acquisition: AcquisitionCase
    fx: FxSnapshot
    xray: xray_app.ExposuresView
    catalogue_provider_ids: tuple[str, ...]


def _report_only_fx_authority(case: AcquisitionCase, *, restriction: str = "allowed") -> None:
    """Append valid authority; CSV/XLSX report copies cannot rely on EXPORT."""
    at = datetime.now(UTC)
    with case.xray.sessions() as session, session.begin():
        original = case.grant
        pinned = session.get_one(ProviderLicenseVersionModel, original.license_version_id)
        license = ProviderLicenseVersionModel(
            id=uuid4(),
            owner_id=pinned.owner_id,
            provider_id=pinned.provider_id,
            version_number=pinned.version_number + 1,
            version="acquired-report-only-2",
            effective_at=at,
            store_permission="allowed",
            display_permission="allowed",
            report_permission="denied" if restriction == "pinned_license" else "allowed",
            export_permission="denied",
            retention_days=pinned.retention_days,
            attribution=pinned.attribution,
            evidence_key="synthetic-acquired-report-only",
            created_at=at,
        )
        session.add(license)
        session.flush()
        grant = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=original.owner_id,
            provider_id=original.provider_id,
            scope_id=original.scope_id,
            version_number=original.version_number + 1,
            license_version_id=license.id,
            effective_at=at,
            expires_at=original.expires_at,
            store_allowed=True,
            display_allowed=True,
            report_allowed=restriction != "pinned_grant",
            export_allowed=False,
            daily_allowance=original.daily_allowance,
            evidence_key="synthetic-acquired-report-only",
            content_digest="0" * 64,
            created_at=at,
        )
        grant.content_digest = grant_digest(grant)
        session.add(grant)
        session.flush()
        session.expunge(grant)
        case.grant = grant


async def _current_valuation(case: XrayReadCase) -> XrayReadCase:
    with case.sessions() as session:
        originals = tuple(
            tuple(row)
            for row in session.execute(
                select(
                    SourceRecordModel.id,
                    SourceRecordModel.source_updated_at,
                    SourceRecordModel.observed_at,
                    SourceRecordModel.payload_fingerprint,
                    SourceRecordModel.sanitized_payload,
                ).order_by(SourceRecordModel.id)
            )
        )
    case.now[0] = max(case.now[0], datetime.now(UTC))
    observed_at = case.now[0]
    receipt = await IngestionCoordinator(
        provider=CurrentXrayBrokerProvider(observed_at),
        store=PostgresIngestionStore(
            case.sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: observed_at,
    ).refresh(
        owner_id=case.principal.owner_id,
        account_id=XRAY_ACCOUNT_ID,
        mode=RunMode.FULL,
        idempotency_key=f"acquired-fx-valuation:{uuid4().hex}",
        correlation_id="acquired-fx-valuation",
    )
    assert receipt.status is RunStatus.SUCCEEDED
    with case.sessions() as session:
        current = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.broker_account_id == UUID(XRAY_ACCOUNT_ID),
                PortfolioSnapshotModel.valuation_at == observed_at,
            )
        )
        assert current is not None and str(current.id) != case.seed["snapshot_id"]
        assert current.reporting_currency == "EUR" and current.portfolio_total == Decimal("1000")
        assert current.source_cutoff_at == observed_at
        retained = tuple(
            tuple(row)
            for row in session.execute(
                select(
                    SourceRecordModel.id,
                    SourceRecordModel.source_updated_at,
                    SourceRecordModel.observed_at,
                    SourceRecordModel.payload_fingerprint,
                    SourceRecordModel.sanitized_payload,
                )
                .where(SourceRecordModel.id.in_(tuple(row[0] for row in originals)))
                .order_by(SourceRecordModel.id)
            )
        )
        assert retained == originals
        snapshot_id = str(current.id)
    return replace(
        case,
        seed={**case.seed, "snapshot_id": snapshot_id, "source_cutoff_at": observed_at.isoformat()},
    )


async def select_fx_policy(
    case: XrayReadCase,
    basis: xray_app.ExposuresView,
    providers: tuple[str, ...],
) -> xray_app.ExposuresView:
    """Append a legitimate policy and compute a new USD run at a legal cutoff."""
    with case.sessions() as session:
        captured = session.get_one(XrayInputSnapshotModel, UUID(basis.context.input_snapshot_id))
        stored = session.get_one(XrayPolicyVersionModel, captured.policy_id)
        original = decode_xray_policy(stored.canonical_policy)
    policy = replace(
        original,
        id=uuid4(),
        version=f"acquired-fx-{uuid4().hex}",
        provider_selection_policy=replace(
            original.provider_selection_policy, id=uuid4(), provider_order=providers
        ),
    )
    case.now[0] = max(case.now[0], datetime.now(UTC))
    await case.service.register_xray_policy(
        case.principal,
        XRAY_ACCOUNT_ID,
        XrayPolicyRegistration(
            key=f"acquired-fx-{policy.id}",
            effective_at=basis.context.valuation_at,
            policy=policy,
            taxonomies=tuple(
                XrayTaxonomyRegistration(
                    id=str(t.taxonomy_id), dimension=t.dimension, key=t.key, version=t.version
                )
                for t in policy.taxonomy_versions
            ),
        ),
        idempotency_key=f"acquired-fx-policy:{policy.id}",
        correlation_id="acquired-fx-policy",
    )
    case.now[0] = max(case.now[0], datetime.now(UTC))
    result = await case.service.get_effective_exposure(
        case.principal,
        XRAY_ACCOUNT_ID,
        query=xray_app.EffectiveExposureQuery(
            request=replace(
                case.request(),
                source_cutoff_at=case.now[0],
                currency=xray_app.ExplicitCurrency(reporting_currency=CurrencyCode("USD")),
            )
        ),
    )
    assert isinstance(result, xray_app.ExposuresView)
    return result


async def research_item_for_run(
    original: ResearchReportCase,
    xray_case: XrayReadCase,
    run: xray_app.ExposuresView,
) -> ResearchReportCase:
    research = replace(original.research, xray=xray_case, run_id=UUID(run.context.run_id))
    research.xray.now[0] = max(research.xray.now[0], datetime.now(UTC)) + timedelta(microseconds=1)
    page = await research.service.get_research_summary(research.xray.principal, research.query())
    item = next(
        item for item in page.items if item.source.revision_id == original.event.revision_id
    )
    assert item.portfolio.pin.run_id == research.run_id
    assert item.portfolio.pin.source_cutoff_at == run.context.source_cutoff_at
    assert item.source_cutoff_at > item.portfolio.pin.source_cutoff_at
    return replace(original, research=research, item=item)


@pytest.fixture
async def acquired_research_report_case(
    research_report_case: ResearchReportCase,
    request: pytest.FixtureRequest,
) -> AcquiredResearchReportCase:
    original = research_report_case
    acquisition = acquisition_case(
        original.research.xray, capability=AcquisitionCapability.REFERENCE_FX
    )
    restriction = getattr(request, "param", "allowed")
    assert restriction in {"allowed", "pinned_grant", "pinned_license"}
    _report_only_fx_authority(acquisition, restriction=restriction)
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=acquisition.xray.sessions,
        principal=acquisition.xray.principal,
        cursor_signing_key=XRAY_CURSOR_KEY,
        enabled=True,
    )
    fx = await runtime.publish(await batch(acquisition, runtime))
    assert isinstance(fx, FxSnapshot)
    assert len(fx.observations) == 1 and fx.observations[0].rate == Decimal("1.123456789123456789")
    current = await _current_valuation(original.research.xray)
    catalogue = await fresh_report_xray(current)
    with current.sessions() as session:
        stored = session.get_one(XrayInputSnapshotModel, UUID(catalogue.context.input_snapshot_id))
        policy = decode_xray_policy(
            session.get_one(XrayPolicyVersionModel, stored.policy_id).canonical_policy
        )
    providers = policy.provider_selection_policy.provider_order
    xray = await select_fx_policy(
        current, catalogue, (str(acquisition.grant.provider_id), *providers)
    )
    assert xray.context.valuation_at >= fx.observations[0].effective_at
    assert xray.context.source_cutoff_at >= fx.provenance.first_observed_at
    assert xray.summary.total.value is not None
    assert xray.summary.total.value.amount == Decimal("1123.456789123456789")
    assert xray.context.reporting_currency == CurrencyCode("USD")
    with current.sessions() as session:
        fx_members = tuple(
            session.scalars(
                select(XrayInputDependencyModel.fx_snapshot_id).where(
                    XrayInputDependencyModel.input_id == UUID(xray.context.input_snapshot_id),
                    XrayInputDependencyModel.fx_snapshot_id.is_not(None),
                )
            )
        )
        assert fx_members and set(fx_members) == {UUID(fx.id)}
    report = await research_item_for_run(original, current, xray)
    return AcquiredResearchReportCase(report, acquisition, fx, xray, providers)
