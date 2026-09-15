"""Metadata admission and report-specific source authorization before private capture."""

from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_application import sources as source_app
from trading212_domain.sources import SourceUse
from trading212_persistence import report_capture_scenario_store as store
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.scenario_source_store import ScenarioCopySources
from trading212_persistence.scenario_store_types import (
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import AuthorizationError

from tests.unit.analytics.xray_factories import uid
from tests.unit.domain.scenario_factories import sensitivity_capture
from tests.unit.persistence.test_report_capture_scenario import prepared

pytestmark = pytest.mark.unit


def fake_auth() -> ReportAuthorization:
    value = Mock(spec=ReportAuthorization)
    value.owner_id = uid(1)
    value.account_id = uid(2)
    return cast(ReportAuthorization, value)


def test_missing_current_authority_precedes_even_permanent_header_lookup() -> None:
    auth = fake_auth()
    cast(Mock, auth.check).side_effect = AuthorizationError("access denied")
    session = Mock(spec=Session)
    _, _, _, _, metadata = prepared()
    with pytest.raises(AuthorizationError):
        store.authorize_scenario_report_metadata(
            session, auth, metadata.run_id, now=metadata.completed_at
        )
    session.scalar.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.parametrize("state", ["foreign_family", "expired", "queued", "unsealed", "purged"])
def test_ineligible_saved_run_denies_from_only_permanent_headers(state: str) -> None:
    _, _, _, _, metadata = prepared()
    root = SimpleNamespace(kind="scenario", expires_at=metadata.expires_at)
    run = SimpleNamespace(sealed=True)
    job = SimpleNamespace(state="succeeded", completed_at=metadata.completed_at)
    result = SimpleNamespace(sealed=True)
    if state == "foreign_family":
        root.kind = "risk"
    if state == "expired":
        root.expires_at = metadata.completed_at
    if state == "queued":
        job.state = "queued"
    if state == "unsealed":
        result.sealed = False
    session = Mock(spec=Session)
    session.scalar.side_effect = [root, run, job, result, uid(95) if state == "purged" else None]
    with pytest.raises(app.ReportServiceError) as error:
        store.authorize_scenario_report_metadata(
            session, fake_auth(), metadata.run_id, now=metadata.completed_at
        )
    expected = (
        app.ReportServiceErrorCode.NOT_FOUND
        if state == "foreign_family"
        else app.ReportServiceErrorCode.ARTIFACT_EXPIRED
        if state in {"expired", "purged"}
        else app.ReportServiceErrorCode.REPORT_UNAVAILABLE
    )
    assert error.value.code is expected
    # Deferred retained financial bytes must never be loaded by this admission helper.
    for call in session.scalar.call_args_list:
        statement = str(call.args[0])
        assert "canonical_result" not in statement and "canonical_input" not in statement
    session.execute.assert_not_called()


def metadata_rows() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    builder, _, _, _, metadata = prepared()
    return (
        SimpleNamespace(
            id=metadata.run_id, created_at=metadata.created_at, expires_at=metadata.expires_at
        ),
        SimpleNamespace(
            portfolio_snapshot_id=builder.selection.snapshot_id,
            reporting_currency=builder.selection.reporting_currency.value,
            source_cutoff_at=builder.selection.source_cutoff_at,
            historical_input_id=None,
        ),
        SimpleNamespace(completed_at=metadata.completed_at),
        SimpleNamespace(id=metadata.result_id, content_digest=metadata.result_digest),
    )


def test_normalized_license_union_is_bounded_before_constructing_any_private_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, sink, _, _, metadata = prepared()
    monkeypatch.setattr(
        store, "authorize_scenario_report_metadata", Mock(return_value=metadata_rows())
    )
    private = Mock()
    monkeypatch.setattr(store, "ScenarioReportStore", private)
    session = Mock(spec=Session)
    session.scalars.return_value = tuple(uid(10_000 + i) for i in range(257))
    with pytest.raises(app.ReportServiceError) as error:
        store.capture_scenario(
            builder,
            session,
            fake_auth(),
            sessions=cast(sessionmaker[Session], Mock()),
            clock=lambda: metadata.completed_at,
            cursor_signing_key=b"synthetic-report-key-32-bytes----",
        )
    assert error.value.code is app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
    private.assert_not_called()
    assert not sink.chunks


def test_private_input_denial_uses_report_permission_and_does_not_read_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, sink, _, _, metadata = prepared()
    monkeypatch.setattr(
        store, "authorize_scenario_report_metadata", Mock(return_value=metadata_rows())
    )
    private = Mock(spec=store.ScenarioReportStore)
    private.read_retained_input.side_effect = ScenarioStorageError(
        ScenarioStorageErrorCode.ACCESS_DENIED
    )
    monkeypatch.setattr(store, "ScenarioReportStore", Mock(return_value=private))
    session = Mock(spec=Session)
    session.scalars.return_value = ()
    with pytest.raises(app.ReportServiceError) as error:
        store.capture_scenario(
            builder,
            session,
            fake_auth(),
            sessions=cast(sessionmaker[Session], Mock()),
            clock=lambda: metadata.completed_at,
            cursor_signing_key=b"synthetic-report-key-32-bytes----",
        )
    assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    assert private.read_retained_input.call_args.kwargs["required_copy_use"] is SourceUse.REPORT
    private.read_result.assert_not_called()
    assert not sink.chunks


@pytest.mark.parametrize("requested", [None, SourceUse.DISPLAY, SourceUse.STORE, SourceUse.REPORT])
def test_nested_source_authority_cannot_downgrade_report_copy_permission(
    requested: SourceUse | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = sensitivity_capture()
    license = source.licenses[0]
    at = license.license.effective_at + timedelta(seconds=1)
    reader = store.ScenarioReportStore(
        cast(sessionmaker[Session], Mock()),
        cursor_signing_key=b"synthetic-report-key-32-bytes----",
        clock=lambda: at,
    )
    authority = reader.copy_authority(retained_at=at, required_copy_use=requested)
    assert isinstance(authority, ScenarioCopySources)
    assert authority.required_copy_use is SourceUse.REPORT and authority.max_copy_licenses == 256
    calls: list[SourceUse] = []

    def permit(*args: object) -> object:
        use = cast(SourceUse, args[-1])
        calls.append(use)
        if use is SourceUse.REPORT:
            raise source_app.SourceServiceError(
                source_app.SourceServiceErrorCode.ACCESS_DENIED, "Report copy denied"
            )
        return license.license

    monkeypatch.setattr(PostgresSourceService, "_permit", permit)
    # Uses the real composed copy-authority path. A newly removed REPORT right
    # must deny even a nested caller that only explicitly requested DISPLAY.
    with pytest.raises(ScenarioStorageError) as error:
        authority._permit(
            Mock(spec=Session),
            source.versions[0].owner_id,
            license.license_version_id,
            SourceUse.DISPLAY,
        )
    assert error.value.code is ScenarioStorageErrorCode.ACCESS_DENIED
    assert calls == [SourceUse.DISPLAY, SourceUse.STORE, SourceUse.DISPLAY, SourceUse.REPORT]
