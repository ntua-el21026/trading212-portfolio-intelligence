"""A genuine large X-ray exercises REPORT's size-only composed-reader fallback.

All broker observations, entities, licenses, policy and constituent revisions use
their normal typed ingestion/registration paths. Two distinct small geometries
size one final publication; no threshold, canonical payload or authority is mocked.
Current DISPLAY admission keeps its combined 32-MiB cap. This is retained-reader
qualification, not construction of a forged legacy item or a full report artifact.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import event, func, select
from trading212_application import research as research_app
from trading212_application import source_providers as ports
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_application.ingestion import (
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
)
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.xray_ingestion import (
    EconomicEntityRegistration,
    EntityEvidenceRegistration,
    FundDefinitionRegistration,
    FundSourceMappingRegistration,
    XrayPolicyRegistration,
    XrayTaxonomyRegistration,
)
from trading212_domain.source_details import ConstituentHolding, ConstituentState
from trading212_domain.sources import LicensePermission, SourceLicense, SourceProvenance, SourceUse
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import MAX_BYTES, encode_xray_result
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_capture_research_store import ResearchReportStore
from trading212_persistence.research_xray_read import read_research_xray
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_catalog_models import (
    ConstituentHoldingModel,
    ConstituentSnapshotModel,
    EconomicEntityModel,
    XrayPolicyVersionModel,
)
from trading212_persistence.xray_run_models import (
    XrayInputDependencyModel,
    XrayInputSnapshotModel,
    XrayRunModel,
)
from trading212_reference_data.xray_replay import XrayReplayFund, XrayReplayProvider
from trading212_security.principals import AuthorizationError
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.source_seed import collect_source_pages
from trading212_worker.xray_fixture import synthetic_xray_policy
from trading212_worker.xray_provider import SyntheticXrayBrokerProvider
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.phase3_operational_fixture import evidence
from tests.integration.retained_xray_geometry import select_final_geometry
from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration

_NAMESPACE = uuid5(NAMESPACE_URL, "t212pi/actual-report-reader-combined-bound/v1")
_UNIT = Decimal("0.0001")
_MAX_HOLDINGS = 9000
_PRIVATE_COLUMNS = (
    "canonical_input",
    "canonical_result",
    "canonical_summary",
    "canonical_exact_state",
    "canonical_reference",
)
_METADATA_BYTE_LENGTH = re.compile(
    r"\boctet_length\(\s*(?:[a-z_][a-z_0-9]*\.)?"
    r"(?:canonical_input|canonical_result|canonical_summary|canonical_exact_state|canonical_reference)"
    r"\s*\)"
)


def _id(label: str) -> UUID:
    return uuid5(_NAMESPACE, label)


class _OneFundProvider(SyntheticXrayBrokerProvider):
    def __init__(self, observed: datetime) -> None:
        super().__init__()
        self.observed = observed
        self.fixture = replace(
            self.fixture,
            listings=tuple(
                replace(row, held_value=Decimal("1000") if row.key == "fund-a" else None)
                for row in self.fixture.listings
            ),
        )

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
        return replace(
            page,
            records=tuple(
                replace(row, source_timestamp=self.observed, observed_at=self.observed)
                for row in page.records
            ),
        )


class _RevisionedReplay(XrayReplayProvider):
    """A typed synthetic provider declares each actual new immutable file revision."""

    def __init__(
        self,
        *,
        owner: str,
        license: SourceLicense,
        known: datetime,
        fund: XrayReplayFund,
        revision: int,
    ) -> None:
        super().__init__(
            owner_id=owner,
            license=license,
            known_at=known,
            funds=(fund,),
            classifications=(),
            clock=lambda: known,
        )
        self.revision = revision

    def _provenance(self, effective_at: datetime) -> SourceProvenance:
        return replace(
            super()._provenance(effective_at),
            source_revision=f"synthetic-full-size-file-{self.revision}",
            revision_order=self.revision,
        )


@contextmanager
def _no_private_select(case: ReportCase) -> Iterator[None]:
    """Permit metadata size SQL, but reject a private canonical payload SELECT."""

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        sql = statement.replace('"', "").lower().lstrip()
        if sql.startswith(("select", "with")):
            # PostgreSQL computes these lengths without returning the private
            # bytea values. Every other occurrence remains forbidden, including
            # a raw private column in the same statement as a length expression.
            public_metadata = _METADATA_BYTE_LENGTH.sub("metadata_byte_length", sql)
            assert not any(name in public_metadata for name in _PRIVATE_COLUMNS), (
                "A denied large read selected private canonical bytes."
            )

    event.listen(case.base.engine, "before_cursor_execute", observe)
    try:
        yield
    finally:
        event.remove(case.base.engine, "before_cursor_execute", observe)


def _sizes(case: ReportCase, run_id: UUID) -> dict[str, int]:
    with case.base.sessions() as session:
        run = session.execute(
            select(
                XrayInputSnapshotModel.id,
                func.octet_length(XrayInputSnapshotModel.canonical_input),
                func.octet_length(AnalyticsRunModel.canonical_result),
                func.octet_length(XrayPolicyVersionModel.canonical_policy),
                func.octet_length(XrayRunModel.canonical_summary),
            )
            .join(XrayRunModel, XrayRunModel.input_id == XrayInputSnapshotModel.id)
            .join(AnalyticsRunModel, AnalyticsRunModel.id == XrayRunModel.analytics_run_id)
            .join(
                XrayPolicyVersionModel,
                XrayPolicyVersionModel.id == XrayInputSnapshotModel.policy_id,
            )
            .where(XrayRunModel.id == run_id)
        ).one()
        references, count = session.execute(
            select(
                func.coalesce(
                    func.sum(func.octet_length(XrayInputDependencyModel.canonical_reference)), 0
                ),
                func.count(),
            ).where(XrayInputDependencyModel.input_id == run[0])
        ).one()
    values = {
        "input_bytes": int(run[1]),
        "result_bytes": int(run[2]),
        "policy_bytes": int(run[3]),
        "summary_bytes": int(run[4]),
        "reference_bytes": int(references),
        "references": int(count),
    }
    values["combined_bytes"] = sum(value for key, value in values.items() if key.endswith("_bytes"))
    return values


async def _register_entities(
    case: ReportCase, license: SourceLicense, start: int, stop: int, effective: datetime
) -> None:
    if start == stop:
        return
    case.base.now[0] = datetime.now(UTC)
    await case.base.service.register_entity_evidence(
        case.principal,
        EntityEvidenceRegistration(
            id=str(_id(f"entities/{start}/{stop}")),
            key=f"full-size-reader-entities-{start}-{stop}",
            provider_id=license.provider_id,
            license_version_id=license.id,
            revision=1,
            effective_at=effective,
            valid_until=None,
            entities=tuple(
                EconomicEntityRegistration(
                    id=str(_id(f"entity/{ordinal}")),
                    key=f"full-size-reader-company-{ordinal:04d}",
                    display_name=f"Synthetic distinct issuer {ordinal:04d}",
                )
                for ordinal in range(start, stop)
            ),
            mappings=(),
            share_classes=(),
            relationships=(),
        ),
        idempotency_key=f"full-size-reader-entities-{start}-{stop}",
        correlation_id="actual-full-size-retained-reader",
    )


async def _publish(
    case: ReportCase,
    license: SourceLicense,
    mapping: str,
    snapshot_id: str,
    effective: datetime,
    *,
    count: int,
    revision: int,
) -> tuple[UUID, dict[str, int]]:
    assert 1 <= count <= _MAX_HOLDINGS
    weights = (_UNIT,) * (count - 1) + (Decimal(1) - _UNIT * (count - 1),)
    assert all(weight > 0 for weight in weights) and sum(weights, Decimal(0)) == Decimal(1)
    holdings = tuple(
        ConstituentHolding(
            source_key=f"full-size-distinct-holding-{ordinal:04d}",
            weight=weight,
            state=ConstituentState.RESOLVED,
            currency=CurrencyCode("EUR"),
            entity_id=str(_id(f"entity/{ordinal}")),
            evidence_key=f"synthetic-distinct-issuer-evidence-{ordinal:04d}",
        )
        for ordinal, weight in enumerate(weights)
    )
    case.base.now[0] = known = datetime.now(UTC)
    replay = _RevisionedReplay(
        owner=case.principal.owner_id,
        license=license,
        known=known,
        fund=XrayReplayFund(
            mapping_id=mapping,
            effective_at=effective,
            holdings=holdings,
            stated_coverage=Decimal(1),
            unresolved_weight=Decimal(0),
            cash_weight=Decimal(0),
        ),
        revision=revision,
    )
    request = ports.ConstituentRequest(
        fund_series_id=mapping, effective_at=effective, source_cutoff_at=known
    )

    async def fetch(cursor: str | None) -> ports.ConstituentPage | ports.SourceFailure:
        return await replay.get_constituents(replace(request, continuation=cursor))

    pages = await collect_source_pages(
        fetch,
        page_type=ports.ConstituentPage,
        next_cursor=lambda page: page.continuation,
        row_count=lambda page: len(page.holdings),
    )
    assert sum(len(page.holdings) for page in pages) == count
    receipt = await case.base.service.ingest_constituents(
        case.principal,
        request,
        pages,
        idempotency_key=f"full-size-reader-constituents-{revision}",
        correlation_id="actual-full-size-retained-reader",
    )
    case.base.now[0] = cutoff = datetime.now(UTC)
    view = await case.base.service.get_effective_exposure(
        case.principal,
        str(case.account_id),
        query=xray_app.EffectiveExposureQuery(
            request=xray_app.XrayRunRequest(
                snapshot_id=snapshot_id,
                source_cutoff_at=cutoff,
                currency=xray_app.ExplicitCurrency(reporting_currency=CurrencyCode("EUR")),
            ),
            limit=25,
        ),
    )
    assert isinstance(view, xray_app.ExposuresView)
    assert view.summary.total.value is not None
    assert view.summary.total.value.amount == Decimal("1000")
    assert view.summary.company_known_weight.value == Decimal(1)
    assert view.summary.unresolved_weight.value == Decimal(0)
    assert view.exposures.total == count
    with case.base.sessions() as session:
        source = session.get_one(ConstituentSnapshotModel, UUID(receipt.id))
        assert source.row_count == count and source.revision_order == revision
        assert source.known_weight == Decimal(1) and source.unresolved_weight == Decimal(0)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ConstituentHoldingModel)
                .where(ConstituentHoldingModel.snapshot_id == source.id)
            )
            == count
        )
    return UUID(view.context.run_id), _sizes(case, UUID(view.context.run_id))


async def test_actual_large_retained_xray_uses_report_only_size_fallback(
    report_case: ReportCase,
) -> None:
    case, started = report_case, perf_counter()
    observations: list[dict[str, object]] = []
    phase, failure = "normal_source_setup", None
    try:
        assert MAX_BYTES == 33_554_432
        case.base.now[0] = financial_at = datetime.now(UTC)
        broker = _OneFundProvider(financial_at)
        ingested = await IngestionCoordinator(
            provider=broker,
            store=PostgresIngestionStore(
                case.base.sessions,
                provider="synthetic",
                materializer=PostgresCanonicalMaterializer(),
            ),
            clock=lambda: financial_at,
        ).refresh(
            owner_id=case.principal.owner_id,
            account_id=str(case.account_id),
            mode=RunMode.FULL,
            capabilities=(IngestionCapability.ACCOUNT, IngestionCapability.POSITIONS),
            idempotency_key="full-size-reader-one-fund-observation",
            correlation_id="actual-full-size-retained-reader",
        )
        assert ingested.status is RunStatus.SUCCEEDED
        with case.base.sessions() as session:
            snapshot = session.scalar(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.broker_account_id == case.account_id,
                    PortfolioSnapshotModel.source_cutoff_at == financial_at,
                )
            )
            assert snapshot is not None and snapshot.portfolio_total == Decimal("1000")
            snapshot_id = str(snapshot.id)
        effective = financial_at - timedelta(days=1)
        case.base.now[0] = datetime.now(UTC)
        sources = PostgresSourceService(
            sessions=case.base.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.base.now[0],
        )
        provider_id, license_id = str(_id("provider")), str(_id("license"))
        await sources.configure_source_provider(
            case.principal,
            SourceProviderRegistration(
                id=provider_id,
                key="actual-full-size-retained-reader",
                name="Synthetic full-size retained X-ray evidence",
                adapter_version="synthetic-xray-replay-v1",
                configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
                synthetic=True,
                capabilities=(ports.SourceCapability.CONSTITUENTS,),
                freshness_policy_version="synthetic-full-size-v1",
                max_age_seconds=7 * 86400,
            ),
            idempotency_key="full-size-reader-provider",
            correlation_id="actual-full-size-retained-reader",
        )
        license = SourceLicense(
            id=license_id,
            provider_id=provider_id,
            version="synthetic-full-size-1",
            effective_at=effective,
            store=LicensePermission.ALLOWED,
            display=LicensePermission.ALLOWED,
            report=LicensePermission.ALLOWED,
            export=LicensePermission.DENIED,
            retention_days=30,
            attribution="Deterministic full-size retained X-ray fixture.",
            evidence_key="synthetic-full-size-source-rights",
        )
        await sources.register_source_license(
            case.principal,
            license,
            idempotency_key="full-size-reader-license",
            correlation_id="actual-full-size-retained-reader",
        )
        original = synthetic_xray_policy()
        policy = replace(
            original,
            id=_id("policy"),
            version="actual-full-size-reader-v1",
            provider_selection_policy=replace(
                original.provider_selection_policy,
                id=_id("provider-selection"),
                provider_order=(provider_id,),
            ),
        )
        await case.base.service.register_xray_policy(
            case.principal,
            str(case.account_id),
            XrayPolicyRegistration(
                key="actual-full-size-retained-reader",
                effective_at=effective,
                policy=policy,
                taxonomies=tuple(
                    XrayTaxonomyRegistration(
                        id=str(row.taxonomy_id),
                        dimension=row.dimension,
                        key=row.key,
                        version=row.version,
                    )
                    for row in policy.taxonomy_versions
                ),
            ),
            idempotency_key="full-size-reader-policy",
            correlation_id="actual-full-size-retained-reader",
        )
        instrument = next(
            row.instrument.id for row in broker.fixture.listings if row.key == "fund-a"
        )
        await case.base.service.register_fund_definition(
            case.principal,
            FundDefinitionRegistration(
                id=str(_id("fund-definition")),
                key="actual-full-size-reader-fund",
                instrument_id=str(instrument),
                fund_type="etf",
                provider_id=provider_id,
                license_version_id=license_id,
                revision=1,
                effective_at=effective,
                valid_until=None,
                evidence_key="synthetic-full-size-fund-definition",
                confidence=Decimal(1),
            ),
            idempotency_key="full-size-reader-definition",
            correlation_id="actual-full-size-retained-reader",
        )
        mapping = str(_id("fund-mapping"))
        await case.base.service.register_fund_mapping(
            case.principal,
            FundSourceMappingRegistration(
                id=mapping,
                fund_definition_id=str(_id("fund-definition")),
                provider_id=provider_id,
                license_version_id=license_id,
                provider_fund_key="synthetic-full-size-fund",
                revision=1,
                effective_at=effective,
                valid_until=None,
                evidence_key="synthetic-full-size-fund-mapping",
                confidence=Decimal(1),
            ),
            idempotency_key="full-size-reader-mapping",
            correlation_id="actual-full-size-retained-reader",
        )
        await _register_entities(case, license, 0, 1024, effective)
        phase = "bounded_actual_geometry_sizing"
        run_id = None
        for revision, count in ((1, 512), (2, 1024)):
            step = perf_counter()
            run_id, sizes = await _publish(
                case, license, mapping, snapshot_id, effective, count=count, revision=revision
            )
            observations.append(
                {
                    "holdings": count,
                    "revision": revision,
                    **sizes,
                    "seconds": perf_counter() - step,
                    "role": "fixture_sizing",
                }
            )
            assert sizes["input_bytes"] <= MAX_BYTES and sizes["result_bytes"] <= MAX_BYTES
        assert run_id is not None
        if sizes["combined_bytes"] <= MAX_BYTES:
            measured_geometries: list[dict[str, int]] = []
            for observation in (observations[0], observations[1]):
                measured: dict[str, int] = {}
                for field in ("holdings", "result_bytes", "combined_bytes", "input_bytes"):
                    value = observation[field]
                    assert isinstance(value, int) and type(value) is int
                    measured[field] = value
                measured_geometries.append(measured)
            forecast = select_final_geometry(*measured_geometries)
            target = forecast["holdings"]
            assert isinstance(target, int)
            assert 1024 < target <= _MAX_HOLDINGS
            await _register_entities(case, license, 1024, target, effective)
            step = perf_counter()
            run_id, sizes = await _publish(
                case, license, mapping, snapshot_id, effective, count=target, revision=3
            )
            observations.append(
                {
                    "holdings": target,
                    "predicted_holdings": target,
                    "sizing_forecast": forecast,
                    "revision": 3,
                    **sizes,
                    "seconds": perf_counter() - step,
                    "role": "qualifying_geometry",
                }
            )
        assert len(observations) <= 3
        assert 0 < sizes["input_bytes"] <= MAX_BYTES
        assert 0 < sizes["result_bytes"] <= MAX_BYTES
        assert sizes["references"] < 100_000 and sizes["combined_bytes"] > MAX_BYTES
        with case.base.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EconomicEntityModel)
                    .where(
                        EconomicEntityModel.owner_id == UUID(case.principal.owner_id),
                        EconomicEntityModel.key.like("full-size-reader-company-%"),
                    )
                )
                == observations[-1]["holdings"]
            )
        phase = "actual_combined_report_and_display_denial_before_payload"
        with case.base.sessions() as session:
            auth = authorize_report_request(
                session,
                case.principal,
                account_id=case.account_id,
                required_scopes=research_app.RESEARCH_READ_SCOPES,
                now=case.base.now[0],
            )
            for use in (SourceUse.REPORT, SourceUse.DISPLAY):
                with (
                    _no_private_select(case),
                    pytest.raises(research_app.ResearchServiceError) as denied,
                ):
                    read_research_xray(
                        session, auth, run_id, now=case.base.now[0], required_copy_use=use
                    )
                assert denied.value.code is research_app.ResearchErrorCode.INPUT_BOUND_EXCEEDED
        phase = "actual_report_size_only_fallback"
        store = ResearchReportStore(
            case.base.sessions, clock=lambda: case.base.now[0], cursor_signing_key=XRAY_CURSOR_KEY
        )
        with case.base.sessions() as session:
            auth = authorize_report_request(
                session,
                case.principal,
                account_id=case.account_id,
                required_scopes=research_app.RESEARCH_READ_SCOPES,
                now=case.base.now[0],
            )
            pin, calculation, input_id, deadline = store.retained_xray(session, auth, run_id)
            assert run_id in store._original_runs and run_id not in store._retained_reads
            metadata = store.xray_metadata(session, auth, run_id)
            assert metadata == (
                input_id,
                pin.result_digest,
                pin.input_digest,
                pin.snapshot_id,
                deadline,
            )
            assert pin.account_id == case.account_id and pin.owner_id == auth.owner_id
            assert pin.reporting_currency == CurrencyCode("EUR")
            assert pin.run_id == run_id and str(pin.snapshot_id) == snapshot_id
            assert calculation.portfolio_summary.total.value is not None
            assert calculation.portfolio_summary.total.value.amount == Decimal("1000")
            assert calculation.portfolio_summary.company_known_weight.value == Decimal(1)
            assert calculation.portfolio_summary.unresolved_weight.value == Decimal(0)
            assert all(
                path.reporting_value.value is not None for path in calculation.terminal_paths
            )
            target_path = next(
                path for path in calculation.terminal_paths if path.entity_id == _id("entity/0")
            )
            assert target_path.reporting_value.value is not None
            assert target_path.reporting_value.value.amount == Decimal("0.1")
            run = session.get_one(XrayRunModel, run_id)
            original_run = session.get_one(AnalyticsRunModel, run.analytics_run_id)
            captured = session.get_one(XrayInputSnapshotModel, input_id)
            encoded = encode_xray_result(calculation)
            equal = encoded == original_run.canonical_result
            assert equal, "Authorized fallback changed canonical retained result bytes."
            assert sha256(encoded).hexdigest() == pin.result_digest == run.content_digest
            assert captured.canonical_input == original_run.canonical_input
            assert sha256(captured.canonical_input).hexdigest() == pin.input_digest
            assert deadline is not None and deadline > case.base.now[0]
        phase = "original_expiry_before_private_payload"
        real_now = case.base.now[0]
        case.base.now[0] = deadline + timedelta(microseconds=1)
        try:
            with case.base.sessions() as session, _no_private_select(case):
                auth = authorize_report_request(
                    session,
                    case.principal,
                    account_id=case.account_id,
                    required_scopes=research_app.RESEARCH_READ_SCOPES,
                    now=case.base.now[0],
                )
                with pytest.raises(research_app.ResearchServiceError):
                    store.xray_metadata(session, auth, run_id)
        finally:
            case.base.now[0] = real_now
        phase = "foreign_authorization_before_private_payload"
        with (
            case.base.sessions() as session,
            _no_private_select(case),
            pytest.raises(AuthorizationError),
        ):
            authorize_report_request(
                session,
                replace(case.principal, owner_id=str(_id("foreign-owner"))),
                account_id=case.account_id,
                required_scopes=research_app.RESEARCH_READ_SCOPES,
                now=case.base.now[0],
            )
        phase = "current_report_revocation_before_private_payload"
        case.base.now[0] = datetime.now(UTC)
        await sources.register_source_license(
            case.principal,
            replace(
                license,
                id=str(_id("report-revoked-license")),
                version="synthetic-full-size-report-denied",
                effective_at=case.base.now[0],
                report=LicensePermission.DENIED,
            ),
            idempotency_key="full-size-reader-report-revocation",
            correlation_id="actual-full-size-retained-reader",
        )
        with case.base.sessions() as session, _no_private_select(case):
            auth = authorize_report_request(
                session,
                case.principal,
                account_id=case.account_id,
                required_scopes=research_app.RESEARCH_READ_SCOPES,
                now=case.base.now[0],
            )
            with pytest.raises(source_app.SourceServiceError) as denied_copy:
                store.xray_metadata(session, auth, run_id)
            assert denied_copy.value.code is source_app.SourceServiceErrorCode.ACCESS_DENIED
        phase = "complete"
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        evidence(
            "actual-large-retained-xray-reader",
            {
                "phase": phase,
                "failure_type": failure,
                "elapsed_seconds": perf_counter() - started,
                "source_geometries": observations,
                "unchanged_combined_limit": MAX_BYTES,
                "full_new_research_item_or_report_capture_claimed": False,
                "controlled_expiry_clock_boundary": True,
                "source_payloads_or_private_urls_retained": False,
                "scope": (
                    "Genuine large REPORT retained-reader size-only fallback; "
                    "DISPLAY combined cap remains enforced. No legacy item is fabricated."
                ),
            },
        )
