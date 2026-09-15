"""Report rights join the existing original-lifetime gate before any input bytes."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.projection import ProjectionErrorCode
from trading212_application.sources import SourceServiceError, SourceServiceErrorCode
from trading212_domain.sources import SourceUse
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.report_capture_projection_store import (
    ProjectionReportSources,
    ProjectionReportStore,
    authorize_projection_report_metadata,
)
from trading212_security.principals import AuthorizationError

from tests.unit.persistence.test_projection_input_sources import AT, license

pytestmark = pytest.mark.unit


def source() -> ProjectionReportSources:
    return ProjectionReportSources(
        sessionmaker(), cursor_signing_key=b"projection-report-unit-signing-key", clock=lambda: AT
    )


def test_report_right_follows_store_display_and_uses_original_lifetime() -> None:
    value = source()
    api = Mock()
    value._sources = api
    api._permit.return_value = license()
    api._current_license.return_value = SimpleNamespace(retention_days=7)
    deadline = value._license(
        Mock(), Mock(owner_id=UUID(int=4)), UUID(int=1), AT - timedelta(days=2)
    )
    assert deadline == AT + timedelta(days=5)
    assert [call.args[-1] for call in api._permit.call_args_list] == [
        SourceUse.STORE,
        SourceUse.DISPLAY,
        SourceUse.REPORT,
    ]


def test_shortened_current_license_cannot_be_refreshed_by_report_creation() -> None:
    value = source()
    api = Mock()
    value._sources = api
    api._permit.return_value = license()
    api._current_license.return_value = SimpleNamespace(retention_days=1)
    with pytest.raises(ProjectionStorageError) as error:
        value._license(Mock(), Mock(owner_id=UUID(int=4)), UUID(int=1), AT - timedelta(days=2))
    assert error.value.code is ProjectionErrorCode.RUN_EXPIRED


def test_report_denial_during_source_authorization_precedes_retained_input_decode() -> None:
    store = ProjectionReportStore(
        sessionmaker(), cursor_signing_key=b"projection-report-unit-signing-key", clock=lambda: AT
    )
    assert isinstance(store.sources, ProjectionReportSources)
    assert store._calibration_resolver == store.sources.resolve_calibration
    api = Mock()
    store.sources._sources = api

    def permit(session: Session, owner: UUID, identifier: UUID, use: SourceUse) -> object:
        if use is SourceUse.REPORT:
            raise SourceServiceError(
                SourceServiceErrorCode.ACCESS_DENIED, "Report permission is unavailable"
            )
        return license()

    api._permit.side_effect = permit
    api._current_license.return_value = SimpleNamespace(retention_days=30)
    auth = Mock(owner_id=UUID(int=4), account_id=UUID(int=5))
    root = SimpleNamespace(
        id=UUID(int=10),
        kind="projection",
        created_at=AT - timedelta(days=1),
        expires_at=AT + timedelta(days=10),
    )
    run = SimpleNamespace(id=root.id, sealed=True, source_count=1, snapshot_id=None)
    session = Mock(spec=Session)
    session.scalar.return_value = None
    session.scalars.return_value = [
        SimpleNamespace(kind="calibration", subject_id=UUID(int=100), content_digest="a" * 64)
    ]

    def authorize(*args: object, **kwargs: object) -> None:
        store.sources._license(session, auth, UUID(int=1), AT - timedelta(days=1))

    with (
        patch.object(store, "authority", return_value=auth),
        patch.object(store, "_owned", side_effect=[root, run]),
        patch("trading212_persistence.projection_input_store.projection_owner_lock"),
        patch.object(store.sources, "authorize_sources", side_effect=authorize),
        patch("trading212_persistence.projection_input_store.unpack_projection_input") as decode,
        pytest.raises(SourceServiceError),
    ):
        store.read_retained_input(session, auth, root.id)
    decode.assert_not_called()
    session.execute.assert_not_called()
    api._load_snapshot.assert_not_called()


def test_current_principal_denial_precedes_all_metadata_and_private_reads() -> None:
    auth = Mock()
    auth.check.side_effect = AuthorizationError("revoked current report grant")
    session = Mock(spec=Session)
    with pytest.raises(AuthorizationError):
        authorize_projection_report_metadata(session, auth, UUID(int=10), now=AT)
    session.scalar.assert_not_called()
    session.execute.assert_not_called()
