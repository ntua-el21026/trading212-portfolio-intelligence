"""All fixed alert metrics consume real canonical producers, independently of job tests.

Each rule is saved and activated. The capture port is evaluated at a real current
cutoff; scheduler alignment and durable job execution are tested separately.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.alerts import evaluate_alert
from trading212_application import alerts as app
from trading212_application import xray as xray_app
from trading212_domain import alerts as d
from trading212_domain.alert_serialization import (
    decode_alert_input,
    encode_alert_input,
    encode_alert_result,
)
from trading212_domain.enums import QualityState
from trading212_domain.reports import ReportSourceKind
from trading212_domain.values import CurrencyCode
from trading212_persistence.alert_authorization import authorize_alert_request
from trading212_persistence.alert_capture import CanonicalAlertCapture
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.xray_run_models import XrayRunModel
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Principal
from trading212_worker.xray_fixture import xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.unit.analytics.alert_factories import predicate

pytestmark = pytest.mark.integration
EUR = CurrencyCode("EUR")


@dataclass(frozen=True)
class Matrix:
    sessions: sessionmaker[Session]
    principal: Principal
    account_id: UUID
    key: bytes = XRAY_CURSOR_KEY

    async def activate(self, selected: d.AlertPredicate) -> d.AlertRuleVersion:
        service = PostgresAlertService(self.sessions, cursor_signing_key=self.key)
        value = await service.create_rule(
            self.principal,
            app.CreateAlertRuleCommand(
                account_id=self.account_id,
                definition=d.AlertRuleDefinition(
                    name=f"Canonical {selected.metric.value}",
                    predicate=selected,
                    schedule=d.AlertIntervalSchedule(anchor_at=datetime.now(UTC)),
                    quality_policy=d.AlertQualityPolicy.ALLOW_DEGRADED,
                ),
            ),
            idempotency_key=uuid4().hex,
            correlation_id="canonical-alert-matrix",
        )
        active = await service.activate_rule(
            self.principal,
            value.id,
            value.latest_version.id,
            expected_revision=value.revision,
            idempotency_key=uuid4().hex,
            correlation_id="canonical-alert-matrix",
        )
        assert active.active_version is not None
        return active.active_version

    def capture(
        self, version: d.AlertRuleVersion, *, cutoff: datetime | None = None
    ) -> tuple[d.AlertEvaluationInput, d.AlertEvaluationResult]:
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            authorization = authorize_alert_request(
                session,
                self.principal,
                account_id=self.account_id,
                now=now,
                write=True,
                definition=version.definition,
            )
            value = CanonicalAlertCapture(
                session, authorization, now=now, cursor_signing_key=self.key, sessions=self.sessions
            ).capture_evaluation(version, cutoff or now, d.AlertExecutionIntent.LIVE)
        assert value.version == version
        assert all(context.account_id == self.account_id for context in value.contexts)
        assert all(
            max(source.effective_at, source.first_observed_at) <= value.source_cutoff_at
            for source in value.source_references
        )
        result = evaluate_alert(value)
        assert result.input_digest and len(encode_alert_input(value)) <= d.MAX_ALERT_INPUT_BYTES
        assert encode_alert_result(
            evaluate_alert(decode_alert_input(encode_alert_input(value)))
        ) == encode_alert_result(result)
        assert b"comparison_basis" not in encode_alert_result(result)
        return value, result


def scalar(result: d.AlertEvaluationResult) -> Decimal | int | bool:
    assert result.observation is not None and result.observation.value is not None, result
    assert result.outcome not in {
        d.AlertEvaluationOutcome.FAILED,
        d.AlertEvaluationOutcome.UNAVAILABLE,
    }, result
    return result.observation.value


def test_actual_portfolio_and_xray_capture_metrics_preserve_exact_values_and_late_run_knowledge(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        matrix = Matrix(report_case.base.sessions, report_case.principal, report_case.account_id)
        financial = {
            d.AlertMetric.DIRECT_MAX_WEIGHT: Decimal("0.5"),
            d.AlertMetric.DIRECT_TOP_N_WEIGHT: Decimal("1"),
            d.AlertMetric.DIRECT_HHI: Decimal("0.35"),
            d.AlertMetric.CASH_AMOUNT: Decimal("0"),
            d.AlertMetric.CASH_WEIGHT: Decimal("0"),
            d.AlertMetric.EFFECTIVE_ENTITY_WEIGHT: Decimal("0.56"),
            d.AlertMetric.EFFECTIVE_TOP_N_WEIGHT: Decimal("0.95"),
            d.AlertMetric.EFFECTIVE_HHI: Decimal("0.4657"),
            d.AlertMetric.ETF_PAIR_OVERLAP: Decimal("0.5"),
            d.AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE: Decimal("0.41"),
        }
        versions = {}
        for metric in financial:
            selected = predicate(metric)
            if selected.entity_id is not None:
                selected = replace(selected, entity_id=UUID(xray_id("entity/alpha")))
            if selected.left_fund_id is not None:
                selected = replace(
                    selected,
                    left_fund_id=UUID(report_case.base.seed["fund-a_instrument_id"]),
                    right_fund_id=UUID(report_case.base.seed["fund-b_instrument_id"]),
                )
            versions[metric] = await matrix.activate(selected)
        before_run = datetime.now(UTC)
        with matrix.sessions() as session:
            assert session.scalar(select(XrayRunModel.id).limit(1)) is None
        await PostgresXrayService(
            sessions=matrix.sessions, cursor_signing_key=matrix.key
        ).get_effective_exposure(
            matrix.principal,
            str(matrix.account_id),
            query=xray_app.EffectiveExposureQuery(request=report_case.base.request()),
        )
        late, missing = matrix.capture(
            versions[d.AlertMetric.EFFECTIVE_ENTITY_WEIGHT], cutoff=before_run
        )
        assert missing.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
        assert missing.reason is d.AlertReason.MISSING_INPUT
        assert not any(
            binding.family is d.AlertCanonicalFamily.XRAY for binding in late.canonical_bindings
        )
        for metric, expected in financial.items():
            value, result = matrix.capture(versions[metric])
            assert scalar(result) == expected, metric
            assert value.source_references
            if metric in {
                d.AlertMetric.DIRECT_MAX_WEIGHT,
                d.AlertMetric.DIRECT_TOP_N_WEIGHT,
                d.AlertMetric.DIRECT_HHI,
            }:
                # The ordinary worker materializer already normalizes wallet values to EUR.
                # No second conversion is warranted; native wallet capture is tested below.
                assert value.fx_conversions == ()
            if metric in {d.AlertMetric.CASH_AMOUNT, d.AlertMetric.CASH_WEIGHT}:
                assert result.observation is not None
                assert (
                    result.observation.quality is not QualityState.FRESH
                )  # The genuine snapshot is old.
            if metric in {
                d.AlertMetric.EFFECTIVE_ENTITY_WEIGHT,
                d.AlertMetric.EFFECTIVE_TOP_N_WEIGHT,
                d.AlertMetric.EFFECTIVE_HHI,
                d.AlertMetric.ETF_PAIR_OVERLAP,
                d.AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE,
            }:
                assert isinstance(value.payload, d.AlertThresholdInput)
                assert isinstance(value.payload.observation.comparison_basis, d.AlertRatioBasis)
                assert (
                    result.observation is not None
                    and result.observation.bound is d.AlertBound.LOWER_BOUND
                )
                assert result.observation.quality is not QualityState.FRESH
                assert any(
                    warning.code == "valuation_warning" for warning in value.contexts[0].warnings
                )
                assert {
                    binding.role
                    for binding in value.canonical_bindings
                    if binding.family is d.AlertCanonicalFamily.XRAY
                } == {d.AlertInputRole.INPUT, d.AlertInputRole.RESULT}
                assert value.licenses and any(ref.provider_id for ref in value.source_references)
            else:
                assert any(
                    binding.role is d.AlertInputRole.SNAPSHOT
                    for binding in value.canonical_bindings
                )
        with matrix.sessions() as session:
            snapshot = session.get_one(
                PortfolioSnapshotModel, UUID(report_case.base.seed["snapshot_id"])
            )
            assert snapshot.portfolio_total == Decimal("1000")
        # Independent full-root HHI oracle: four EUR50 direct roots and EUR500/EUR300 funds.
        exact = sum(
            (Fraction(amount, 1000) ** 2 for amount in (50, 50, 50, 50, 500, 300)), Fraction()
        )
        with localcontext() as ctx:
            ctx.prec = 80
            assert financial[d.AlertMetric.DIRECT_HHI] == Decimal(exact.numerator) / Decimal(
                exact.denominator
            )

    asyncio.run(run())


def test_native_wallet_snapshot_uses_actual_broker_fx_once_in_direct_capture(
    report_case: ReportCase,
) -> None:
    from trading212_analytics.portfolio import (
        CashComponentInput,
        FxQuote,
        ValuedPositionInput,
        aggregate_portfolio,
        build_portfolio_snapshot,
    )
    from trading212_analytics.quality import combine_quality
    from trading212_domain import (
        BrokerAccountId,
        CalculationMetadata,
        CalculationRunId,
        DataQuality,
        Instant,
        ListingId,
        Quantity,
        SnapshotId,
    )
    from trading212_domain.values import FxRate, Money
    from trading212_persistence.models import (
        CalculationRunModel,
        CashBalanceObservationModel,
        PositionObservationModel,
        SnapshotPositionModel,
        SourceRecordModel,
    )
    from trading212_persistence.planning_inputs import digest
    from trading212_persistence.repositories import SnapshotRepository, SnapshotWriteContext
    from trading212_worker.materializer import _coverage, _provenance

    async def run() -> None:
        matrix = Matrix(report_case.base.sessions, report_case.principal, report_case.account_id)
        with matrix.sessions() as session, session.begin():
            original = session.get_one(
                PortfolioSnapshotModel, UUID(report_case.base.seed["snapshot_id"])
            )
            previous = session.get_one(CalculationRunModel, original.calculation_run_id)
            source_ids = tuple(UUID(item) for item in previous.input_ids)
            records = tuple(
                session.scalars(
                    select(SourceRecordModel)
                    .where(SourceRecordModel.id.in_(source_ids))
                    .order_by(SourceRecordModel.id)
                )
            )
            by_id = {item.id: item for item in records}
            native = tuple(
                session.scalars(
                    select(PositionObservationModel)
                    .where(
                        PositionObservationModel.broker_account_id == matrix.account_id,
                        PositionObservationModel.source_record_id.in_(source_ids),
                    )
                    .order_by(PositionObservationModel.listing_id)
                )
            )
            balances = tuple(
                session.scalars(
                    select(CashBalanceObservationModel)
                    .where(
                        CashBalanceObservationModel.broker_account_id == matrix.account_id,
                        CashBalanceObservationModel.source_record_id.in_(source_ids),
                    )
                    .order_by(CashBalanceObservationModel.currency)
                )
            )
            normalized = tuple(
                session.scalars(
                    select(SnapshotPositionModel).where(
                        SnapshotPositionModel.snapshot_id == original.id
                    )
                )
            )
            assert len(native) == len(normalized) == 6 and len(balances) == 1
            assert all(row.currency == "EUR" for row in normalized)
            usd = next(row for row in native if row.valuation_currency == "USD")
            assert usd.provider_market_value == Decimal("62.5")
            quote_rows = previous.options["fx_quotes"]
            assert isinstance(quote_rows, list) and len(quote_rows) == 1
            quote_row = quote_rows[0]
            assert isinstance(quote_row, dict) and isinstance(quote_row["rate"], str)
            source = by_id[UUID(str(quote_row["source_record_id"]))]
            assert source.id == usd.source_record_id
            fx_at = datetime.fromisoformat(str(quote_row["observed_at"]).replace("Z", "+00:00"))
            assert fx_at == source.source_updated_at
            quote = FxQuote(
                FxRate(
                    CurrencyCode(str(quote_row["base_currency"])),
                    CurrencyCode(str(quote_row["quote_currency"])),
                    Decimal(quote_row["rate"]),
                    Instant(fx_at),
                    str(source.id),
                )
            )
            positions = tuple(
                ValuedPositionInput(
                    account_id=BrokerAccountId(matrix.account_id),
                    listing_id=ListingId(row.listing_id),
                    quantity=Quantity(row.quantity),
                    valuation_currency=CurrencyCode(row.valuation_currency),
                    provider_market_value=None
                    if row.provider_market_value is None
                    else Money(row.provider_market_value, CurrencyCode(row.valuation_currency)),
                    provider_unrealized_pnl=None
                    if row.provider_unrealized_pnl is None
                    else Money(row.provider_unrealized_pnl, CurrencyCode(row.valuation_currency)),
                )
                for row in native
            )
            cash = tuple(
                CashComponentInput(
                    BrokerAccountId(matrix.account_id),
                    row.currency,
                    Money(row.amount, CurrencyCode(row.currency)),
                )
                for row in balances
            )
            observed_at = Instant(datetime.now(UTC))
            aggregate = aggregate_portfolio(
                account_id=BrokerAccountId(matrix.account_id),
                positions=positions,
                cash_components=cash,
                reporting_currency=EUR,
                fx_quotes=(quote,),
                valuation_at=observed_at,
                source_cutoff_at=Instant(original.source_cutoff_at),
            )
            assert aggregate.portfolio_total == Money(Decimal("1000"), EUR)
            assert previous.coverage.get("complete") is True
            coverage = _coverage(records, end_at=original.source_cutoff_at)
            metadata = CalculationMetadata(
                calculation_name=aggregate.method_id,
                version=aggregate.version,
                run_id=CalculationRunId(uuid4()),
                calculated_at=observed_at,
                valuation_at=aggregate.valuation_at,
                source_cutoff_at=aggregate.source_cutoff_at,
                reporting_currency=EUR,
                input_ids=source_ids,
                method="Canonical portfolio aggregation retaining native observed wallet values",
                assumptions=(
                    "Native wallet values are retained; the actual sourced broker quote "
                    "converts the reporting total once.",
                    "The new valuation retains the original source cutoff and explicitly "
                    "carries stale source quality.",
                ),
                data_quality=DataQuality(
                    combine_quality(
                        (
                            aggregate.quality_state,
                            QualityState.STALE,
                            QualityState.FRESH if coverage.complete else QualityState.PARTIAL,
                        )
                    ),
                    observed_at,
                    900,
                    coverage,
                    warnings=aggregate.warnings,
                    missing_inputs=aggregate.missing_inputs,
                ),
                options=previous.options,
            )
            snapshot = build_portfolio_snapshot(
                aggregate,
                snapshot_id=SnapshotId(uuid4()),
                positions=positions,
                cash_components=cash,
                calculation=metadata,
            )
            persisted = SnapshotRepository(session).persist_immutable(
                snapshot,
                context=SnapshotWriteContext(
                    input_schema_version=previous.input_schema_version,
                    output_schema_version=previous.output_schema_version,
                    input_fingerprint=digest(
                        (
                            positions,
                            cash,
                            quote,
                            source_ids,
                            aggregate.valuation_at,
                            aggregate.source_cutoff_at,
                        )
                    ),
                    output_fingerprint=digest(snapshot),
                    position_currencies={
                        ListingId(row.listing_id): CurrencyCode(row.valuation_currency)
                        for row in native
                    },
                    position_provenance={
                        ListingId(row.listing_id): _provenance(by_id[row.source_record_id])
                        for row in native
                    },
                    cash_provenance={
                        CurrencyCode(row.currency): _provenance(by_id[row.source_record_id])
                        for row in balances
                    },
                ),
            )
            assert persisted.snapshot_created and persisted.snapshot_id != original.id
        for metric, expected in (
            (d.AlertMetric.DIRECT_MAX_WEIGHT, Decimal("0.5")),
            (d.AlertMetric.DIRECT_TOP_N_WEIGHT, Decimal("1")),
            (d.AlertMetric.DIRECT_HHI, Decimal("0.35")),
        ):
            value, result = matrix.capture(await matrix.activate(predicate(metric)))
            assert scalar(result) == expected
            assert value.contexts[0].valuation_at == observed_at.value
            assert value.contexts[0].quality is not QualityState.FRESH
            assert any(
                pin.subject_id == persisted.snapshot_id and pin.role is d.AlertInputRole.SNAPSHOT
                for pin in value.canonical_bindings
            )
            (conversion,) = value.fx_conversions
            assert conversion.original == Money(Decimal("62.5"), CurrencyCode("USD"))
            assert conversion.converted == Money(Decimal("50"), EUR)
            (leg,) = conversion.legs
            assert leg.rate == Decimal("0.8") and not leg.inverse
            assert leg.provider_id is None and leg.snapshot_id is None
            retained = next(
                ref for ref in value.source_references if ref.key == leg.source_reference_key
            )
            assert retained.kind is ReportSourceKind.BROKER_SOURCE_RECORD
            assert retained.subject_id == source.id and retained.effective_at == leg.observed_at
            assert retained.content_digest == source.payload_fingerprint
        # Independent rational oracle includes all original held roots, not only the FX row.
        assert sum(
            (Fraction(amount, 1000) ** 2 for amount in (50, 50, 50, 50, 500, 300)), Fraction()
        ) == Fraction(35, 100)

    asyncio.run(run())


def test_actual_target_and_reconciliation_metrics_bind_saved_canonical_inputs(
    report_case: ReportCase,
) -> None:
    from trading212_analytics.planning import calculate_drift
    from trading212_domain import build_synthetic_identity
    from trading212_domain import planning as p
    from trading212_domain.values import Money
    from trading212_persistence.models import ReconciliationRunModel
    from trading212_persistence.planning_inputs import capture_input, digest
    from trading212_persistence.target_models import (
        TargetHoldingModel,
        TargetNodeModel,
        TargetVersionModel,
        VirtualPortfolioModel,
    )
    from trading212_persistence.target_service import PostgresTargetService
    from trading212_worker.scenarios import persist_quantity_cash_mismatch_scenario

    async def run() -> None:
        matrix = Matrix(
            report_case.base.sessions, report_case.principal, build_synthetic_identity().account.id
        )
        with matrix.sessions() as session:
            target = session.scalar(
                select(TargetVersionModel)
                .join(VirtualPortfolioModel)
                .where(
                    VirtualPortfolioModel.broker_account_id == matrix.account_id,
                    TargetVersionModel.published_at.is_not(None),
                )
            )
            snapshot = session.scalar(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.broker_account_id == matrix.account_id
                )
            )
            assert target is not None and snapshot is not None
            nodes = session.scalars(
                select(TargetNodeModel).where(TargetNodeModel.target_version_id == target.id)
            ).all()
            group = next(row for row in nodes if row.kind == "group")
            holding = session.scalar(
                select(TargetHoldingModel).where(TargetHoldingModel.target_version_id == target.id)
            )
            assert holding is not None
            original = capture_input(
                session,
                owner=UUID(matrix.principal.owner_id),
                account=matrix.account_id,
                portfolio_id=target.virtual_portfolio_id,
                target_id=target.id,
                snapshot_id=snapshot.id,
                options=p.PlanningOptions(
                    Money(Decimal(0), EUR), p.PlanningMode.GLOBAL, p.CoveragePolicy.ALLOW_DEGRADED
                ),
                targets=PostgresTargetService(
                    sessions=matrix.sessions, cursor_signing_key=matrix.key
                ),
            )
            original_digest = digest(original)
            canonical = calculate_drift(original)
        for metric in (
            d.AlertMetric.PORTFOLIO_L1_DRIFT,
            d.AlertMetric.GROUP_ABSOLUTE_DRIFT,
            d.AlertMetric.HOLDING_ABSOLUTE_DRIFT,
        ):
            chosen = predicate(metric)
            chosen = replace(
                chosen,
                target_version_id=target.id,
                group_node_id=group.id if chosen.group_node_id is not None else None,
                holding_id=holding.id if chosen.holding_id is not None else None,
            )
            version = await matrix.activate(chosen)
            value, result = matrix.capture(version)
            actual = scalar(result)
            if metric is d.AlertMetric.GROUP_ABSOLUTE_DRIFT:
                expected = next(
                    row.absolute_drift for row in canonical.rows if row.node_id == str(group.id)
                )
            elif metric is d.AlertMetric.HOLDING_ABSOLUTE_DRIFT:
                expected = next(
                    row.absolute_drift
                    for row in canonical.rows
                    if row.holding_id == str(holding.id)
                )
            else:
                selected = [
                    row
                    for row in canonical.rows
                    if row.depth == 1 or row.kind in {"cash", "unclassified"}
                ]
                expected = (
                    sum(
                        (
                            row.signed_drift.copy_abs()
                            for row in selected
                            if row.signed_drift is not None
                        ),
                        Decimal(0),
                    )
                    / 2
                )
            assert actual == expected
            assert any(
                pin.family is d.AlertCanonicalFamily.TARGET
                and pin.subject_id == target.id
                and pin.content_digest == target.content_digest
                for pin in value.canonical_bindings
            )
            assert any(
                pin.family is d.AlertCanonicalFamily.PLANNING
                and pin.role is d.AlertInputRole.INPUT
                and pin.content_digest == original_digest
                for pin in value.canonical_bindings
            )
        # A partial reconciliation is unavailable, never a fabricated failure/clear signal.
        incomplete, partial = matrix.capture(
            await matrix.activate(predicate(d.AlertMetric.RECONCILIATION_FAILED))
        )
        assert partial.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
        assert partial.reason is d.AlertReason.INCOMPLETE_COVERAGE
        assert any(
            ref.kind is ReportSourceKind.RECONCILIATION for ref in incomplete.source_references
        )
        with matrix.sessions() as session, session.begin():
            reconciliation_id = persist_quantity_cash_mismatch_scenario(
                session,
                account_id=matrix.account_id,
                listing_id=build_synthetic_identity().listing.id,
                as_of=datetime.now(UTC),
            )
        for metric in (
            d.AlertMetric.RECONCILIATION_FAILED,
            d.AlertMetric.RECONCILIATION_DISCREPANCY_COUNT,
        ):
            value, result = matrix.capture(await matrix.activate(predicate(metric)))
            with matrix.sessions() as session:
                latest = session.scalar(
                    select(ReconciliationRunModel)
                    .where(
                        ReconciliationRunModel.broker_account_id == matrix.account_id,
                        ReconciliationRunModel.as_of <= value.source_cutoff_at,
                    )
                    .order_by(
                        ReconciliationRunModel.as_of.desc(),
                        ReconciliationRunModel.created_at.desc(),
                        ReconciliationRunModel.id,
                    )
                    .limit(1)
                )
                assert latest is not None
                assert latest.id == reconciliation_id and latest.status == "unreconciled"
                reconciliation_expected = (
                    latest.status in {"failed", "unreconciled"}
                    if metric is d.AlertMetric.RECONCILIATION_FAILED
                    else latest.discrepancy_count
                )
            assert scalar(result) == reconciliation_expected
            assert any(
                ref.kind is ReportSourceKind.RECONCILIATION and ref.subject_id == latest.id
                for ref in value.source_references
            )

    asyncio.run(run())


def test_actual_valuation_classification_constituent_universes_and_explicit_sessions(
    report_case: ReportCase,
) -> None:
    from sqlalchemy import func
    from trading212_domain.sources import MarketSession, SourceCalendar, SourcePeriod
    from trading212_persistence.models import SnapshotCashModel, SnapshotPositionModel
    from trading212_persistence.source_models import SourceCalendarModel
    from trading212_persistence.source_service import PostgresSourceService
    from trading212_persistence.xray_catalog_models import (
        ClassificationSnapshotInstrumentModel,
        ClassificationSnapshotModel,
        ConstituentSnapshotModel,
        XrayTaxonomyModel,
    )

    async def run() -> None:
        matrix = Matrix(report_case.base.sessions, report_case.principal, report_case.account_id)
        with matrix.sessions() as session:
            snapshot = session.get_one(
                PortfolioSnapshotModel, UUID(report_case.base.seed["snapshot_id"])
            )
            classification = session.scalar(
                select(ClassificationSnapshotModel)
                .where(ClassificationSnapshotModel.owner_id == UUID(matrix.principal.owner_id))
                .order_by(ClassificationSnapshotModel.id)
            )
            constituent = session.scalar(
                select(ConstituentSnapshotModel)
                .where(ConstituentSnapshotModel.owner_id == UUID(matrix.principal.owner_id))
                .order_by(ConstituentSnapshotModel.id)
            )
            assert classification is not None and constituent is not None
            requested = session.scalar(
                select(func.count())
                .select_from(ClassificationSnapshotInstrumentModel)
                .where(ClassificationSnapshotInstrumentModel.snapshot_id == classification.id)
            )
            taxonomy = session.get_one(XrayTaxonomyModel, classification.taxonomy_id)
            inventory = sum(
                session.scalar(
                    select(func.count()).select_from(model).where(model.snapshot_id == snapshot.id)
                )
                or 0
                for model in (SnapshotPositionModel, SnapshotCashModel)
            )
        for family, identifier in (
            (d.AlertSourceFamily.VALUATION, snapshot.id),
            (d.AlertSourceFamily.CLASSIFICATION, classification.id),
            (d.AlertSourceFamily.CONSTITUENT, constituent.id),
        ):
            for metric in (d.AlertMetric.MISSING_COUNT, d.AlertMetric.MISSING_FRACTION):
                chosen = replace(predicate(metric), domain=family, source_id=identifier)
                value, result = matrix.capture(await matrix.activate(chosen))
                if (
                    family is d.AlertSourceFamily.CONSTITUENT
                    and metric is d.AlertMetric.MISSING_COUNT
                ):
                    assert (
                        result.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
                        and result.reason is d.AlertReason.UNKNOWN_DENOMINATOR
                    )
                    continue
                actual = scalar(result)
                fact = value.contexts[0].coverage[-1]
                if family is d.AlertSourceFamily.VALUATION:
                    assert fact.expected_count == inventory and actual == 0
                elif family is d.AlertSourceFamily.CLASSIFICATION:
                    assert (
                        fact.expected_count == requested
                        and fact.key == f"classification.{taxonomy.dimension}"
                    )
                    assert fact.available_count is not None and fact.expected_count is not None
                    assert actual == (
                        fact.expected_count - fact.available_count
                        if metric is d.AlertMetric.MISSING_COUNT
                        else (
                            Decimal(fact.expected_count - fact.available_count)
                            / Decimal(fact.expected_count)
                        ).quantize(Decimal("1e-18"))
                    )
                else:
                    assert (
                        constituent.known_weight is not None and constituent.cash_weight is not None
                    )
                    assert actual == Decimal(1) - constituent.known_weight - constituent.cash_weight
                    assert fact.expected_count is None
        dates = tuple(snapshot.valuation_at.date() + timedelta(days=offset) for offset in (1, 2))
        assert dates[-1] < datetime.now(UTC).date()
        calendar = SourceCalendar(
            id="alert-matrix-two-declared-sessions",
            version="1",
            timezone="UTC",
            period=SourcePeriod(start=snapshot.valuation_at.date(), end=datetime.now(UTC).date()),
            sessions=tuple(
                MarketSession(
                    session_date=day,
                    close_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=16),
                )
                for day in dates
            ),
        )
        sources = PostgresSourceService(sessions=matrix.sessions, cursor_signing_key=matrix.key)
        await sources.register_source_calendar(
            matrix.principal, calendar, idempotency_key=uuid4().hex, correlation_id="alert-matrix"
        )
        with matrix.sessions() as session:
            calendar_id = session.scalar(
                select(SourceCalendarModel.id).where(SourceCalendarModel.key == calendar.id)
            )
            assert calendar_id is not None
        for metric in (d.AlertMetric.SOURCE_AGE_SECONDS, d.AlertMetric.SOURCE_MISSING_SESSIONS):
            chosen = replace(
                predicate(metric),
                source_family=d.AlertSourceFamily.VALUATION,
                source_id=snapshot.id,
                calendar_version_id=calendar_id
                if metric is d.AlertMetric.SOURCE_MISSING_SESSIONS
                else None,
            )
            value, result = matrix.capture(await matrix.activate(chosen))
            elapsed = value.source_cutoff_at - snapshot.valuation_at
            assert scalar(result) == (
                2
                if metric is d.AlertMetric.SOURCE_MISSING_SESSIONS
                else elapsed.days * 86400 + elapsed.seconds
            )
            if metric is d.AlertMetric.SOURCE_MISSING_SESSIONS:
                assert any(
                    pin.subject_id == calendar_id and pin.role is d.AlertInputRole.CALENDAR
                    for pin in value.canonical_bindings
                )

    asyncio.run(run())


def test_actual_historical_price_and_fx_coverage_preserve_counts_and_licensed_source_hashes(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    from trading212_application import historical as h
    from trading212_domain import historical as hd
    from trading212_domain import historical_results as hr
    from trading212_domain.historical_serialization import historical_result_from_json
    from trading212_persistence.historical_models import HistoricalRunModel
    from trading212_persistence.historical_service import PostgresHistoricalService
    from trading212_persistence.planning_models import AnalyticsRunModel
    from trading212_persistence.source_models import FxSnapshotModel, PriceSnapshotModel

    from tests.integration.report_history_cases import history_report_case
    from tests.integration.test_historical_seed import window

    async def run() -> None:
        sessions, ids = seeded_history
        case = history_report_case(sessions, ids)
        matrix = Matrix(sessions, case.principal, case.account_id)
        historical = await PostgresHistoricalService(
            sessions, cursor_signing_key=matrix.key
        ).get_performance_summary(
            matrix.principal,
            str(matrix.account_id),
            query=h.PerformanceSummaryQuery(
                window=window("annual"),
                options=hr.PerformanceOptions(frequency=hd.HistoricalFrequency.MONTHLY),
            ),
        )
        with sessions() as session:
            run = session.get_one(HistoricalRunModel, UUID(historical.context.run_id))
            saved = session.get_one(AnalyticsRunModel, run.analytics_run_id)
            canonical = historical_result_from_json(saved.canonical_result)
            price = session.scalar(
                select(PriceSnapshotModel)
                .where(PriceSnapshotModel.owner_id == UUID(matrix.principal.owner_id))
                .order_by(PriceSnapshotModel.id)
            )
            fx = session.scalar(
                select(FxSnapshotModel)
                .where(FxSnapshotModel.owner_id == UUID(matrix.principal.owner_id))
                .order_by(FxSnapshotModel.id)
            )
            assert price is not None and fx is not None
        for family, identifier, expected, available in (
            (
                d.AlertSourceFamily.HISTORY,
                run.id,
                sum(item.expected_count for item in canonical.context.coverage.measures),
                sum(item.available_count for item in canonical.context.coverage.measures),
            ),
            (d.AlertSourceFamily.PRICE, price.id, price.expected_count, price.available_count),
            (d.AlertSourceFamily.FX, fx.id, fx.expected_count, fx.available_count),
        ):
            for metric in (d.AlertMetric.MISSING_COUNT, d.AlertMetric.MISSING_FRACTION):
                value, result = matrix.capture(
                    await matrix.activate(
                        replace(predicate(metric), domain=family, source_id=identifier)
                    )
                )
                want = (
                    expected - available
                    if metric is d.AlertMetric.MISSING_COUNT
                    else (Decimal(expected - available) / Decimal(expected)).quantize(
                        Decimal("1e-18")
                    )
                )
                assert scalar(result) == want
                fact = next(fact for fact in value.contexts[0].coverage if fact.key == family.value)
                assert (fact.expected_count, fact.available_count) == (expected, available)
                assert value.licenses and any(
                    ref.license_version_id is not None for ref in value.source_references
                )
                if family is d.AlertSourceFamily.HISTORY:
                    assert any(
                        pin.subject_id == run.id and pin.content_digest == saved.content_digest
                        for pin in value.canonical_bindings
                    )
                    assert {ReportSourceKind.PRICE_SNAPSHOT, ReportSourceKind.FX_SNAPSHOT} <= {
                        ref.kind for ref in value.source_references
                    }
                else:
                    header = price if family is d.AlertSourceFamily.PRICE else fx
                    reference = next(
                        ref for ref in value.source_references if ref.subject_id == header.id
                    )
                    assert (
                        reference.content_digest,
                        reference.provider_id,
                        reference.license_version_id,
                    ) == (header.content_digest, header.provider_id, header.license_version_id)

    asyncio.run(run())


def test_actual_provider_refresh_activity_corrections_and_report_terminal_producers(
    report_case: ReportCase,
) -> None:
    from trading212_application import activity_revisions as revision
    from trading212_application import ingestion as ingestion
    from trading212_application import source_providers as ports
    from trading212_application.provider_observations import ObservedETFConstituentProvider
    from trading212_application.source_ingestion import SourceProviderRegistration
    from trading212_application.sources import ProviderConfigurationState
    from trading212_persistence.activity_revision_store import PostgresActivityRevisionStore
    from trading212_persistence.models import SourceRecordModel
    from trading212_persistence.provider_observation_store import PostgresProviderOutcomeObserver
    from trading212_persistence.source_service import PostgresSourceService
    from trading212_worker.postgres_store import PostgresIngestionStore

    from tests.integration.test_report_postgres import finish, generate

    class Broker:
        failed = False
        correction = False

        async def read_page(
            self,
            *,
            owner_id: str,
            account_id: str,
            capability: ingestion.IngestionCapability,
            checkpoint: ingestion.Checkpoint | None,
            correlation_id: str,
        ) -> ingestion.SourcePage:
            if self.failed:
                raise ingestion.IngestionFailure(
                    ingestion.FailureCategory.TRANSIENT,
                    "Synthetic provider failed",
                    retryable=False,
                )
            now = datetime.now(UTC)
            rows = []
            if capability is ingestion.IngestionCapability.DIVIDENDS:
                rows.append(
                    ingestion.SourceRecord(
                        "alert-payment",
                        now,
                        now,
                        {
                            "reference": "alert-payment",
                            "paidOn": now.date(),
                            "amount": Decimal("4" if self.correction else "3"),
                            "currency": "EUR",
                        },
                        "alert-matrix-v1",
                    )
                )
            elif capability is ingestion.IngestionCapability.TRANSACTIONS and not self.correction:
                rows.extend(
                    (
                        ingestion.SourceRecord(
                            "alert-withdrawal",
                            now,
                            now,
                            {
                                "reference": "alert-withdrawal",
                                "dateTime": now,
                                "amount": Decimal("-7"),
                                "currency": "EUR",
                                "type": "WITHDRAW",
                            },
                            "alert-matrix-v1",
                        ),
                        ingestion.SourceRecord(
                            "alert-unknown",
                            now,
                            now,
                            {
                                "reference": "alert-unknown",
                                "dateTime": now,
                                "amount": Decimal("5"),
                                "currency": "EUR",
                                "type": "SYNTHETIC_UNCLASSIFIED",
                            },
                            "alert-matrix-v1",
                        ),
                    )
                )
            return ingestion.SourcePage(tuple(rows), None, True)

    class ReferenceProvider:
        code = ports.SourceProviderError.TRANSIENT_FAILURE

        async def get_constituents(
            self, request: ports.ConstituentRequest
        ) -> ports.ConstituentPage | ports.SourceFailure:
            return ports.SourceFailure(
                code=self.code,
                capability=ports.SourceCapability.CONSTITUENTS,
                provider_key="alert-matrix-provider",
            )

    async def run() -> None:
        matrix = Matrix(report_case.base.sessions, report_case.principal, report_case.account_id)
        provider_id = uuid4()
        await PostgresSourceService(
            sessions=matrix.sessions, cursor_signing_key=matrix.key
        ).configure_source_provider(
            matrix.principal,
            SourceProviderRegistration(
                id=str(provider_id),
                key="alert-matrix-provider",
                name="Synthetic alert invocation fixture",
                adapter_version="1",
                configuration_state=ProviderConfigurationState.CONFIGURED,
                synthetic=True,
                capabilities=(ports.SourceCapability.CONSTITUENTS,),
            ),
            idempotency_key=uuid4().hex,
            correlation_id="alert-matrix",
        )
        metrics = (
            d.AlertMetric.PROVIDER_FAILED,
            d.AlertMetric.PROVIDER_CONSECUTIVE_FAILURES,
            d.AlertMetric.REFRESH_FAILED,
            d.AlertMetric.POSITIVE_DIVIDEND,
            d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
            d.AlertMetric.ACTIVITY_COUNT,
            d.AlertMetric.UNCLASSIFIED_ACTIVITY,
            d.AlertMetric.REPORT_TERMINAL,
        )
        versions = {}
        for metric in metrics:
            chosen = predicate(metric)
            if chosen.provider_id is not None:
                chosen = replace(chosen, provider_id=provider_id)
            versions[metric] = await matrix.activate(chosen)
        before_invocation = datetime.now(UTC)
        provider = ReferenceProvider()
        observed = ObservedETFConstituentProvider(
            provider,
            PostgresProviderOutcomeObserver(
                sessions=matrix.sessions, principal=matrix.principal, provider_id=provider_id
            ),
        )
        for _ in range(2):
            now = datetime.now(UTC)
            response = await observed.get_constituents(
                ports.ConstituentRequest(
                    fund_series_id=report_case.base.seed["fund-a_instrument_id"],
                    effective_at=now,
                    source_cutoff_at=now,
                )
            )
            assert (
                isinstance(response, ports.SourceFailure)
                and response.code is ports.SourceProviderError.TRANSIENT_FAILURE
            )
        _, historical = matrix.capture(
            versions[d.AlertMetric.PROVIDER_FAILED], cutoff=before_invocation
        )
        assert (
            historical.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
            and historical.reason is d.AlertReason.NO_OBSERVATIONS
        )
        for metric, expected in (
            (d.AlertMetric.PROVIDER_FAILED, True),
            (d.AlertMetric.PROVIDER_CONSECUTIVE_FAILURES, 2),
        ):
            value, result = matrix.capture(versions[metric])
            assert scalar(result) == expected
            assert any(
                pin.family is d.AlertCanonicalFamily.PROVIDER and pin.parent_id == provider_id
                for pin in value.canonical_bindings
            )
        broker = Broker()
        coordinator = ingestion.IngestionCoordinator(
            provider=broker, store=PostgresIngestionStore(matrix.sessions, provider="synthetic")
        )

        async def ingest() -> ingestion.IngestionRun:
            return await coordinator.refresh(
                owner_id=matrix.principal.owner_id,
                account_id=str(matrix.account_id),
                mode=ingestion.RunMode.FULL,
                idempotency_key=uuid4().hex,
                capabilities=ingestion.HISTORY_REFRESH_ORDER,
                correlation_id="alert-matrix",
            )

        first_run = await ingest()
        assert first_run.status is ingestion.RunStatus.SUCCEEDED
        for metric in (
            d.AlertMetric.POSITIVE_DIVIDEND,
            d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
            d.AlertMetric.ACTIVITY_COUNT,
            d.AlertMetric.UNCLASSIFIED_ACTIVITY,
        ):
            value, result = matrix.capture(versions[metric])
            assert result.decision is True, result
            assert any(
                ref.kind is ReportSourceKind.BROKER_SOURCE_RECORD for ref in value.source_references
            )
            assert (
                value.contexts[0].coverage[0].complete is False
            )  # No invented complete live window.
            if metric is d.AlertMetric.ACTIVITY_COUNT:
                assert (
                    scalar(result) == 2
                )  # Dividend economic time is payment-day midnight, unlike newly-known event rules.
            else:
                assert result.event_decisions
                if metric is d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT:
                    assert result.event_decisions[0].observation.value == Decimal("7")
                    assert result.event_decisions[0].observation.currency == EUR
        broker.failed = True
        failed = await ingest()
        assert failed.status is ingestion.RunStatus.FAILED
        value, result = matrix.capture(versions[d.AlertMetric.REFRESH_FAILED])
        assert isinstance(value.payload, d.AlertEventBatchInput)
        assert result.decision is True and any(
            event.identity == UUID(failed.id) for event in value.payload.events
        )
        completed = await finish(report_case, await generate(report_case))
        value, result = matrix.capture(versions[d.AlertMetric.REPORT_TERMINAL])
        assert result.decision is True and any(
            pin.family is d.AlertCanonicalFamily.REPORT and pin.subject_id == completed.job_id
            for pin in value.canonical_bindings
        )
        before_correction = datetime.now(UTC)
        broker.failed, broker.correction = False, True
        corrected_run = await ingest()
        assert corrected_run.status is ingestion.RunStatus.SUCCEEDED
        _, ambiguous = matrix.capture(versions[d.AlertMetric.POSITIVE_DIVIDEND])
        assert (
            ambiguous.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
            and ambiguous.reason is d.AlertReason.AMBIGUOUS_SOURCE
        )
        with matrix.sessions() as session:
            previous = session.scalar(
                select(SourceRecordModel.id).where(
                    SourceRecordModel.ingestion_run_id == UUID(first_run.id),
                    SourceRecordModel.capability == "historical_dividends",
                )
            )
            revised = session.scalar(
                select(SourceRecordModel.id).where(
                    SourceRecordModel.ingestion_run_id == UUID(corrected_run.id),
                    SourceRecordModel.capability == "historical_dividends",
                )
            )
            assert previous is not None and revised is not None and previous != revised
        proof = await PostgresActivityRevisionStore(matrix.sessions).register_activity_revision(
            matrix.principal,
            matrix.account_id,
            revision.ActivityRevisionRegistration(
                id=uuid4(),
                new_source_record_id=revised,
                superseded_source_record_id=previous,
                authority=revision.ActivityRevisionAuthority.OWNER_ATTESTATION,
                evidence_key="actual-synthetic-correction-review",
            ),
            idempotency_key=uuid4().hex,
            correlation_id="alert-matrix",
        )
        value, result = matrix.capture(versions[d.AlertMetric.POSITIVE_DIVIDEND])
        assert result.decision is True and isinstance(value.payload, d.AlertEventBatchInput)
        current = next(event for event in value.payload.events if event.revision_id == revised)
        assert (
            current.correction_of == previous
            and current.net_amount is not None
            and current.net_amount.amount == Decimal("4")
        )
        assert current.first_eligible_at == proof.first_observed_at
        assert any(
            ref.kind is ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            and ref.subject_id == proof.registration.id
            and ref.content_digest == proof.content_digest
            for ref in value.source_references
        )
        earlier, _ = matrix.capture(
            versions[d.AlertMetric.POSITIVE_DIVIDEND], cutoff=before_correction
        )
        assert isinstance(earlier.payload, d.AlertEventBatchInput) and any(
            event.revision_id == previous for event in earlier.payload.events
        )
        assert all(
            ref.kind is not ReportSourceKind.ACTIVITY_REVISION_EVIDENCE
            for ref in earlier.source_references
        )
        provider.code = ports.SourceProviderError.NOT_CONFIGURED
        now = datetime.now(UTC)
        await observed.get_constituents(
            ports.ConstituentRequest(
                fund_series_id=report_case.base.seed["fund-a_instrument_id"],
                effective_at=now,
                source_cutoff_at=now,
            )
        )
        value, result = matrix.capture(versions[d.AlertMetric.PROVIDER_FAILED])
        assert (
            result.outcome is d.AlertEvaluationOutcome.UNAVAILABLE
            and result.reason is d.AlertReason.NOT_CONFIGURED
        )
        assert any(pin.parent_id == provider_id for pin in value.canonical_bindings)

    asyncio.run(run())
