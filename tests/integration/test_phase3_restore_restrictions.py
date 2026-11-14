"""Apply one recorded post-backup restriction before serving a quarantined restore.

This finite synthetic reconciliation exercises existing authority guards. It does
not define a production authority feed, automatic recovery policy or public tool.
"""

import asyncio
import hashlib
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_domain import reports as reports
from trading212_domain.serialization import canonical_json
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.acquisition_store import PostgresAcquisitionStore
from trading212_persistence.models import AuditEventModel
from trading212_persistence.report_models import (
    ArtifactDownloadGrantModel,
    ReportJobModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_research_retention import expire_research_report_payloads
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.xray_service import PostgresXrayService
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.acquired_research_report_case import AcquiredResearchReportCase
from tests.integration.acquired_research_report_case import (
    acquired_research_report_case as acquired_research_report_case,
)
from tests.integration.phase3_operational_fixture import (
    drop_restored,
    evidence,
    inventory,
    restore_empty,
)
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import complete, generate, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_acquired_research_reports_postgres import (
    _authority_revision,
    _no_private_reads,
)
from tests.integration.test_research_report_retention_postgres import _assert_closed
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration

_GRANT_METADATA = (
    "id",
    "owner_id",
    "provider_id",
    "scope_id",
    "version_number",
    "license_version_id",
    "effective_at",
    "expires_at",
    "store_allowed",
    "display_allowed",
    "report_allowed",
    "export_allowed",
    "daily_allowance",
    "evidence_key",
    "content_digest",
    "created_at",
)


def _grant_metadata(record: ProviderCapabilityGrantModel) -> tuple[object, ...]:
    return tuple(getattr(record, field) for field in _GRANT_METADATA)


def _audit_receipts(sessions: sessionmaker[Session]) -> dict[str, str]:
    """Compare immutable audit identities through hashes, without emitting values."""
    with sessions() as session:
        session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        rows = session.execute(
            text(
                "SELECT a.id::text,encode(sha256(convert_to(to_jsonb(a)::text,'UTF8')),'hex') "
                "FROM audit_events a ORDER BY a.id"
            )
        )
        return {row[0]: row[1] for row in rows}


def _backup_directory() -> Path:
    directory = Path(os.environ["T212PI_PHASE3_EVIDENCE_DIR"]).resolve() / "operations-backups"
    assert not directory.is_relative_to(Path.cwd().resolve())
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def _append_recorded_restriction(
    sessions: sessionmaker[Session],
    recorded: ProviderCapabilityGrantModel,
) -> None:
    """Normal immutable INSERT of exactly one captured synthetic current revision."""
    assert recorded.store_allowed and recorded.display_allowed and not recorded.report_allowed
    assert grant_digest(recorded) == recorded.content_digest
    with sessions() as session, session.begin():
        assert session.get(ProviderCapabilityGrantModel, recorded.id) is None
        previous = session.scalar(
            select(ProviderCapabilityGrantModel)
            .where(
                ProviderCapabilityGrantModel.owner_id == recorded.owner_id,
                ProviderCapabilityGrantModel.scope_id == recorded.scope_id,
            )
            .order_by(ProviderCapabilityGrantModel.version_number.desc())
            .limit(1)
        )
        assert previous is not None and previous.version_number + 1 == recorded.version_number
        assert previous.provider_id == recorded.provider_id
        session.add(
            ProviderCapabilityGrantModel(
                id=recorded.id,
                owner_id=recorded.owner_id,
                provider_id=recorded.provider_id,
                scope_id=recorded.scope_id,
                version_number=recorded.version_number,
                license_version_id=recorded.license_version_id,
                effective_at=recorded.effective_at,
                expires_at=recorded.expires_at,
                store_allowed=recorded.store_allowed,
                display_allowed=recorded.display_allowed,
                report_allowed=recorded.report_allowed,
                export_allowed=recorded.export_allowed,
                daily_allowance=recorded.daily_allowance,
                evidence_key=recorded.evidence_key,
                content_digest=recorded.content_digest,
                created_at=recorded.created_at,
            )
        )
    with sessions() as session:
        copied = session.get_one(ProviderCapabilityGrantModel, recorded.id)
        assert _grant_metadata(copied) == _grant_metadata(recorded)
        assert grant_digest(copied) == recorded.content_digest


@pytest.mark.parametrize("fault", ["diagnostic_timeout", "post_restore_metadata"])
def test_restore_lifecycle_records_original_failure_before_optional_diagnostics(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case, directory = xray_read_case, _backup_directory()
    root = directory.parent
    original_run, original_read = subprocess.run, Path.read_bytes
    source_before = inventory(case.sessions)
    targets: list[str] = []
    metadata_failed = False
    corrupt = directory / f"invalid-lifecycle-{uuid4().hex}.bin"
    corrupt.write_bytes(b"explicit synthetic invalid pg_dump header\n")
    before = set(root.glob("operations-restore-failure-quarantined-*.json"))

    def controlled_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if "pg_restore" in arguments:
            targets.append(
                next(
                    value.removeprefix("--dbname=")
                    for value in arguments
                    if value.startswith("--dbname=")
                )
            )
            if fault == "diagnostic_timeout":
                with corrupt.open("rb") as invalid:
                    return original_run(arguments, **{**kwargs, "stdin": invalid})
        if "--schema-only" in arguments and fault == "diagnostic_timeout":
            raise subprocess.TimeoutExpired(arguments, timeout=120)
        return original_run(arguments, **kwargs)

    def controlled_read(path: Path) -> bytes:
        nonlocal metadata_failed
        if fault == "post_restore_metadata" and path.suffix == ".dump" and not metadata_failed:
            metadata_failed = True
            raise OSError("Explicit post-restore metadata observation failure.")
        return original_read(path)

    def exists(name: str) -> bool:
        admin = case.engine.url.set(drivername="postgresql", database="postgres")
        with psycopg.connect(admin.render_as_string(hide_password=False)) as connection:
            return connection.execute(
                "SELECT count(*) FROM pg_database WHERE datname=%s", (name,)
            ).fetchone() == (1,)

    try:
        with monkeypatch.context() as context:
            context.setattr(subprocess, "run", controlled_run)
            context.setattr(Path, "read_bytes", controlled_read)
            expected = subprocess.CalledProcessError if fault == "diagnostic_timeout" else OSError
            with pytest.raises(expected):
                restore_empty(case.engine, directory=directory)
        assert len(targets) == 1
        observations = set(root.glob("operations-restore-failure-quarantined-*.json")) - before
        records = [json.loads(path.read_text()) for path in observations]
        assert len(records) == 1
        assert records[0]["target"] == targets[0]
        assert records[0]["failure_type"] == expected.__name__
        assert records[0]["target_removed"] is False
        assert records[0]["target_creation_confirmed"] is True
        assert records[0]["diagnostic_export_attempted"] is False
        assert exists(targets[0]) is (fault == "diagnostic_timeout")
    finally:
        # The exact target is observed in this test's own pg_restore argv. A
        # refused diagnostic export stays quarantined until this explicit test
        # cleanup records its actual empty state; never sweep other databases.
        for name in targets:
            if exists(name):
                url = case.engine.url.set(drivername="postgresql", database=name)
                with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
                    tables = tuple(
                        connection.execute(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname='public' ORDER BY tablename"
                        )
                    )
                evidence(
                    "lifecycle-fault-target",
                    {"target": name, "public_tables": tables, "fault": fault},
                )
                if fault == "diagnostic_timeout":
                    assert not tables
                else:
                    retained_engine = create_database_engine(
                        case.engine.url.set(database=name).render_as_string(hide_password=False)
                    )
                    try:
                        retained = inventory(create_session_factory(retained_engine))
                        evidence(
                            "lifecycle-fault-restored-inventory",
                            {
                                "target": name,
                                "restored_inventory": retained,
                                "source_inventory": source_before,
                            },
                        )
                        assert {k: v for k, v in retained.items() if k != "raw_schema_sha256"} == {
                            k: v for k, v in source_before.items() if k != "raw_schema_sha256"
                        }
                    finally:
                        retained_engine.dispose()
                drop_restored(case.engine, name)


async def test_quarantined_restore_applies_post_backup_fx_restriction_before_private_reads(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    source = acquired_research_report_case
    original_report = source.report
    principal, account = (
        original_report.research.xray.principal,
        original_report.research.account_id,
    )
    selected = selection(original_report, formats=(reports.ReportFormat.JSON,))
    finished = await complete(original_report, await generate(original_report, selected=selected))
    artifact = finished.artifacts[0]
    token = await original_report.reports.create_report_download_grant(
        principal, account, finished.job_id, artifact.artifact_id
    )
    served = await original_report.reports.download_report_artifact(
        principal, account, finished.job_id, artifact.artifact_id, grant_token=token.token
    )
    assert hashlib.sha256(served.content).hexdigest() == artifact.content_digest
    assert served.content
    with original_report.research.xray.sessions() as session:
        input_id = session.get_one(ReportJobModel, finished.job_id).input_id
        grant_expiry = session.scalar(
            select(ArtifactDownloadGrantModel.expires_at).where(
                ArtifactDownloadGrantModel.report_artifact_id == artifact.artifact_id
            )
        )
        assert grant_expiry is not None

    source_engine, source_sessions = (
        original_report.research.xray.engine,
        original_report.research.xray.sessions,
    )
    source_before = inventory(source_sessions)
    audits_before = _audit_receipts(source_sessions)
    assert len(source_before["tables"]) == 368
    started = perf_counter()
    observations: dict[str, Any] = {
        "phase": "backup_restore",
        "proof_completed": False,
        "source_before": source_before,
        "audit_prefix": audits_before,
        "denied_operations_completed": 0,
    }

    def checkpoint(phase: str, **values: Any) -> None:
        observations.update(phase=phase, **values)
        evidence("restriction-phase", observations)

    directory = await asyncio.to_thread(_backup_directory)
    try:
        target_name, observation = await asyncio.to_thread(
            restore_empty, source_engine, directory=directory
        )
    except Exception as error:
        try:
            checkpoint("backup_restore_failed", failure_type=type(error).__name__)
        except Exception as recording_error:
            error.add_note(
                "Restriction backup failure observation could not be retained "
                f"({type(recording_error).__name__})."
            )
        raise
    observations.update(target=target_name, **observation)
    restored_engine = None
    failure: Exception | None = None
    try:
        restored_engine = create_database_engine(
            source_engine.url.set(database=target_name).render_as_string(hide_password=False)
        )
        sessions = create_session_factory(restored_engine)
        # Quarantine permits administrative integrity inspection, not application
        # reads. No restored application service exists until the overlay commits.
        restored_before = inventory(sessions)
        checkpoint("restored_integrity_observed", restored_before=restored_before)
        assert {k: v for k, v in restored_before.items() if k != "raw_schema_sha256"} == {
            k: v for k, v in source_before.items() if k != "raw_schema_sha256"
        }
        assert _audit_receipts(sessions) == audits_before

        # restore_empty performs dump+restore together. This is a genuine later
        # source restriction after that backup, while the target is quarantined.
        after_restore = datetime.now(UTC)
        written = _authority_revision(source, "grant_report")
        with source_sessions() as session:
            current = session.scalar(
                select(ProviderCapabilityGrantModel)
                .where(
                    ProviderCapabilityGrantModel.owner_id == written.owner_id,
                    ProviderCapabilityGrantModel.scope_id == written.scope_id,
                    ProviderCapabilityGrantModel.effective_at
                    <= original_report.research.xray.now[0],
                )
                .order_by(
                    ProviderCapabilityGrantModel.effective_at.desc(),
                    ProviderCapabilityGrantModel.version_number.desc(),
                    ProviderCapabilityGrantModel.id.desc(),
                )
                .limit(1)
            )
            assert current is not None and current.id == written.id
            assert current.effective_at >= after_restore
            assert grant_digest(current) == current.content_digest
            session.expunge(current)
        source_restricted = inventory(source_sessions)
        checkpoint(
            "source_restriction_observed",
            source_restricted=source_restricted,
            authority_revision_id=str(current.id),
            authority_revision_digest=current.content_digest,
            authority_effective_at=current.effective_at.isoformat(),
            authority_expires_at=current.expires_at.isoformat(),
        )
        assert {
            name
            for name, value in source_restricted["tables"].items()
            if value != source_before["tables"][name]
        } == {"provider_capability_grants"}
        assert _audit_receipts(source_sessions) == audits_before
        _append_recorded_restriction(sessions, current)
        restored_restricted = inventory(sessions)
        checkpoint("target_restriction_observed", restored_restricted=restored_restricted)
        assert {k: v for k, v in restored_restricted.items() if k != "raw_schema_sha256"} == {
            k: v for k, v in source_restricted.items() if k != "raw_schema_sha256"
        }

        # Actual current/pinned authority is now reconstructed before any target
        # service can read a saved context, manifest, note, X-ray or artifact.
        now = [max(current.effective_at, datetime.now(UTC))]
        assert now[0] < min(grant_expiry, finished.expires_at)
        xray = replace(
            original_report.research.xray,
            engine=restored_engine,
            sessions=sessions,
            now=now,
            service=PostgresXrayService(
                sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: now[0]
            ),
        )
        research = replace(
            original_report.research,
            xray=xray,
            service=PostgresResearchService(
                sessions,
                cursor_signing_key=XRAY_CURSOR_KEY,
                clock=lambda: now[0],
                capability_authority=PostgresResearchCapabilityAuthority(),
            ),
        )
        report = replace(
            original_report,
            research=research,
            reports=PostgresReportService(
                sessions,
                cursor_signing_key=XRAY_CURSOR_KEY,
                clock=lambda: now[0],
                contract_version=3,
            ),
        )
        target = replace(
            source,
            report=report,
            acquisition=replace(
                source.acquisition,
                xray=xray,
                store=PostgresAcquisitionStore(
                    sessions=sessions, principal=principal, enabled=True
                ),
            ),
        )

        denied_operations: tuple[Callable[[], Awaitable[object]], ...] = (
            lambda: report.reports.get_report_manifest(principal, account, finished.job_id),
            lambda: report.reports.download_report_artifact(
                principal, account, finished.job_id, artifact.artifact_id, grant_token=token.token
            ),
            lambda: generate(report, selected=selected),
        )
        observations["phase"] = "private_boundary_denials"
        for ordinal, operation in enumerate(denied_operations, 1):
            with _no_private_reads(target), pytest.raises(app.ReportServiceError) as denied:
                await operation()
            assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
            checkpoint("private_boundary_denials", denied_operations_completed=ordinal)
        assert inventory(sessions) == restored_restricted

        with sessions() as session, session.begin():
            pin, value, _, _ = research.service.retained_xray(
                session, research.auth(session), research.run_id
            )
            assert pin == report.item.portfolio.pin and value.content_digest == pin.result_digest
        checkpoint("original_display_authorized", original_display_read_authorized=True)
        assert inventory(sessions) == restored_restricted
        observations["phase"] = "physical_cleanup"
        cleanup_budgets: list[dict[str, int]] = []
        observations["cleanup_budget_remaining"] = cleanup_budgets
        for _ in range(16):
            with sessions() as session, session.begin():
                budget = SourcePurgeBudget()
                expire_research_report_payloads(session, at=now[0], budget=budget)
                cleanup_budgets.append(
                    {
                        "rows_inspected": budget.rows_inspected,
                        "rows_removed": budget.rows_removed,
                        "bytes_inspected": budget.bytes_inspected,
                        "bytes_removed": budget.bytes_removed,
                    }
                )
                assert 0 <= budget.rows_inspected <= 4096 and 0 <= budget.rows_removed <= 4096
                assert (
                    0 <= budget.bytes_inspected <= 67_108_864
                    and 0 <= budget.bytes_removed <= 67_108_864
                )
                work = session.scalar(
                    select(ReportRetentionWorkModel).where(
                        ReportRetentionWorkModel.input_id == input_id
                    )
                )
                done = work is not None and work.completed_at is not None
                if work is not None:
                    assert work.legacy_source_kind == "physical"
            if done:
                break
        else:
            pytest.fail("Restored forbidden report copies did not physically drain.")
        _assert_closed(report, input_id)
        after_cleanup = inventory(sessions)
        checkpoint("physical_cleanup_observed", after_cleanup=after_cleanup)
        allowed_changes = {
            "report_input_snapshots",
            "report_input_chunks",
            "report_input_dependencies",
            "report_input_research_dependencies",
            "report_input_research_sources",
            "report_input_research_notes",
            "report_jobs",
            "report_dispatch_outbox",
            "report_artifacts",
            "report_manifests",
            "artifact_download_grants",
            "report_retention_work",
            "report_research_retention_sweep",
            "audit_events",
        }
        changed_tables = {
            name
            for name, value in after_cleanup["tables"].items()
            if value != restored_restricted["tables"][name]
        }
        assert changed_tables <= allowed_changes
        assert {
            "report_artifacts",
            "artifact_download_grants",
            "report_retention_work",
        } <= changed_tables
        audits_after = _audit_receipts(sessions)
        assert all(
            audits_after.get(identifier) == digest for identifier, digest in audits_before.items()
        )
        added = tuple(UUID(identifier) for identifier in audits_after.keys() - audits_before.keys())
        with sessions() as session:
            actions = tuple(
                session.scalars(select(AuditEventModel.action).where(AuditEventModel.id.in_(added)))
            )
            assert sorted(actions) == ["report.input.purged", "report.job.expired"]
        source_after = inventory(source_sessions)
        checkpoint("final_source_observed", source_after=source_after)
        assert source_after == source_restricted
        elapsed = perf_counter() - started
        assert elapsed <= 600
        evidence(
            "restored-current-restriction",
            {
                **observation,
                "table_count": len(source_before["tables"]),
                "authority_scope": (
                    "one finite recorded synthetic post-backup FX REPORT-only revision"
                ),
                "authority_revision_id": str(current.id),
                "authority_revision_digest": current.content_digest,
                "authority_metadata_sha256": hashlib.sha256(
                    canonical_json(_grant_metadata(current)).encode()
                ).hexdigest(),
                "authority_metadata_fields": list(_GRANT_METADATA),
                "authority_effective_at": current.effective_at.isoformat(),
                "authority_expires_at": current.expires_at.isoformat(),
                "target_service_constructed_after_restriction_commit": True,
                "pre_overlay_restored_inventory": restored_before,
                "post_reconciliation_inventory": restored_restricted,
                "post_cleanup_inventory": after_cleanup,
                "source_post_backup_restriction_inventory": source_restricted,
                "private_boundary_observation": "current explicit private-column SELECT sentinel",
                "manifest_download_new_capture_denied": True,
                "original_display_read_authorized": True,
                "forbidden_copies_physically_cleared": True,
                "original_financial_source_rows_preserved": True,
                "prior_audit_prefix_preserved": True,
                "new_audit_actions": list(sorted(actions)),
                "source_unchanged_after_recorded_revision": True,
                "changed_cleanup_tables": sorted(changed_tables),
                "reconcile_denial_and_cleanup_seconds": elapsed,
            },
        )
        observations.update(phase="complete", proof_completed=True)
    except Exception as error:
        failure = error
        observations["failure_type"] = type(error).__name__
        raise
    finally:
        final_error: Exception | None = None
        saved = False
        observations["observed_elapsed_seconds"] = perf_counter() - started
        try:
            if restored_engine is not None:
                observations["target_before_disposal"] = inventory(
                    create_session_factory(restored_engine)
                )
        except Exception as error:
            final_error = error
            observations["final_inventory_failure_type"] = type(error).__name__
        try:
            evidence("restriction-final-state", observations)
            saved = True
        except Exception as error:
            final_error = error
        finally:
            if restored_engine is not None:
                restored_engine.dispose()
            if saved and final_error is None:
                try:
                    drop_restored(source_engine, target_name)
                except Exception as error:
                    final_error = error
                    observations["target_disposal_failure_type"] = type(error).__name__
                    try:
                        evidence("restriction-disposal-failure", observations)
                    except Exception:
                        error.add_note("The target disposal failure receipt could not be retained.")
                    if failure is not None:
                        failure.add_note(
                            f"Restored target {target_name} disposal was not confirmed "
                            f"({type(error).__name__})."
                        )
            elif failure is not None:
                failure.add_note(
                    f"Restored target {target_name} remains quarantined because its final "
                    "observations could not be retained completely."
                )
        if final_error is not None and failure is None:
            raise final_error
