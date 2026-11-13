"""Fresh report-copy sources with explicit current knowledge and stable economic facts."""

from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from trading212_analytics.source_policy import assess_fx_coverage
from trading212_application import source_providers as ports
from trading212_application import sources as source_app
from trading212_application import xray as app
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.xray_ingestion import (
    FundDefinitionRegistration,
    FundSourceMappingRegistration,
    XrayPolicyRegistration,
    XrayTaxonomyRegistration,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import FxObservation, SourceLicense, SourcePeriod, SourceProvenance
from trading212_domain.values import CurrencyCode
from trading212_domain.xray import XrayDimension
from trading212_persistence.report_sources import _PHYSICAL
from trading212_persistence.source_models import FxObservationModel, FxSnapshotModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_run_models import XrayInputDependencyModel
from trading212_reference_data.xray_replay import XrayReplayProvider
from trading212_worker.source_seed import collect_source_pages
from trading212_worker.xray_fixture import (
    XRAY_ACCOUNT_ID,
    XRAY_AT,
    XRAY_EFFECTIVE,
    synthetic_xray_policy,
    xray_id,
)
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_entities, xray_license, xray_replay

from tests.integration.test_xray_reads_postgres import XrayReadCase


def _financial(value: object) -> object:
    """Retain every financial/quality field while comparing independent provenance."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _financial(getattr(value, field.name))
            for field in fields(value)
            if field.name != "source_reference_ids"
        }
    if isinstance(value, tuple):
        return tuple(_financial(item) for item in value)
    return value


def _residual(value: app.XrayResidualView) -> tuple[object, ...]:
    return (
        value.value,
        value.currency,
        value.kind,
        value.child_count,
        value.parent_separately_rounded,
    )


def _exposure(value: app.XrayExposureRowView) -> dict[str, object]:
    # Row IDs and metric references bind the new proof; all economic row fields remain exact.
    return {
        field.name: _financial(getattr(value, field.name))
        for field in fields(value)
        if field.name not in {"id", "residuals"}
    } | {"residuals": tuple(_residual(item) for item in value.residuals)}


def _path(value: app.XrayPathRowView) -> tuple[object, ...]:
    classification = value.classification
    return (
        value.root_key,
        value.root,
        value.instrument_id,
        value.entity_id,
        value.name,
        value.explicit_cash,
        value.unresolved_reason,
        tuple((item.fund_instrument_id, item.weight, item.origin) for item in value.fund_edges),
        _financial(value.reporting_value),
        _financial(value.absolute_weight),
        _financial(value.relative_weight),
        _financial(value.normalized_known_weight),
        None
        if classification is None
        else (
            classification.dimension,
            classification.bucket_key,
            classification.reason,
            classification.confidence,
        ),
        tuple(_residual(item) for item in value.residuals),
        value.quality,
        value.confidence,
    )


async def _assert_financial_parity(
    case: XrayReadCase, baseline: app.ExposuresView, fresh: app.ExposuresView
) -> None:
    assert _financial(fresh.summary) == _financial(baseline.summary)
    assert baseline.summary.total.value is not None
    assert baseline.summary.total.value.amount == (
        Decimal("1000")
        if baseline.context.reporting_currency == CurrencyCode("EUR")
        else Decimal("800")
    )
    assert baseline.summary.company_known_weight.value == Decimal("0.95")
    assert baseline.summary.unresolved_weight.value == Decimal("0.05")
    assert baseline.summary.hhi.value == Decimal("0.4657")
    for dimension in XrayDimension:
        observations = []
        for retained in (baseline, fresh):
            request = replace(
                case.request(retained.context.run_id),
                source_cutoff_at=retained.context.source_cutoff_at,
                currency=app.ExplicitCurrency(
                    reporting_currency=retained.context.reporting_currency
                ),
            )
            exposure = await case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=request, options=app.Exposures(dimension=dimension), limit=100
                ),
            )
            paths = await case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=request, options=app.Paths(dimension=dimension), limit=100
                ),
            )
            assert isinstance(exposure, app.ExposuresView) and isinstance(paths, app.PathsView)
            assert exposure.exposures.next_cursor is None and paths.paths.next_cursor is None
            observations.append(
                (
                    _financial(exposure.summary),
                    _financial(exposure.dimension_summary),
                    tuple(_residual(item) for item in exposure.dimension_residuals),
                    exposure.exposures.total,
                    {item.bucket_key: _exposure(item) for item in exposure.exposures.items},
                    _financial(paths.summary),
                    _financial(paths.dimension_summary),
                    tuple(_residual(item) for item in paths.dimension_residuals),
                    paths.paths.total,
                    sorted(canonical_json(_path(item)) for item in paths.paths.items),
                )
            )
        assert observations[0] == observations[1], dimension


def _headers(case: XrayReadCase, input_id: str) -> dict[str, tuple[object, ...]]:
    headers = {}
    with case.sessions() as session:
        for kind in (
            "fx",
            "classification",
            "constituent",
            "entity_evidence",
            "fund_definition",
            "fund_mapping",
        ):
            model, target = _PHYSICAL[kind]
            rows = session.execute(
                select(
                    model.id,
                    model.content_digest,
                    model.effective_at,
                    model.created_at,
                    model.first_observed_at,
                    model.expires_at,
                )
                .join(
                    XrayInputDependencyModel, getattr(XrayInputDependencyModel, target) == model.id
                )
                .where(XrayInputDependencyModel.input_id == UUID(input_id))
            )
            headers.update({f"{kind}:{row.id}": tuple(row) for row in rows})
    return headers


async def _copy_fx(
    case: XrayReadCase,
    source: PostgresSourceService,
    license: SourceLicense,
    original_headers: dict[str, tuple[object, ...]],
    prefix: str,
) -> set[str]:
    identifiers = [UUID(key.split(":", 1)[1]) for key in original_headers if key.startswith("fx:")]
    assert len(identifiers) <= 1
    copied = set()
    for identifier in identifiers:
        with case.sessions() as session:
            snapshot = session.get_one(FxSnapshotModel, identifier)
            calendar = source._calendar(
                session, UUID(case.principal.owner_id), snapshot.calendar_id
            )
            rows = session.scalars(
                select(FxObservationModel)
                .where(FxObservationModel.snapshot_id == identifier)
                .order_by(
                    FxObservationModel.session_date,
                    FxObservationModel.base,
                    FxObservationModel.quote,
                )
            ).all()
            assert 0 < len(rows) <= 4
            assert all(row.state == "available" and row.rate is not None for row in rows)
            observations = tuple(
                FxObservation(
                    base=CurrencyCode(row.base),
                    quote=CurrencyCode(row.quote),
                    session_date=row.session_date,
                    effective_at=row.effective_at,
                    rate=row.rate,
                    batch_key=row.batch_key,
                )
                for row in rows
            )
            period = SourcePeriod(start=snapshot.period_start, end=snapshot.period_end)
            effective_at = snapshot.effective_at
        pairs = tuple(ports.FxPair(base=item.base, quote=item.quote) for item in observations)
        receipt = await source.ingest_fx_rates(
            case.principal,
            ports.FxRatesRequest(
                provider_id=license.provider_id,
                license_version_id=license.id,
                pairs=pairs,
                period=period,
                source_cutoff_at=case.now[0],
                calendar_id=calendar.id,
                calendar_version=calendar.version,
            ),
            (
                ports.FxRatePage(
                    provenance=SourceProvenance(
                        provider_id=license.provider_id,
                        license_version_id=license.id,
                        adapter_version="synthetic-xray-replay-v1",
                        schema_version="1",
                        source_revision="current-copy-1",
                        revision_order=1,
                        effective_at=effective_at,
                        first_observed_at=case.now[0],
                        synthetic=True,
                    ),
                    period=period,
                    coverage=assess_fx_coverage(
                        calendar,
                        period,
                        observations,
                        pairs=tuple((item.base, item.quote) for item in observations),
                    ),
                    observations=observations,
                ),
            ),
            idempotency_key=f"{prefix}:fx:{identifier}",
            correlation_id=prefix,
        )
        copied.add(receipt.id)
    return copied


async def fresh_report_xray(
    case: XrayReadCase, *, reporting_currency: CurrencyCode | None = None
) -> app.ExposuresView:
    """Publish twelve new physical headers through normal typed synthetic adapters.

    An isolated provider/policy prevents the complete source proof from retaining
    older overlapping catalog versions. Their records and old observation cutoff
    remain available unchanged. New availability is current UTC, never backdated.
    """
    original_request = replace(
        case.request(),
        currency=app.ExplicitCurrency(reporting_currency=reporting_currency or CurrencyCode("EUR")),
    )
    baseline = await case.service.get_effective_exposure(
        case.principal, XRAY_ACCOUNT_ID, query=app.EffectiveExposureQuery(request=original_request)
    )
    assert isinstance(baseline, app.ExposuresView)
    old_cutoff = case.request().source_cutoff_at
    original_headers = _headers(case, baseline.context.input_snapshot_id)
    assert 12 <= len(original_headers) <= 13
    case.now[0] = max(case.now[0], datetime.now(UTC))
    observed_at = case.now[0]
    assert observed_at > old_cutoff
    provider_id, license_id = str(uuid4()), str(uuid4())
    prefix = f"runtime-report-{provider_id}"
    source = PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    await source.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=provider_id,
            key=prefix,
            name="Synthetic current report evidence",
            adapter_version="synthetic-xray-replay-v1",
            configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            freshness_policy_version="synthetic-xray-freshness-1",
            max_age_seconds=7 * 86400,
            capabilities=(
                ports.SourceCapability.CLASSIFICATIONS,
                ports.SourceCapability.CONSTITUENTS,
                ports.SourceCapability.FX_RATES,
            ),
        ),
        idempotency_key=prefix,
        correlation_id=prefix,
    )
    license = replace(xray_license(), id=license_id, provider_id=provider_id)
    await source.register_source_license(
        case.principal, license, idempotency_key=f"{prefix}:license", correlation_id=prefix
    )
    original_policy = synthetic_xray_policy()
    policy = replace(
        original_policy,
        id=uuid4(),
        provider_selection_policy=replace(
            original_policy.provider_selection_policy, id=uuid4(), provider_order=(provider_id,)
        ),
    )
    await case.service.register_xray_policy(
        case.principal,
        XRAY_ACCOUNT_ID,
        XrayPolicyRegistration(
            key=prefix,
            effective_at=XRAY_EFFECTIVE,
            policy=policy,
            taxonomies=tuple(
                XrayTaxonomyRegistration(
                    id=str(item.taxonomy_id),
                    dimension=item.dimension,
                    key=item.key,
                    version=item.version,
                )
                for item in policy.taxonomy_versions
            ),
        ),
        idempotency_key=f"{prefix}:policy",
        correlation_id=prefix,
    )
    original_evidence = xray_entities()
    shares = {item.id: str(uuid4()) for item in original_evidence.share_classes}
    evidence = replace(
        original_evidence,
        id=str(uuid4()),
        key=prefix,
        provider_id=provider_id,
        license_version_id=license_id,
        mappings=tuple(replace(item, id=str(uuid4())) for item in original_evidence.mappings),
        share_classes=tuple(
            replace(item, id=shares[item.id]) for item in original_evidence.share_classes
        ),
        relationships=tuple(
            replace(
                item,
                id=str(uuid4()),
                share_class_id=None if item.share_class_id is None else shares[item.share_class_id],
            )
            for item in original_evidence.relationships
        ),
    )
    registered = {
        (
            await case.service.register_entity_evidence(
                case.principal,
                evidence,
                idempotency_key=f"{prefix}:entities",
                correlation_id=prefix,
            )
        ).id
    }
    mappings = {}
    for key in ("fund-a", "fund-b"):
        definition_id, mapping_id = str(uuid4()), str(uuid4())
        definition = await case.service.register_fund_definition(
            case.principal,
            FundDefinitionRegistration(
                id=definition_id,
                key=f"{prefix}-{key}",
                instrument_id=xray_id(f"instrument/{key}"),
                fund_type="etf",
                provider_id=provider_id,
                license_version_id=license_id,
                revision=1,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                evidence_key=f"synthetic-{key}-definition",
                confidence=Decimal("0.99"),
            ),
            idempotency_key=f"{prefix}:definition:{key}",
            correlation_id=prefix,
        )
        mapping = await case.service.register_fund_mapping(
            case.principal,
            FundSourceMappingRegistration(
                id=mapping_id,
                fund_definition_id=definition_id,
                provider_id=provider_id,
                license_version_id=license_id,
                provider_fund_key=f"synthetic-{key}",
                revision=1,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                evidence_key=f"synthetic-{key}-mapping",
                confidence=Decimal("0.99"),
            ),
            idempotency_key=f"{prefix}:mapping:{key}",
            correlation_id=prefix,
        )
        registered.update((definition.id, mapping.id))
        mappings[xray_id(f"fund-mapping/{key}")] = mapping_id
    original_replay = xray_replay(case.principal.owner_id)
    replay = XrayReplayProvider(
        owner_id=case.principal.owner_id,
        license=license,
        known_at=observed_at,
        funds=tuple(
            replace(fund, mapping_id=mappings[fund.mapping_id]) for fund in original_replay.funds
        ),
        classifications=original_replay.classifications,
        clock=lambda: case.now[0],
    )
    for fund in replay.funds:
        request = ports.ConstituentRequest(
            fund_series_id=fund.mapping_id, effective_at=XRAY_AT, source_cutoff_at=observed_at
        )

        async def fetch(
            cursor: str | None, request: ports.ConstituentRequest = request
        ) -> ports.ConstituentPage | ports.SourceFailure:
            return await replay.get_constituents(replace(request, continuation=cursor))

        pages = await collect_source_pages(
            fetch,
            page_type=ports.ConstituentPage,
            next_cursor=lambda page: page.continuation,
            row_count=lambda page: len(page.holdings),
        )
        receipt = await case.service.ingest_constituents(
            case.principal,
            request,
            pages,
            idempotency_key=f"{prefix}:constituents:{fund.mapping_id}",
            correlation_id=prefix,
        )
        registered.add(receipt.id)
    for dimension in XrayDimension:
        if dimension is XrayDimension.COMPANY:
            continue
        classification_request = ports.ClassificationRequest(
            instrument_ids=tuple(
                xray_id(f"instrument/{key}") for key in ("alpha-a", "alpha-b", "alpha-adr", "beta")
            ),
            taxonomy=f"synthetic-xray-{dimension.value}",
            taxonomy_version="1",
            source_cutoff_at=observed_at,
        )

        async def fetch_classifications(
            cursor: str | None, request: ports.ClassificationRequest = classification_request
        ) -> ports.ClassificationPage | ports.SourceFailure:
            return await replay.get_classifications(replace(request, continuation=cursor))

        pages_classifications = await collect_source_pages(
            fetch_classifications,
            page_type=ports.ClassificationPage,
            next_cursor=lambda page: page.continuation,
            row_count=lambda page: len(page.observations),
        )
        receipt = await case.service.ingest_classifications(
            case.principal,
            classification_request,
            pages_classifications,
            idempotency_key=f"{prefix}:classification:{dimension.value}",
            correlation_id=prefix,
        )
        registered.add(receipt.id)
    assert len(registered) == 12
    registered.update(await _copy_fx(case, source, license, original_headers, prefix))
    old = await case.service.get_effective_exposure(
        case.principal, XRAY_ACCOUNT_ID, query=app.EffectiveExposureQuery(request=original_request)
    )
    assert isinstance(old, app.ExposuresView)
    fresh = await case.service.get_effective_exposure(
        case.principal,
        XRAY_ACCOUNT_ID,
        query=app.EffectiveExposureQuery(
            request=replace(original_request, source_cutoff_at=observed_at)
        ),
    )
    assert isinstance(fresh, app.ExposuresView)
    assert _headers(case, old.context.input_snapshot_id) == original_headers
    assert _headers(case, baseline.context.input_snapshot_id) == original_headers
    fresh_headers = _headers(case, fresh.context.input_snapshot_id)
    assert {str(row[0]) for row in fresh_headers.values()} == registered
    assert not registered.intersection(str(row[0]) for row in original_headers.values())
    assert all(row[3] == row[4] == observed_at for row in fresh_headers.values())
    assert (
        fresh.context.source_cutoff_at == observed_at > old.context.source_cutoff_at == old_cutoff
    )
    assert fresh.context.valuation_at == baseline.context.valuation_at
    assert fresh.context.snapshot_id == baseline.context.snapshot_id
    await _assert_financial_parity(case, baseline, fresh)
    return fresh
