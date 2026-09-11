"""Actual company PDF and plan-audit artifact regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application import planning as planning_app
from trading212_application import reports as app
from trading212_application import targets as targets_app
from trading212_application import xray
from trading212_application.planning_jobs import PlanTaskMessage
from trading212_domain import CurrencyCode
from trading212_domain import planning as d
from trading212_domain import reports as r
from trading212_domain import targets as t
from trading212_domain.report_schema import table_schema
from trading212_domain.values import Money
from trading212_persistence.planning_models import (
    ContributionPlanRequestModel,
    ContributionPlanResultModel,
)
from trading212_persistence.planning_service import PostgresPlanningService
from trading212_persistence.target_service import PostgresTargetService
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, XRAY_AT, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_report_company_postgres import report_case, selected
from tests.integration.test_report_exports_postgres import _export
from tests.integration.test_report_postgres import ReportCase, finish
from tests.integration.test_report_type_matrix_postgres import (
    DownloadedReport,
    _checked_formats,
    _download,
)
from tests.integration.test_virtual_targets import publish
from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _company_evidence(
    report: DownloadedReport, full: xray.ExposuresView
) -> tuple[dict[str, r.ReportCell], ...]:
    """Compare report cells with the independent full X-ray producer, not planning output."""
    assert full.exposures.total == len(full.exposures.items)
    alpha = next(
        bucket for bucket in full.exposures.items if bucket.bucket_key == xray_id("entity/alpha")
    )
    metric = alpha.absolute_weight
    assert metric.value == Decimal("0.56")
    assert report.manifest.document.selection.xray_run_id == UUID(full.context.run_id)
    assert any(
        binding.family is r.ReportFamily.XRAY
        and binding.subject_id == UUID(full.context.run_id)
        and binding.content_digest == full.context.content_digest
        for binding in report.manifest.bindings
    )
    basis = report.rows(r.ReportTableKey.PLANNING_COMPANY_BASIS_V1)[0]
    for key, expected in (
        ("xray_run_id", full.context.run_id),
        ("xray_input_id", full.context.input_snapshot_id),
        ("xray_input_digest", full.context.input_digest),
        ("xray_content_digest", full.context.content_digest),
        ("snapshot_id", full.context.snapshot_id),
        ("account_id", full.context.account_id),
        ("reporting_currency", full.context.reporting_currency.value),
        ("valuation_at", full.context.valuation_at),
        ("source_cutoff_at", full.context.source_cutoff_at),
    ):
        assert basis[key].value == expected
    rows = report.rows(r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1)
    alpha_rows = tuple(row for row in rows if row["entity_id"].value == alpha.bucket_key)
    assert len(alpha_rows) == 4
    bounds = {bound.key: bound for bound in report.manifest.bounds}
    contexts = {context.key: context for context in report.manifest.contexts}
    references = {reference.key: reference for reference in report.manifest.source_references}
    for row in alpha_rows:
        cell = row["actual_weight"]
        assert cell.value == metric.value and cell.currency is None
        assert cell.decimal_role is r.DecimalRole.RATIO
        assert cell.state.value == metric.availability.value
        assert cell.context_key is not None
        context = contexts[cell.context_key]
        quality = cell.quality if cell.quality is not None else context.quality
        assert quality == metric.quality and cell.confidence == metric.confidence
        assert cell.bound_key is not None
        bound = bounds[cell.bound_key]
        assert bound.kind.value == metric.bound.value
        assert bound.positive_below_quantum is metric.positive_below_quantum
        assert cell.context_key is not None
        context = contexts[cell.context_key]
        assert context.family is r.ReportFamily.XRAY
        assert context.valuation_at == full.context.valuation_at
        assert context.source_cutoff_at == full.context.source_cutoff_at
        provenance = cell.provenance_set_key or context.provenance_set_key
        source_keys = {
            member.source_key
            for member in report.manifest.source_memberships
            if member.provenance_set_key == provenance
        }
        # X-ray reference IDs identify proof entries; subject IDs identify their
        # underlying records and are deliberately not interchangeable.
        assert source_keys == {
            f"xray.source.{identifier}" for identifier in metric.source_reference_ids
        }
        assert source_keys <= references.keys()
        assert row["projection_digest"].value == basis["projection_digest"].value
    assert all(
        row["semantics"].value == "full_portfolio_company_non_additive"
        and row["drift_reason"].value == "effective_exposure_target_unavailable"
        for row in rows
    )
    note = next(
        note for note in report.manifest.notes if note.code == "full_portfolio_company_non_additive"
    )
    assert "non-additive" in note.text
    assert "snapshot actuals, never post-contribution weights" in note.text
    assert all(
        row["effective_weight"].value is None for row in report.rows(r.ReportTableKey.DRIFT_ROWS)
    )
    return alpha_rows


def test_pinned_company_pdf_download_has_exact_manifest_values_and_metric_evidence(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        # Observation advances; the actual historical financial cutoff stays fixed.
        xray_read_case.now[0] += timedelta(seconds=1)
        case = report_case(xray_read_case)
        selection = replace(await selected(case), formats=tuple(r.ReportFormat))
        full = await company(case.base)
        assert selection.xray_run_id == UUID(full.context.run_id)
        assert full.context.source_cutoff_at == XRAY_AT
        assert XRAY_AT < full.context.calculated_at <= selection.source_cutoff_at
        pending = await case.service.generate_report(
            case.principal,
            app.GenerateReportCommand(selection=selection, idempotency_key=uuid4().hex),
        )
        completed = await finish(case, pending)
        # These accepted helpers use actual grants/downloads, verify artifact sizes
        # and SHA-256, decode JSON/table digests, and compare the PDF attachment's
        # exact canonical manifest bytes. All formats avoid a parallel fake reader.
        report = _checked_formats(
            await _download(case.service, case.principal, case.account_id, completed)
        )
        assert report.manifest.document.selection == selection
        alpha_rows = _company_evidence(report, full)
        text = " ".join(report.pdf_text.split())
        assert "Planning company actuals v1" in text
        assert "Planning company basis v1" in text
        note = next(
            note
            for note in report.manifest.notes
            if note.code == "full_portfolio_company_non_additive"
        )
        assert " ".join(note.text.split()) in text
        for row in alpha_rows:
            # Localize to each actual row; a matching number elsewhere in the PDF
            # cannot satisfy the canonical company-cell presentation assertion.
            marker = f"Record: company.actual.{row['row_key'].value} "
            assert marker in text
            record = text.split(marker, 1)[1].split("Record: ", 1)[0]
            cell = row["actual_weight"]
            assert "Actual weight: 0.56" in record
            assert f"[bound: {cell.bound_key}]" in record
            assert cell.context_key is not None
            context = next(
                item for item in report.manifest.contexts if item.key == cell.context_key
            )
            quality = cell.quality if cell.quality is not None else context.quality
            assert f"Quality: {quality.value}" in record
            assert "Semantics: full_portfolio_company_non_additive" in record
        assert full.context.run_id in text
        assert full.context.content_digest in text
        # Selectable text/attachment assertions are not a visual-layout acceptance.

    asyncio.run(run())


def _plan_bytes(case: ReportCase, request_id: UUID) -> tuple[bytes, str, str, bytes, str]:
    with case.base.sessions() as session:
        request = session.get(ContributionPlanRequestModel, request_id)
        revision = session.scalar(
            select(ContributionPlanResultModel).where(
                ContributionPlanResultModel.request_id == request_id
            )
        )
        assert request is not None and revision is not None
        return (
            request.canonical_input,
            request.input_digest,
            request.normalized_digest,
            revision.canonical_result,
            revision.content_digest,
        )


def _unchanged_financial_tables(baseline: DownloadedReport, pinned: DownloadedReport) -> None:
    descriptors = {item.table: item for item in pinned.manifest.document.tables}
    for descriptor in baseline.manifest.document.tables:
        table = descriptor.table
        if not table.value.startswith(("plan_", "target_", "drift_")):
            continue
        assert table in pinned.tables
        if table is r.ReportTableKey.PLAN_RELATIONS:
            # Only the explicit company membership relations are additive here.
            retained = tuple(
                row for row in pinned.tables[table] if not row.key.startswith("company.actual.")
            )
            assert retained == baseline.tables[table]
        else:
            assert pinned.tables[table] == baseline.tables[table]
            assert descriptors[table].content_digest == descriptor.content_digest
    assert baseline.tables[r.ReportTableKey.PLAN_LINES]
    assert baseline.tables[r.ReportTableKey.PLAN_INPUT_HEADER]
    assert baseline.tables[r.ReportTableKey.PLAN_VALUATION_POSITIONS]
    assert r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1 not in baseline.tables


def test_finalized_plan_audit_exports_keep_legacy_bytes_and_preplan_company_actuals(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        xray_read_case.now[0] += timedelta(seconds=1)
        case = report_case(xray_read_case)
        full = await company(case.base)
        targets = PostgresTargetService(
            sessions=case.base.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.base.now[0],
        )
        portfolio = await targets.create_virtual_portfolio(
            case.principal,
            targets_app.CreateVirtualPortfolioCommand(
                "Company plan audit", CurrencyCode("EUR"), XRAY_ACCOUNT_ID
            ),
            idempotency_key=uuid4().hex,
            correlation_id="company-plan-audit",
        )
        # Real ingested primary listing; no catalogue/source mutation. Matching
        # one listing leaves the other three Alpha roots as actual unclassified rows.
        content = t.TargetContent(
            (
                t.TargetNode(
                    "alpha",
                    None,
                    t.TargetNodeKind.HOLDING,
                    "Alpha primary",
                    0,
                    Decimal("1"),
                    holding=t.TargetHoldingMapping(
                        t.TargetMappingState.RESOLVED,
                        instrument_id=UUID(xray_id("instrument/alpha-a")),
                        listing_id=UUID(xray_id("listing/alpha-primary")),
                    ),
                ),
            )
        )
        version = await targets.create_target_version(
            case.principal,
            portfolio.id,
            targets_app.CreateTargetVersionCommand(XRAY_AT, content=content),
            if_match=portfolio.etag,
            idempotency_key=uuid4().hex,
            correlation_id="company-plan-audit",
        )
        version = await publish(targets, case.principal, version)
        planner = PostgresPlanningService(
            sessions=case.base.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.base.now[0],
        )
        command = planning_app.CreateContributionPlanCommand(
            account_id=XRAY_ACCOUNT_ID,
            virtual_portfolio_id=portfolio.id,
            target_version_id=version.id,
            snapshot_id=case.base.seed["snapshot_id"],
            options=d.PlanningOptions(
                Money(Decimal("20"), CurrencyCode("EUR")),
                d.PlanningMode.GLOBAL,
                d.CoveragePolicy.ALLOW_DEGRADED,
            ),
        )
        job = await planner.create_contribution_plan(
            case.principal,
            command,
            idempotency_key=uuid4().hex,
            correlation_id="company-plan-audit",
        )
        claim = await planner.claim_plan_job(
            PlanTaskMessage(
                job.job_id,
                job.request_id,
                case.principal.owner_id,
                job.account_id,
                job.input_digest,
            ),
            consumer_id="company-plan-audit",
        )
        assert claim is not None
        actual_input = await planner.load_plan_job_input(claim)
        canonical = calculate_contribution_plan(actual_input)
        assert canonical.summary.outcome in {
            d.PlanOutcome.OPTIMAL,
            d.PlanOutcome.FEASIBLE_NONOPTIMAL,
        }
        assert len(canonical.lines) == 1
        line = canonical.lines[0]
        assert line.recommended_amount.amount > 0
        assert line.current_weight != line.post_weight
        assert canonical.summary.before_drift.value == Money(Decimal("1000"), CurrencyCode("EUR"))
        assert canonical.summary.post_total == Money(Decimal("1020"), CurrencyCode("EUR"))
        post_total = canonical.summary.post_total
        assert post_total is not None
        assert await planner.complete_plan_job(claim, canonical)
        request_id = UUID(job.request_id)
        with case.base.sessions() as session:
            revision = session.scalar(
                select(ContributionPlanResultModel).where(
                    ContributionPlanResultModel.request_id == request_id
                )
            )
            assert revision is not None
            revision_id = revision.id
        original = _plan_bytes(case, request_id)
        assert original[1] == job.input_digest
        selection = r.ExportSelection(
            account_id=case.account_id,
            snapshot_id=UUID(command.snapshot_id),
            start_date=XRAY_AT.date(),
            end_date=XRAY_AT.date(),
            source_cutoff_at=case.base.now[0],
            reporting_currency=CurrencyCode("EUR"),
            dataset=r.ExportDataset.PLANS,
            field_set=r.ExportFieldSet.AUDIT,
            format=r.ExportFormat.JSON,
            target_version_id=UUID(version.id),
            plan_revision_id=revision_id,
        )
        baseline = await _export(
            case.base.sessions, case.service, case.jobs, case.principal, selection
        )
        assert baseline.manifest.document.selection.xray_run_id is None
        assert _plan_bytes(case, request_id) == original
        for format in r.ExportFormat:
            pinned = await _export(
                case.base.sessions,
                case.service,
                case.jobs,
                case.principal,
                replace(selection, format=format, xray_run_id=UUID(full.context.run_id)),
            )
            assert pinned.manifest.document.selection.plan_revision_id == revision_id
            assert (
                pinned.manifest.document.document_digest
                != baseline.manifest.document.document_digest
            )
            _unchanged_financial_tables(baseline, pinned)
            _company_evidence(pinned, full)
            summary = pinned.rows(r.ReportTableKey.PLAN_SUMMARY)[0]
            assert summary["execution_allowed"].value is False
            assert summary["contribution"].value == canonical.summary.contribution.amount
            assert summary["post_total"].value == post_total.amount
            actual_lines = pinned.rows(r.ReportTableKey.PLAN_LINES)
            assert len(actual_lines) == 1
            for key in ("current_weight", "post_weight"):
                assert actual_lines[0][key].value == getattr(line, key)
            for key in ("current_value", "recommended_amount", "post_value"):
                assert actual_lines[0][key].value == getattr(line, key).amount
                assert actual_lines[0][key].currency == CurrencyCode("EUR")
            assert any(
                binding.role is r.ReportInputRole.PLAN_REVISION
                and binding.subject_id == revision_id
                and binding.content_digest == original[4]
                for binding in pinned.manifest.bindings
            )
            assert all(
                "post" not in column.key
                for table in (
                    r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1,
                    r.ReportTableKey.PLANNING_COMPANY_BASIS_V1,
                )
                for column in table_schema(table).columns
            )
            assert _plan_bytes(case, request_id) == original

    asyncio.run(run())
