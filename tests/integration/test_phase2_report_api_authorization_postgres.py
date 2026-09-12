"""Every report/export HTTP operation enforces persisted owner, account and current grants."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from hashlib import sha256
from typing import assert_never
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from trading212_api_contracts import reports as wire
from trading212_domain.serialization import to_primitive
from trading212_persistence.report_models import ArtifactDownloadGrantModel
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import (
    ORIGIN,
    REPORT_STATE,
    Actor,
    HttpCase,
    OwnerGrid,
    ReportResources,
    denied,
    retained_state,
    send,
    without_grant,
)
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_authorization_cases import report_resources as report_resources
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


class ReportOperation(StrEnum):
    GENERATE = "generate_portfolio_report"
    STATUS = "get_report_status"
    LIST = "list_reports"
    MANIFEST = "get_report_manifest"
    GRANT = "create_report_download_grant"
    DOWNLOAD = "download_report_artifact"
    EXPORT = "create_portfolio_export"
    EXPORT_LIST = "list_portfolio_exports"
    EXPORT_STATUS = "get_export_status"
    EXPORT_GRANT = "create_export_download_grant"
    EXPORT_DOWNLOAD = "download_export_artifact"


CREATES = frozenset({ReportOperation.GENERATE, ReportOperation.EXPORT})
LISTS = frozenset({ReportOperation.LIST, ReportOperation.EXPORT_LIST})
GRANTS = frozenset({ReportOperation.GRANT, ReportOperation.EXPORT_GRANT})
DOWNLOADS = frozenset({ReportOperation.DOWNLOAD, ReportOperation.EXPORT_DOWNLOAD})


async def current_download_grant(
    grid: OwnerGrid,
    actor: Actor,
    resource: ReportResources,
    operation: ReportOperation,
) -> ReportResources:
    """Issue only the selected token through the authorized real service."""
    if operation is ReportOperation.DOWNLOAD:
        artifact_id = resource.report.artifacts[0].artifact_id
        grant = await grid.reports.create_report_download_grant(
            actor.principal,
            resource.pin.account_id,
            resource.report.job_id,
            artifact_id,
        )
        assert grant.artifact_id == artifact_id
        assert grant.expires_at > grid.operational_clock()
        return replace(resource, report_grant=grant.token)
    if operation is ReportOperation.EXPORT_DOWNLOAD:
        artifact_id = resource.export.artifacts[0].artifact_id
        grant = await grid.reports.create_export_download_grant(
            actor.principal,
            resource.pin.account_id,
            resource.export.export_id,
            artifact_id,
        )
        assert grant.artifact_id == artifact_id
        assert grant.expires_at > grid.operational_clock()
        return replace(resource, export_grant=grant.token)
    return resource


def request_for(
    grid: OwnerGrid,
    operation: ReportOperation,
    resource: ReportResources,
    *,
    account: UUID | None = None,
) -> HttpCase:
    account_id = account or resource.pin.account_id
    query = {"account_id": str(account_id)}
    key = {"X-Idempotency-Key": uuid4().hex}
    match operation:
        case ReportOperation.GENERATE:
            body = wire.GenerateReportRequest.model_validate(
                to_primitive(grid.report_selection(resource.pin))
            ).model_copy(update={"account_id": str(account_id)})
            return HttpCase(
                operation,
                "POST",
                "/api/v1/report-jobs",
                202,
                body=body.model_dump_json(),
                headers=key,
            )
        case ReportOperation.EXPORT:
            export = wire.CreateExportRequest.model_validate(
                to_primitive(grid.export_selection(resource.pin))
            ).model_copy(update={"account_id": str(account_id)})
            return HttpCase(
                operation,
                "POST",
                "/api/v1/exports",
                202,
                body=export.model_dump_json(),
                headers=key,
            )
        case ReportOperation.LIST | ReportOperation.EXPORT_LIST:
            path = "/api/v1/reports" if operation is ReportOperation.LIST else "/api/v1/exports"
            return HttpCase(operation, "GET", path, 200, {**query, "limit": "100"})
        case ReportOperation.STATUS:
            return HttpCase(
                operation, "GET", f"/api/v1/report-jobs/{resource.report.job_id}", 200, query
            )
        case ReportOperation.MANIFEST:
            return HttpCase(
                operation, "GET", f"/api/v1/reports/{resource.report.job_id}", 200, query
            )
        case ReportOperation.EXPORT_STATUS:
            return HttpCase(
                operation, "GET", f"/api/v1/exports/{resource.export.export_id}", 200, query
            )
        case ReportOperation.GRANT | ReportOperation.DOWNLOAD:
            base = (
                f"/api/v1/reports/{resource.report.job_id}"
                f"/artifacts/{resource.report.artifacts[0].artifact_id}"
            )
            if operation is ReportOperation.GRANT:
                return HttpCase(operation, "POST", base + "/grants", 201, query, "{}")
            return HttpCase(
                operation,
                "GET",
                base + "/content",
                200,
                query,
                headers={"X-Artifact-Grant": resource.report_grant},
            )
        case ReportOperation.EXPORT_GRANT | ReportOperation.EXPORT_DOWNLOAD:
            base = (
                f"/api/v1/exports/{resource.export.export_id}"
                f"/artifacts/{resource.export.artifacts[0].artifact_id}"
            )
            if operation is ReportOperation.EXPORT_GRANT:
                return HttpCase(operation, "POST", base + "/grants", 201, query, "{}")
            return HttpCase(
                operation,
                "GET",
                base + "/content",
                200,
                query,
                headers={"X-Artifact-Grant": resource.export_grant},
            )
        case _:
            assert_never(operation)


def assert_owned(
    response: httpx.Response,
    operation: ReportOperation,
    resource: ReportResources,
) -> None:
    account = str(resource.pin.account_id)
    if operation in {ReportOperation.GENERATE, ReportOperation.STATUS}:
        value = wire.ReportJobStatus.model_validate_json(response.content)
        assert value.account_id == account and value.context is not None
        if operation is ReportOperation.STATUS:
            assert value.job_id == str(resource.report.job_id) and value.state == "succeeded"
        else:
            assert value.state == "queued"
    elif operation in {ReportOperation.EXPORT, ReportOperation.EXPORT_STATUS}:
        exported = wire.ExportJobStatus.model_validate_json(response.content)
        assert exported.account_id == account and exported.context is not None
        if operation is ReportOperation.EXPORT_STATUS:
            assert (
                exported.export_id == str(resource.export.export_id)
                and exported.state == "succeeded"
            )
        else:
            assert exported.state == "queued"
    elif operation is ReportOperation.LIST:
        page = wire.ReportPage.model_validate_json(response.content)
        assert page.total == len(page.items) and page.next_cursor is None
        assert str(resource.report.job_id) in {item.job_id for item in page.items}
        assert all(item.account_id == account for item in page.items)
    elif operation is ReportOperation.EXPORT_LIST:
        exports = wire.ExportPage.model_validate_json(response.content)
        assert exports.total == len(exports.items) and exports.next_cursor is None
        assert str(resource.export.export_id) in {item.export_id for item in exports.items}
        assert all(item.account_id == account for item in exports.items)
    elif operation is ReportOperation.MANIFEST:
        manifest = wire.ReportManifest.model_validate_json(response.content)
        assert manifest.document.selection.account_id == account
        assert manifest.document.selection.snapshot_id == str(resource.pin.snapshot_id)
    elif operation in GRANTS:
        grant = wire.ArtifactGrant.model_validate_json(response.content)
        expected = resource.report if operation is ReportOperation.GRANT else resource.export
        assert grant.artifact_id == str(expected.artifacts[0].artifact_id)
    else:
        assert operation in DOWNLOADS
        expected = resource.report if operation is ReportOperation.DOWNLOAD else resource.export
        artifact = expected.artifacts[0]
        assert len(response.content) == artifact.byte_length
        assert sha256(response.content).hexdigest() == artifact.content_digest


@pytest.mark.parametrize("operation", tuple(ReportOperation), ids=lambda operation: operation.value)
async def test_report_export_operations_bind_real_owner_account_resource_and_current_grant(
    owner_grid: OwnerGrid,
    report_resources: dict[UUID, ReportResources],
    operation: ReportOperation,
) -> None:
    grid = owner_grid
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(grid.api), base_url=ORIGIN
    ) as client:
        for index, actor in enumerate(grid.actors):
            other = grid.actors[1 - index]
            own = report_resources[actor.accounts[0].account_id]
            second = report_resources[actor.accounts[1].account_id]
            foreign = report_resources[other.accounts[0].account_id]
            own = await current_download_grant(grid, actor, own, operation)
            second = await current_download_grant(grid, actor, second, operation)
            foreign = await current_download_grant(grid, other, foreign, operation)
            request = request_for(grid, operation, own)
            positive = await send(client, actor, request)
            assert positive.status_code == request.success
            assert_owned(positive, operation, own)
            if operation in CREATES:
                before = retained_state(grid, REPORT_STATE)
                replay = await send(client, actor, request)
                assert replay.status_code == 202 and replay.content == positive.content
                assert retained_state(grid, REPORT_STATE) == before
            if operation in DOWNLOADS:
                # Donors must be real, currently authorized downloads before misuse.
                for donor_actor, donor in ((actor, second), (other, foreign)):
                    control = await send(client, donor_actor, request_for(grid, operation, donor))
                    assert control.status_code == 200
                    assert_owned(control, operation, donor)
            # Successful own conditional responses remain unusable by another owner.
            protected = replace(
                request,
                headers={**request.headers, "If-None-Match": positive.headers.get("etag", "*")},
            )
            before = retained_state(grid, REPORT_STATE)
            denied(await send(client, other, protected), "ACCESS_DENIED", own.private_values)
            assert retained_state(grid, REPORT_STATE) == before
            if operation in DOWNLOADS:
                # The same token must still work, ruling out expiry-only denial.
                still_owned = await send(client, actor, request)
                assert still_owned.status_code == 200
                assert_owned(still_owned, operation, own)

            if operation in LISTS:
                second_request = request_for(grid, operation, second)
                isolated = await send(client, actor, second_request)
                assert isolated.status_code == 200
                assert_owned(isolated, operation, second)
                assert str(own.report.job_id) not in isolated.text
                assert str(own.export.export_id) not in isolated.text
                denied_request = replace(
                    request, query={**request.query, "account_id": str(foreign.pin.account_id)}
                )
                before = retained_state(grid, REPORT_STATE)
                denied(
                    await send(client, actor, denied_request),
                    "ACCESS_DENIED",
                    foreign.private_values,
                )
                assert retained_state(grid, REPORT_STATE) == before
            else:
                # Fresh keys ensure commands reach reference validation, not replay conflict.
                for referenced, account in (
                    (foreign, own.pin.account_id),
                    (own, second.pin.account_id),
                ):
                    mismatch = request_for(grid, operation, referenced, account=account)
                    before = retained_state(grid, REPORT_STATE)
                    denied(
                        await send(client, actor, mismatch), "NOT_FOUND", referenced.private_values
                    )
                    assert retained_state(grid, REPORT_STATE) == before

            revoke = Scope.REPORTS_WRITE if operation in CREATES else Scope.REPORTS_READ
            with without_grant(grid, actor, revoke):
                before = retained_state(grid, REPORT_STATE)
                denied(await send(client, actor, protected), "ACCESS_DENIED", own.private_values)
                assert retained_state(grid, REPORT_STATE) == before


@pytest.mark.parametrize(
    "operation", tuple(sorted(GRANTS | DOWNLOADS)), ids=lambda operation: operation.value
)
async def test_report_export_artifact_parent_and_grant_binding(
    owner_grid: OwnerGrid,
    report_resources: dict[UUID, ReportResources],
    operation: ReportOperation,
) -> None:
    grid = owner_grid
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(grid.api), base_url=ORIGIN
    ) as client:
        for actor in grid.actors:
            own, second = (report_resources[pin.account_id] for pin in actor.accounts)
            own = await current_download_grant(grid, actor, own, operation)
            second = await current_download_grant(grid, actor, second, operation)
            request = request_for(grid, operation, own)
            positive = await send(client, actor, request)
            assert positive.status_code == request.success
            assert_owned(positive, operation, own)
            is_report = operation in {ReportOperation.GRANT, ReportOperation.DOWNLOAD}
            own_artifact = own.report.artifacts[0] if is_report else own.export.artifacts[0]
            other_artifact = second.report.artifacts[0] if is_report else second.export.artifacts[0]
            mismatch = replace(
                request,
                path=request.path.replace(
                    str(own_artifact.artifact_id), str(other_artifact.artifact_id)
                ),
            )
            before = retained_state(grid, REPORT_STATE)
            denied(await send(client, actor, mismatch), "NOT_FOUND", second.private_values)
            assert retained_state(grid, REPORT_STATE) == before
            if operation in DOWNLOADS:
                donor_request = request_for(grid, operation, second)
                donor_control = await send(client, actor, donor_request)
                assert donor_control.status_code == 200
                assert_owned(donor_control, operation, second)
                token = second.report_grant if is_report else second.export_grant
                wrong_grant = replace(
                    request, headers={**request.headers, "X-Artifact-Grant": token}
                )
                before = retained_state(grid, REPORT_STATE)
                denied(
                    await send(client, actor, wrong_grant), "ACCESS_DENIED", second.private_values
                )
                assert retained_state(grid, REPORT_STATE) == before
                donor_still_valid = await send(client, actor, donor_request)
                assert donor_still_valid.status_code == 200
                assert_owned(donor_still_valid, operation, second)


@pytest.mark.parametrize(
    "operation", tuple(sorted(DOWNLOADS)), ids=lambda operation: operation.value
)
async def test_report_export_http_checks_physical_revocation_of_a_real_download_grant(
    owner_grid: OwnerGrid,
    report_resources: dict[UUID, ReportResources],
    operation: ReportOperation,
) -> None:
    grid = owner_grid
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(grid.api), base_url=ORIGIN
    ) as client:
        for actor in grid.actors:
            own = report_resources[actor.accounts[0].account_id]
            grant_operation = (
                ReportOperation.GRANT
                if operation is ReportOperation.DOWNLOAD
                else ReportOperation.EXPORT_GRANT
            )
            issued = await send(client, actor, request_for(grid, grant_operation, own))
            assert issued.status_code == 201
            grant = wire.ArtifactGrant.model_validate_json(issued.content)
            request = request_for(grid, operation, own)
            request = replace(request, headers={**request.headers, "X-Artifact-Grant": grant.token})
            positive = await send(client, actor, request)
            assert positive.status_code == 200
            assert_owned(positive, operation, own)
            with grid.sessions() as session, session.begin():
                row = session.scalar(
                    select(ArtifactDownloadGrantModel).where(
                        ArtifactDownloadGrantModel.owner_id == UUID(actor.principal.owner_id),
                        ArtifactDownloadGrantModel.token_digest
                        == sha256(grant.token.encode()).hexdigest(),
                    )
                )
                assert row is not None and row.revoked_at is None
                row.revoked_at = grid.operational_clock()
            before = retained_state(grid, REPORT_STATE)
            denied(
                await send(client, actor, request),
                "ACCESS_DENIED",
                (*own.private_values, grant.token),
            )
            assert retained_state(grid, REPORT_STATE) == before
