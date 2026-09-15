"""Actual nonempty sensitivity/replay report copies and current original source rights."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from trading212_application import reports as app
from trading212_application import scenario as scenarios
from trading212_application import source_providers as ports
from trading212_application import sources as source_app
from trading212_application.historical_evidence import HistoricalPolicyRegistration
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProviderRegistration,
)
from trading212_domain import historical as h
from trading212_domain import historical_results as hr
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.report_manifest import canonical_report_cell_value
from trading212_domain.report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES
from trading212_domain.report_v3 import ReportScenarioRunBinding
from trading212_domain.scenario import (
    ScenarioRateShock,
    ScenarioReason,
    ScenarioSensitivityVersionPin,
    ScenarioVersionContent,
    scenario_rule_key,
)
from trading212_domain.scenario_execution import ScenarioReplaySelection
from trading212_domain.scenario_result import ScenarioMoneyMetric, ScenarioRatioMetric
from trading212_domain.scenario_serialization import (
    scenario_sensitivity_evidence_digest,
    scenario_sensitivity_observation_digest,
    scenario_sensitivity_version_digest,
)
from trading212_domain.scenario_sources import (
    ScenarioEntitySubject,
    ScenarioSensitivityCapture,
    ScenarioSensitivityMembership,
    ScenarioSourceLicense,
)
from trading212_domain.source_details import (
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    FxObservation,
    LicensePermission,
    MarketSession,
    PriceBasis,
    PriceObservation,
    SourceCalendar,
    SourceCoverage,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceSelectionPolicy,
    SourceSeries,
    SourceSeriesKind,
)
from trading212_domain.values import CurrencyCode
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityVersionModel,
)
from trading212_persistence.scenario_source_store import ScenarioSourceStore
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.source_store import license_view
from trading212_security.principals import Scope
from trading212_worker.xray_fixture import build_xray_fixture, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.premium_report_v3_artifacts import DownloadedReportV3, download_v3
from tests.integration.test_premium_reports_v3_postgres import (
    SavedScenario,
    complete,
    metric,
    no_private_reads,
    saved,
    selection,
    service,
)
from tests.integration.test_scenario_retention_postgres import published
from tests.integration.test_scenario_runs_postgres import ScenarioCase, cancel_scenario
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.unit.domain.scenario_factories import sensitivity_capture

pytestmark = pytest.mark.integration


def sources(case: ScenarioCase) -> PostgresSourceService:
    return PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
    )


async def licensed_provider(case: ScenarioCase, key: str, *, market: bool) -> SourceLicense:
    source = sources(case)
    provider = str(uuid4())
    await source.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=provider,
            key=key,
            name="Synthetic scenario report source",
            adapter_version="scenario-report-fixture-1",
            configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(ports.SourceCapability.PRICE_HISTORY, ports.SourceCapability.FX_RATES)
            if market
            else (),
            supported_price_bases=(PriceBasis.TOTAL_RETURN,) if market else (),
        ),
        idempotency_key=uuid4().hex,
        correlation_id=key,
    )
    license = SourceLicense(
        id=str(uuid4()),
        provider_id=provider,
        version="1",
        effective_at=case.now - timedelta(days=10),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=365,
        attribution="Synthetic report regression only",
        evidence_key=key,
    )
    await source.register_source_license(
        case.principal, license, idempotency_key=uuid4().hex, correlation_id=key
    )
    return license


async def publish_sensitivity(case: ScenarioCase) -> ScenarioSensitivityCapture:
    """Use the private typed adapter publication seam, never a generic/source-array API."""
    license = await licensed_provider(case, "scenario-report-rate", market=False)
    seed = sensitivity_capture()
    owner, provider, license_id = (
        UUID(case.principal.owner_id),
        UUID(license.provider_id),
        UUID(license.id),
    )
    at = case.command.source_cutoff_at - timedelta(days=1)
    evidence = replace(
        seed.evidence[0],
        owner_id=owner,
        provider_id=provider,
        license_version_id=license_id,
        effective_at=at,
        first_known_at=at,
    )
    evidence = replace(evidence, content_digest=scenario_sensitivity_evidence_digest(evidence))
    version = replace(
        seed.versions[0],
        owner_id=owner,
        provider_id=provider,
        license_version_id=license_id,
        effective_at=at,
        first_known_at=at,
        valid_from=at,
    )
    version = replace(version, content_digest=scenario_sensitivity_version_digest(version))
    observation = replace(
        seed.observations[0],
        owner_id=owner,
        provider_id=provider,
        license_version_id=license_id,
        effective_at=at,
        first_known_at=at,
        valid_from=at,
        subject=ScenarioEntitySubject(entity_id=UUID(xray_id("entity/beta"))),
    )
    observation = replace(
        observation, content_digest=scenario_sensitivity_observation_digest(observation)
    )
    capture = ScenarioSensitivityCapture(
        versions=(version,),
        observations=(observation,),
        evidence=(evidence,),
        memberships=(
            ScenarioSensitivityMembership(
                version_id=version.version_id,
                version_digest=version.content_digest,
                observation_id=observation.observation_id,
                observation_digest=observation.content_digest,
            ),
        ),
        licenses=(ScenarioSourceLicense(license_version_id=license_id, license=license),),
    )
    store = ScenarioSourceStore(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
    )
    with case.sessions() as session, session.begin():
        auth = authorize_report_request(
            session,
            case.principal,
            account_id=case.command.account_id,
            required_scopes=frozenset(
                {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.SCENARIOS_WRITE}
            ),
            now=case.now,
        )
        store.publish_capture(session, auth, capture, expires_at=case.now + timedelta(days=30))
        assert session.get_one(ScenarioSensitivityVersionModel, version.version_id).sealed
    return capture


@dataclass(frozen=True)
class ReplaySource:
    selected: ScenarioReplaySelection
    license: SourceLicense
    series: SourceSeries
    price_snapshot_id: str
    fx_snapshot_id: str


async def publish_replay_history(case: ScenarioCase) -> ReplaySource:
    """Three actual dated price/FX observations for the saved USD receipt terminal.

    Retrospective knowledge is explicit: this fixture publishes the completed
    market window at the later holdings cutoff, with no then-known claim.
    """
    license = await licensed_provider(case, "scenario-report-replay", market=True)
    source = sources(case)
    end = case.command.source_cutoff_at.date() - timedelta(days=1)
    start = end - timedelta(days=1)
    days = (start - timedelta(days=1), start, end)
    closes = tuple(datetime.combine(day, time(17), UTC) for day in days)
    period = SourcePeriod(start=days[0], end=days[-1])
    calendar = SourceCalendar(
        id="scenario-report-calendar",
        version="1",
        timezone="UTC",
        period=period,
        sessions=tuple(
            MarketSession(session_date=day, close_at=at)
            for day, at in zip(days, closes, strict=True)
        ),
    )
    await source.register_source_calendar(
        case.principal, calendar, idempotency_key=uuid4().hex, correlation_id="scenario-replay"
    )
    # These are declared fixture identities, not symbol inference or arbitrary caller mappings.
    receipt = next(item for item in build_xray_fixture().listings if item.key == "alpha-adr")
    assert receipt.instrument.isin is not None
    mapping_id = str(uuid4())
    await source.register_source_mapping(
        case.principal,
        SourceInstrumentMapping(
            id=mapping_id,
            provider_id=license.provider_id,
            provider_key="scenario-report-usd-receipt",
            version="1",
            state=SourceMappingState.RESOLVED,
            identifier=SourceIdentifier(
                kind=SourceIdentifierKind.ISIN, value=receipt.instrument.isin
            ),
            currency=CurrencyCode("USD"),
            asset_type="equity",
            evidence_key="scenario-report-receipt",
            valid_from=closes[0] - timedelta(days=1),
            instrument_id=str(receipt.instrument.id),
            listing_id=str(receipt.listing.id),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="scenario-replay",
    )
    series = SourceSeries(
        id=str(uuid4()),
        owner_id=case.principal.owner_id,
        provider_id=license.provider_id,
        license_version_id=license.id,
        kind=SourceSeriesKind.SECURITY_PRICE,
        provider_key="scenario-report-usd-receipt",
        mapping_version="1",
        basis=PriceBasis.TOTAL_RETURN,
        currency=CurrencyCode("USD"),
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        mapping_id=mapping_id,
        instrument_id=str(receipt.instrument.id),
        listing_id=str(receipt.listing.id),
    )
    await source.register_source_series(
        case.principal, series, idempotency_key=uuid4().hex, correlation_id="scenario-replay"
    )
    provenance = SourceProvenance(
        provider_id=license.provider_id,
        license_version_id=license.id,
        adapter_version="scenario-report-fixture-1",
        schema_version="1",
        source_revision="1",
        revision_order=1,
        effective_at=closes[-1],
        first_observed_at=case.now,
        synthetic=True,
    )
    coverage = SourceCoverage(
        expected_count=3, available_count=3, gaps=(), quality=QualityState.FRESH
    )
    price = await source.ingest_price_history(
        case.principal,
        ports.PriceHistoryRequest(series=series, period=period, source_cutoff_at=case.now),
        (
            ports.PriceHistoryPage(
                series=series,
                provenance=provenance,
                period=period,
                coverage=coverage,
                observations=tuple(
                    PriceObservation(session_date=day, effective_at=at, value=Decimal(level))
                    for day, at, level in zip(days, closes, ("100", "110", "121"), strict=True)
                ),
            ),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="scenario-replay-price",
    )
    fx = await source.ingest_fx_rates(
        case.principal,
        ports.FxRatesRequest(
            provider_id=license.provider_id,
            license_version_id=license.id,
            pairs=(ports.FxPair(base=CurrencyCode("USD"), quote=CurrencyCode("EUR")),),
            period=period,
            source_cutoff_at=case.now,
            calendar_id=calendar.id,
            calendar_version=calendar.version,
        ),
        (
            ports.FxRatePage(
                provenance=provenance,
                period=period,
                coverage=coverage,
                observations=tuple(
                    FxObservation(
                        base=CurrencyCode("USD"),
                        quote=CurrencyCode("EUR"),
                        session_date=day,
                        effective_at=at,
                        rate=Decimal(rate),
                        batch_key="scenario-replay-fx",
                    )
                    for day, at, rate in zip(days, closes, ("0.8", "0.84", "0.88"), strict=True)
                ),
            ),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="scenario-replay-fx",
    )
    policy = HistoricalPolicyRegistration(
        id=str(uuid4()),
        key="scenario-report-history",
        effective_at=closes[0],
        accounting_policy=h.HistoricalAccountingPolicy(),
        source_policy=SourceSelectionPolicy(
            version="scenario-report-history-1",
            provider_priority=(license.provider_id,),
            max_age_seconds=86400 * 3,
            allow_closed_session_carry=True,
        ),
        reporting_calendar_ref=h.CalendarRef(id=calendar.id, version=calendar.version),
        price_series_ids=(series.id,),
    )
    await PostgresHistoricalStore(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
    ).register_historical_policy(
        case.principal,
        str(case.command.account_id),
        policy,
        idempotency_key=uuid4().hex,
        correlation_id="scenario-replay-policy",
    )
    captured = await HistoricalCaptureStore(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
    ).capture(
        case.principal,
        str(case.command.account_id),
        request=h.HistoricalSelectionRequest(
            window=h.HistoricalWindow(
                start_date=start,
                end_date=end,
                source_cutoff_at=case.now,
                reporting_currency=case.command.reporting_currency,
                knowledge_policy=h.KnowledgePolicy.AS_OF_CUTOFF,
            ),
            accounting_policy=policy.accounting_policy,
            source_policy=policy.source_policy,
            reporting_calendar_ref=policy.reporting_calendar_ref,
        ),
    )
    assert any(item.id == price.id for item in captured.input.price_snapshots)
    assert any(item.id == fx.id for item in captured.input.fx_snapshots)
    return ReplaySource(
        ScenarioReplaySelection(
            historical_input_snapshot_id=UUID(captured.id),
            start_date=start,
            end_date=end,
            market_knowledge_cutoff_at=case.now,
            holdings_basis="current_holdings",
            knowledge_basis="retrospective",
        ),
        license,
        series,
        price.id,
        fx.id,
    )


async def select_run(
    case: ScenarioCase,
    content: ScenarioVersionContent,
    replay: ScenarioReplaySelection | None = None,
) -> SavedScenario:
    await cancel_scenario(case, case.run.id)
    old = await case.service.get_version(case.principal, case.command.scenario_version_id)
    version = await case.service.create_version(
        case.principal,
        scenarios.CreateScenarioVersion(
            scenario_id=old.definition_id,
            expected_revision=1,
            content=content,
            idempotency_key=uuid4().hex,
            correlation_id="scenario-report-source",
        ),
    )
    case.command = replace(
        case.command, scenario_version_id=version.id, replay=replay, idempotency_key=uuid4().hex
    )
    case.run = await case.service.create_run(case.principal, case.command)
    await published(case)
    return saved(case)


async def report_for(
    case: ScenarioCase, original: SavedScenario
) -> tuple[
    PostgresReportService, app.GenerateReportCommand, app.ReportJobStatus, DownloadedReportV3
]:
    case.now = max(case.now + timedelta(days=1), datetime.now(UTC))
    reports = service(case)
    selected = selection(case)
    replay = original.execution.replay
    selected = replace(
        selected,
        start_date=original.value.valuation_at.date()
        if replay is None
        else replay.selection.start_date,
        end_date=original.value.valuation_at.date()
        if replay is None
        else replay.selection.end_date,
    )
    command = app.GenerateReportCommand(
        selection=selected, idempotency_key=uuid4().hex, ttl_days=30
    )
    with patch(
        "trading212_analytics.scenario.calculate_scenario",
        side_effect=AssertionError("report recomputed saved scenario"),
    ):
        pending = await reports.generate_report(case.principal, command)
    assert pending.expires_at <= original.expires_at
    completed = await complete(case, reports, pending)
    downloaded = await download_v3(reports, case.principal, case.command.account_id, completed)
    assert downloaded.manifest.document.selection == selected
    assert saved(case).input_payload == original.input_payload
    assert saved(case).result_payload == original.result_payload
    return reports, command, completed, downloaded


def money_and_channels(report: DownloadedReportV3, original: SavedScenario) -> None:
    value = original.value
    assert set((*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES)) <= set(report.tables)
    binding = report.manifest.document.premium_binding
    assert isinstance(binding, ReportScenarioRunBinding)
    assert (binding.result_id, binding.result_digest, binding.input_digest) == (
        original.result_id,
        original.result_digest,
        original.execution.input_digest,
    )
    assert binding.xray.input_digest == original.execution.pins.xray_input_digest
    assert binding.xray.result_digest == original.execution.pins.xray_result_digest
    assert not any(item.family is r.ReportFamily.RISK for item in report.manifest.bindings)
    summary = report.rows(r.ReportTableKey.SCENARIO_SUMMARY_V1)[0]
    for field in fields(value.summary):
        expected = getattr(value.summary, field.name)
        if isinstance(expected, ScenarioMoneyMetric):
            metric(report, summary[field.name], expected)
        elif isinstance(expected, int):
            assert summary[field.name].value == expected
    components = {
        str(row["path_key"].value): row
        for row in report.rows(r.ReportTableKey.SCENARIO_COMPONENTS_V1)
    }
    assert set(components) == {item.exposure.path_key for item in value.components}
    for item in value.components:
        row = components[item.exposure.path_key]
        assert (
            row["partition"].value == item.partition
            and row["money_basis"].value == item.money_basis
        )
        for name, expected in (
            ("pre_value", item.exposure.pre_value),
            ("post_value", item.post_value),
            ("impact", item.impact),
            ("rounding_residual", item.rounding_residual),
        ):
            metric(report, row[name], expected)
    channels = report.rows(r.ReportTableKey.SCENARIO_CHANNELS_V1)
    assert len(channels) == 4 * (len(value.components) + 1)
    effects = {item.exposure.path_key: item.effects for item in value.components}
    for row in channels:
        effect = (
            value.summary.effects
            if row["scope"].value == "summary"
            else effects[str(row["path_key"].value)]
        )
        channel = str(row["channel"].value)
        expected = getattr(effect, channel)
        assert isinstance(expected, ScenarioMoneyMetric)
        metric(report, row["effect"], expected)
        if channel != "interaction":
            ratio = getattr(effect, f"{channel}_ratio")
            assert isinstance(ratio, ScenarioRatioMetric)
            metric(report, row["ratio"], ratio)
    # The four-format helper already proves table parity. Require visible named
    # financial rows in PDF too, with actual record boundaries across page breaks.
    compact = "".join(report.pdf_body_text.split())
    for raw, row in zip(
        report.tables[r.ReportTableKey.SCENARIO_COMPONENTS_V1],
        report.rows(r.ReportTableKey.SCENARIO_COMPONENTS_V1),
        strict=True,
    ):
        marker = f"Record:{raw.key}Ordinal:"
        assert compact.count(marker) == 1
        body = compact.split(marker, 1)[1].split("Defaultrowcontext:", 1)[0]
        for column, label in (
            ("pre_value", "Pre-value"),
            ("post_value", "Post-value"),
            ("impact", "Impact"),
        ):
            cell = row[column]
            shown = (
                f"Unavailable({cell.reason_key})"
                if cell.value is None
                else f"{canonical_report_cell_value(cell)}{cell.currency}"
            )
            # The fixed label uses spaces, while exact amount/currency strings remain intact.
            assert f"{label.replace('-', '')}:{shown}".lower() in body.lower()


def members(report: DownloadedReportV3, owner: str, field: str) -> tuple[str, ...]:
    rows = [
        row
        for row in report.rows(r.ReportTableKey.SCENARIO_MEMBERS_V1)
        if row["owner_key"].value == owner and row["field"].value == field
    ]
    rows.sort(key=lambda row: int(str(row["ordinal"].value)))
    return tuple(str(row["reference_id"].value) for row in rows)


async def revoke_original_report_license(
    case: ScenarioCase,
    reports: PostgresReportService,
    command: app.GenerateReportCommand,
    completed: app.ReportJobStatus,
    license: SourceLicense,
) -> None:
    artifact = completed.artifacts[0]
    grant = await reports.create_report_download_grant(
        case.principal, case.command.account_id, completed.job_id, artifact.artifact_id
    )
    with case.sessions() as session:
        pinned = license_view(session.get_one(ProviderLicenseVersionModel, UUID(license.id)))
        assert pinned == license
    await sources(case).register_source_license(
        case.principal,
        replace(
            license,
            id=str(uuid4()),
            version="2-report-denied",
            effective_at=case.now,
            report=LicensePermission.DENIED,
        ),
        idempotency_key=uuid4().hex,
        correlation_id="scenario-report-revoke",
    )
    account = case.command.account_id
    with no_private_reads(case):
        for operation in (
            partial(reports.get_report_status, case.principal, account, completed.job_id),
            partial(reports.get_report_manifest, case.principal, account, completed.job_id),
            partial(
                reports.create_report_download_grant,
                case.principal,
                account,
                completed.job_id,
                artifact.artifact_id,
            ),
            partial(
                reports.download_report_artifact,
                case.principal,
                account,
                completed.job_id,
                artifact.artifact_id,
                grant_token=grant.token,
            ),
            partial(reports.generate_report, case.principal, command),
            partial(
                reports.generate_report,
                case.principal,
                replace(command, idempotency_key=uuid4().hex),
            ),
        ):
            with pytest.raises(app.ReportServiceError) as denied:
                await operation()
            assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    # REPORT-only restriction must not fabricate source expiry or deny licensed display.
    run = await case.service.get_run(
        case.principal, case.run.id, scenarios.ScenarioComponentPageQuery()
    )
    assert run.result is not None and run.result_availability == "available"


async def test_nonempty_sensitivity_evidence_four_formats_and_original_report_license(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    capture = await publish_sensitivity(case)
    version, observation, evidence = (
        capture.versions[0],
        capture.observations[0],
        capture.evidence[0],
    )
    assert isinstance(observation.subject, ScenarioEntitySubject)
    shock = ScenarioRateShock(
        source=ScenarioSensitivityVersionPin(
            version_id=version.version_id,
            content_digest=version.content_digest,
            driver_id=version.driver.driver_id,
            driver_definition_version_id=version.driver.definition_version_id,
        ),
        size=Decimal("0.01"),
    )
    original = await select_run(
        case,
        ScenarioVersionContent(
            name="Retained rate source",
            description="Exact licensed local coefficient",
            mode="compounded",
            shocks=(shock,),
        ),
    )
    assert (
        original.execution.sensitivities == capture
        and original.value.sensitivity_source_row_count == 3
    )
    uses = [
        (component.exposure.path_key, ordinal, use)
        for component in original.value.components
        for ordinal, use in enumerate(component.sensitivity_uses)
    ]
    resolved = [use for _, _, use in uses if use.reason is None]
    assert resolved and any(use.reason is ScenarioReason.MISSING_SENSITIVITY for _, _, use in uses)
    assert all(
        use.observation_id == observation.observation_id
        and use.coefficient == Decimal("-2")
        and use.effect_ratio.value == Decimal("-0.02")
        for use in resolved
    )
    assert all(
        component.effects.factor_ratio.value == Decimal("-0.02")
        for component in original.value.components
        if any(use.reason is None for use in component.sensitivity_uses)
    )
    reports, command, completed, report = await report_for(case, original)
    money_and_channels(report, original)
    assert report.rows(r.ReportTableKey.SCENARIO_SHOCKS_V1)[0][
        "rule_key"
    ].value == scenario_rule_key(shock)
    sources_table = report.rows(r.ReportTableKey.SCENARIO_SENSITIVITY_VERSIONS_V1)
    assert len(sources_table) == 1
    assert sources_table[0]["version_id"].value == str(version.version_id)
    assert sources_table[0]["content_digest"].value == version.content_digest
    driver = report.rows(r.ReportTableKey.SCENARIO_DRIVERS_V1)
    assert len(driver) == 1
    assert driver[0]["driver_id"].value == str(version.driver.driver_id)
    assert driver[0]["definition_version_id"].value == str(version.driver.definition_version_id)
    assert driver[0]["definition_digest"].value == version.driver.definition_digest
    assert driver[0]["shock_unit"].value == "absolute_rate_change"
    assert members(
        report, report.tables[r.ReportTableKey.SCENARIO_DRIVERS_V1][0].key, "evidence_reference_ids"
    ) == tuple(map(str, version.driver.evidence_reference_ids))
    observed = report.rows(r.ReportTableKey.SCENARIO_SENSITIVITY_OBSERVATIONS_V1)
    assert len(observed) == 1
    for field, expected in (
        ("observation_id", str(observation.observation_id)),
        ("version_id", str(version.version_id)),
        ("content_digest", observation.content_digest),
        ("subject_id", str(observation.subject.entity_id)),
        ("coefficient", Decimal("-2")),
        ("response_currency", "EUR"),
        ("effective_at", observation.effective_at),
        ("first_known_at", observation.first_known_at),
        ("license_version_id", str(observation.license_version_id)),
    ):
        assert observed[0][field].value == expected
    assert observed[0]["coefficient"].origin is r.ReportMetricOrigin.NORMALIZED_PROVIDER
    assert members(
        report,
        report.tables[r.ReportTableKey.SCENARIO_SENSITIVITY_OBSERVATIONS_V1][0].key,
        "evidence_reference_ids",
    ) == tuple(map(str, observation.evidence_reference_ids))
    evidence_rows = report.rows(r.ReportTableKey.SCENARIO_SENSITIVITY_EVIDENCE_V1)
    assert len(evidence_rows) == 1
    for evidence_field in fields(evidence):
        expected = getattr(evidence, evidence_field.name)
        assert evidence_rows[0][evidence_field.name].value == (
            str(expected) if isinstance(expected, UUID) else expected
        )
    license_rows = report.rows(r.ReportTableKey.SCENARIO_SOURCE_LICENSES_V1)
    assert len(license_rows) == 1
    assert license_rows[0]["license_version_id"].value == str(
        capture.licenses[0].license_version_id
    )
    for license_field in fields(capture.licenses[0].license):
        assert license_rows[0][license_field.name].value == getattr(
            capture.licenses[0].license, license_field.name
        )
    member = report.rows(r.ReportTableKey.SCENARIO_SENSITIVITY_MEMBERSHIPS_V1)
    assert len(member) == 1
    assert {name: cell.value for name, cell in member[0].items()} == {
        "version_id": str(version.version_id),
        "version_digest": version.content_digest,
        "observation_id": str(observation.observation_id),
        "observation_digest": observation.content_digest,
    }
    applied = report.rows(r.ReportTableKey.SCENARIO_APPLIED_SENSITIVITIES_V1)
    assert len(applied) == len(uses)
    for path, ordinal, use in uses:
        index = next(
            i
            for i, row in enumerate(applied)
            if row["path_key"].value == path and row["ordinal"].value == ordinal
        )
        row, raw = (
            applied[index],
            report.tables[r.ReportTableKey.SCENARIO_APPLIED_SENSITIVITIES_V1][index],
        )
        assert row["observation_id"].value == (
            None if use.observation_id is None else str(use.observation_id)
        )
        assert row["coefficient"].value == use.coefficient
        assert row["coefficient"].state is (
            r.CellState.UNAVAILABLE if use.coefficient is None else r.CellState.AVAILABLE
        )
        assert row["reason"].value == use.reason and row["shock_size"].value == shock.size
        assert row["version_id"].value == str(version.version_id)
        metric(report, row["effect_ratio"], use.effect_ratio)
        assert members(report, raw.key, "candidate_observation_ids") == tuple(
            map(str, use.candidate_observation_ids)
        )
        assert members(report, raw.key, "evidence_reference_ids") == tuple(
            map(str, use.driver.evidence_reference_ids)
        )
    headers = report.rows(r.ReportTableKey.SCENARIO_SOURCE_HEADERS_V1)
    assert len(headers) == 3
    with case.sessions() as session:
        originals: tuple[
            tuple[
                str,
                ScenarioSensitivityVersionModel
                | ScenarioSensitivityObservationModel
                | ScenarioSensitivityEvidenceModel,
                UUID,
            ],
            ...,
        ] = (
            (
                "scenario_sensitivity_version",
                session.get_one(ScenarioSensitivityVersionModel, version.version_id),
                version.version_id,
            ),
            (
                "scenario_sensitivity_observation",
                session.get_one(ScenarioSensitivityObservationModel, observation.observation_id),
                observation.observation_id,
            ),
            (
                "scenario_sensitivity_evidence",
                session.get_one(ScenarioSensitivityEvidenceModel, evidence.id),
                evidence.id,
            ),
        )
        for kind, header, identifier in originals:
            row = next(row for row in headers if row["source_kind"].value == kind)
            assert (
                row["subject_id"].value == str(identifier)
                and row["created_at"].value == header.created_at
            )
            assert row["content_digest"].value == header.content_digest
            assert row["expires_at"].value == (
                header.expires_at if isinstance(header, ScenarioSensitivityVersionModel) else None
            )
            assert header.created_at < case.now
    assert str(evidence.source_record_id) in "".join(report.pdf_body_text.split())
    assert "Coefficient: -2" in " ".join(report.pdf_body_text.split())
    await revoke_original_report_license(
        case, reports, command, completed, capture.licenses[0].license
    )


async def test_saved_historical_replay_four_formats_complete_trace_and_original_report_license(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    source = await publish_replay_history(case)
    original = await select_run(
        case,
        ScenarioVersionContent(
            name="Saved market replay",
            description="Retrospective market, current retained holdings",
            mode="compounded",
        ),
        source.selected,
    )
    execution, replay = original.execution.replay, original.value.replay
    assert execution is not None and replay is not None
    assert (
        execution.historical_input.selection.window.knowledge_policy
        is h.KnowledgePolicy.AS_OF_CUTOFF
    )
    assert source.series.instrument_id is not None
    bound = next(
        item
        for item in execution.market_bindings
        if item.instrument_id == UUID(source.series.instrument_id)
    )
    assert bound.local_series_id == UUID(source.series.id) and bound.reason is None
    assert source.price_snapshot_id in bound.source_reference_ids
    receipt_paths = {
        item.exposure.path_key
        for item in original.value.components
        if item.exposure.instrument.subject_id == bound.instrument_id
    }
    available = [item for item in replay.changes if item.path_key in receipt_paths]
    assert available and all(
        item.local_return.value == Decimal("0.21")
        and item.fx_return.value == Decimal("0.1")
        and item.reporting_return.value == Decimal("0.331")
        for item in available
    )
    assert any(
        item.reporting_return.reason is ScenarioReason.MISSING_REPLAY_MAPPING
        for item in replay.changes
    )
    assert replay.source_uses and replay.conversions
    assert {
        item.snapshot_id
        for item in replay.source_uses
        if isinstance(item, hr.HistoricalObservationUse)
    } >= {source.price_snapshot_id, source.fx_snapshot_id}
    reports, command, completed, report = await report_for(case, original)
    money_and_channels(report, original)
    binding = report.manifest.document.premium_binding
    assert isinstance(binding, ReportScenarioRunBinding) and binding.historical is not None
    assert binding.historical.input_snapshot_id == source.selected.historical_input_snapshot_id
    assert binding.historical.input_digest == execution.historical_input_digest
    selected = report.manifest.document.selection
    assert (selected.start_date, selected.end_date) == (
        source.selected.start_date,
        source.selected.end_date,
    )
    basis = report.rows(r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1)[0]
    for name, expected in (
        ("start_date", source.selected.start_date),
        ("end_date", source.selected.end_date),
        ("market_knowledge_cutoff_at", source.selected.market_knowledge_cutoff_at),
        ("holdings_evidence_at", original.execution.xray_input.valuation_at.value),
        ("holdings_knowledge_cutoff_at", original.execution.xray_input.source_cutoff_at.value),
        ("knowledge_basis", "retrospective"),
        ("holdings_basis", "current_holdings"),
    ):
        assert basis[name].value == expected
    bindings = report.rows(r.ReportTableKey.SCENARIO_REPLAY_BINDINGS_V1)
    assert len(bindings) == len(execution.market_bindings)
    for ordinal, expected_binding in enumerate(execution.market_bindings):
        row = next(
            row
            for row in bindings
            if row["instrument_id"].value == str(expected_binding.instrument_id)
        )
        assert row["local_series_id"].value == (
            None
            if expected_binding.local_series_id is None
            else str(expected_binding.local_series_id)
        )
        assert row["response_basis"].value == expected_binding.response_basis
        assert row["reason"].value == expected_binding.reason
        raw = report.tables[r.ReportTableKey.SCENARIO_REPLAY_BINDINGS_V1][ordinal]
        assert (
            members(report, raw.key, "source_reference_ids")
            == expected_binding.source_reference_ids
        )
    changes = report.rows(r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1)
    assert len(changes) == len(replay.changes) == len(original.value.components)
    for expected_change in replay.changes:
        index = next(
            i for i, row in enumerate(changes) if row["path_key"].value == expected_change.path_key
        )
        for name in ("local_return", "fx_return", "reporting_return"):
            metric(report, changes[index][name], getattr(expected_change, name))
        raw = report.tables[r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1][index]
        assert members(report, raw.key, "source_use_keys") == expected_change.source_use_keys
        assert members(report, raw.key, "conversion_keys") == expected_change.conversion_keys
    uses = {
        str(row["use_key"].value): row
        for key in (
            r.ReportTableKey.HISTORICAL_OBSERVATION_USES,
            r.ReportTableKey.HISTORICAL_EVIDENCE_USES,
            r.ReportTableKey.HISTORICAL_MISSING_USES,
        )
        if key in report.tables
        for row in report.rows(key)
    }
    assert set(uses) == {item.use_key for item in replay.source_uses}
    consumers = {
        str(row["use_key"].value): row
        for row in report.rows(r.ReportTableKey.HISTORICAL_USE_CONSUMERS)
    }
    assert set(consumers) == set(uses)
    for use in replay.source_uses:
        row = uses[use.use_key]
        assert (
            row["use_at"].value == use.use_at
            and row["knowledge_cutoff_at"].value == use.knowledge_cutoff_at
        )
        assert row["role"].value == use.role
        for field in fields(use.consumer):
            assert consumers[use.use_key][field.name].value == getattr(use.consumer, field.name)
        if isinstance(use, hr.HistoricalObservationUse):
            assert row["snapshot_id"].value == use.snapshot_id
            assert row["observation_index"].value == use.observation_index
            assert row["source_kind"].value == use.source_kind
            leg = use.conversion_leg
            assert row["conversion_key"].value == (None if leg is None else leg.conversion_key)
            if leg is not None:
                assert row["leg_ordinal"].value == leg.ordinal
                assert row["direction"].value == leg.direction
                assert row["base"].value == leg.base.value and row["quote"].value == leg.quote.value
        elif isinstance(use, hr.HistoricalMissingUse):
            assert (
                row["reason"].value == use.reason
                and row["expected_session"].value == use.expected_session
            )
        else:
            assert row["reference_kind"].value == use.reference_kind
            assert row["reference_id"].value == use.reference_id
    conversions = report.rows(r.ReportTableKey.HISTORICAL_CONVERSION_USES)
    assert len(conversions) == len(replay.conversions) > 0
    for expected_conversion in replay.conversions:
        row = next(
            row
            for row in conversions
            if row["conversion_key"].value == expected_conversion.conversion_key
        )
        assert (
            row["rate"].value == expected_conversion.rate
            and row["use_at"].value == expected_conversion.use_at
        )
        assert (
            row["base"].value == expected_conversion.base.value
            and row["quote"].value == expected_conversion.quote.value
        )
        assert row["operation"].value == expected_conversion.operation
        legs = [
            row
            for row in report.rows(r.ReportTableKey.HISTORICAL_CONVERSION_LEGS)
            if row["conversion_key"].value == expected_conversion.conversion_key
        ]
        assert (
            tuple(
                row["leg_use_key"].value
                for row in sorted(legs, key=lambda row: int(str(row["ordinal"].value)))
            )
            == expected_conversion.leg_use_keys
        )
    coverage = report.rows(r.ReportTableKey.SCENARIO_REPLAY_COVERAGE_V1)
    assert len(coverage) == len(replay.context.coverage.measures)
    for ordinal, expected_coverage in enumerate(replay.context.coverage.measures):
        row = next(row for row in coverage if row["ordinal"].value == ordinal)
        assert row["coverage_key"].value == expected_coverage.key
        assert row["expected_count"].value == expected_coverage.expected_count
        assert row["available_count"].value == expected_coverage.available_count
        assert row["complete"].value == expected_coverage.complete
        raw = report.tables[r.ReportTableKey.SCENARIO_REPLAY_COVERAGE_V1][ordinal]
        assert members(report, raw.key, "reasons") == tuple(map(str, expected_coverage.reasons))
    warnings = report.rows(r.ReportTableKey.SCENARIO_REPLAY_WARNINGS_V1)
    assert len(warnings) == len(replay.context.warnings)
    for ordinal, expected_warning in enumerate(replay.context.warnings):
        row = next(row for row in warnings if row["ordinal"].value == ordinal)
        assert row["reason_code"].value == expected_warning.reason_code
        assert row["coverage_key"].value == expected_warning.coverage_key
        raw = report.tables[r.ReportTableKey.SCENARIO_REPLAY_WARNINGS_V1][ordinal]
        assert members(report, raw.key, "reference_ids") == expected_warning.reference_ids
    references = {str(item.subject_id) for item in report.manifest.source_references}
    assert {source.price_snapshot_id, source.fx_snapshot_id} <= references
    for identifier in (source.price_snapshot_id, source.fx_snapshot_id):
        original_reference = next(
            item for item in execution.historical_input.sources if item.id == identifier
        )
        reference = next(
            item for item in report.manifest.source_references if str(item.subject_id) == identifier
        )
        assert reference.content_digest == original_reference.semantic_digest
        assert reference.provider_id == UUID(source.license.provider_id)
        assert reference.license_version_id == UUID(source.license.id)
    text = " ".join(report.pdf_body_text.split())
    assert (
        "Local return: 0.21" in text
        and "Fx return: 0.1" in text
        and "Reporting return: 0.331" in text
    )
    await revoke_original_report_license(case, reports, command, completed, source.license)
