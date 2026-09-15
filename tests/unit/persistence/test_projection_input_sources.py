"""Independent source admission and exact dated normalized capture regressions."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_domain.sources import LicensePermission, SourceLicense, SourceUse
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_input_store import (
    projection_input_rows,
    projection_run_header,
)
from trading212_persistence.projection_models import (
    ProjectionCalendarBoundaryModel,
    ProjectionInputModel,
    ProjectionRunPauseModel,
    ProjectionRunScheduleEntryModel,
)
from trading212_persistence.projection_source_store import ProjectionSourceStore

from tests.unit.persistence.projection_codec_factories import capture

AT = datetime(2026, 9, 15, tzinfo=UTC)


def store() -> ProjectionSourceStore:
    return ProjectionSourceStore(
        cast(sessionmaker[Session], Mock()),
        cursor_signing_key=b"projection-source-unit-key-32bytes",
        clock=lambda: AT,
    )


def test_complete_calendar_and_dated_schedule_are_retained_without_relabeling() -> None:
    plan = capture()
    rows = projection_input_rows(plan)
    assert rows[ProjectionCalendarBoundaryModel] == (
        {"month": 0, "on": date(2025, 1, 31), "point_index": 0},
        {"month": 1, "on": date(2025, 2, 28), "point_index": 1},
        {"month": 2, "on": date(2025, 3, 31), "point_index": 2},
        {"month": 3, "on": date(2025, 4, 30), "point_index": 3},
    )
    assert rows[ProjectionRunPauseModel] == ({"on": date(2025, 2, 28), "month": 2},)
    assert rows[ProjectionRunScheduleEntryModel] == (
        {
            "entry_key": "lump",
            "on": date(2025, 1, 31),
            "month": 1,
            "kind": "lump_sum",
            "value": Decimal(7),
        },
        {
            "entry_key": "withdrawal",
            "on": date(2025, 3, 31),
            "month": 3,
            "kind": "withdrawal",
            "value": Decimal(3),
        },
    )
    assert rows[ProjectionInputModel][0]["contribution_delta"] == Decimal(2)
    assert rows[ProjectionInputModel][0]["initial_value"] == Decimal("1500.123456789012345678")
    header = projection_run_header(plan, 2)
    assert header["capture_digest"] != header["numerical_input_digest"]
    assert header["snapshot_valuation_at"] == datetime(2025, 1, 31, 23, 17, 21, 123456, tzinfo=UTC)
    assert header["variant_count"] == 3 and header["retained_point_count"] == 4


def test_current_authorization_precedes_source_identity_discovery() -> None:
    source = store()
    session = Mock()
    auth = Mock()
    denied = ProjectionStorageError(app.ProjectionErrorCode.ACCESS_DENIED)
    auth.check.side_effect = denied
    with pytest.raises(ProjectionStorageError) as failure:
        source.resolve_calibration(session, auth, (), use=SourceUse.DISPLAY, now=AT)
    assert failure.value is denied
    session.execute.assert_not_called()
    session.scalar.assert_not_called()


@pytest.mark.parametrize("candidates", [(None, None, None), (UUID(int=1), UUID(int=1), None)])
def test_unknown_or_ambiguous_uuid_never_loads_financial_source(
    candidates: tuple[UUID | None, ...],
) -> None:
    source = store()
    session = Mock()
    session.scalar.side_effect = candidates
    auth = Mock(owner_id=UUID(int=4), account_id=UUID(int=5))
    source._sources = Mock()
    pin = capture().assumption_version.content.calibration_pins[0]
    with pytest.raises(ProjectionStorageError) as failure:
        source.resolve_calibration(session, auth, (pin,), use=SourceUse.STORE, now=AT)
    assert failure.value.code is app.ProjectionErrorCode.SOURCE_UNAVAILABLE
    source._sources._load_snapshot.assert_not_called()
    assert session.scalar.call_count == 3


def license() -> SourceLicense:
    return SourceLicense(
        id=str(UUID(int=1)),
        provider_id=str(UUID(int=2)),
        version="synthetic",
        effective_at=AT - timedelta(days=10),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.DENIED,
        export=LicensePermission.DENIED,
        retention_days=30,
        attribution="Synthetic",
        evidence_key="fixture",
    )


def test_current_shorter_license_uses_original_creation_not_new_copy_clock() -> None:
    source = store()
    api = Mock()
    source._sources = api
    api._permit.return_value = license()
    api._current_license.return_value = SimpleNamespace(retention_days=1)
    session = Mock()
    auth = Mock(owner_id=UUID(int=4))
    with pytest.raises(ProjectionStorageError) as failure:
        source._license(session, auth, UUID(int=1), AT - timedelta(days=2))
    assert failure.value.code is app.ProjectionErrorCode.RUN_EXPIRED
    assert [call.args[-1] for call in api._permit.call_args_list] == [
        SourceUse.STORE,
        SourceUse.DISPLAY,
    ]


def test_original_source_deadline_clamps_before_the_license_copy_bound() -> None:
    source = store()
    api = Mock()
    source._sources = api
    api._permit.return_value = license()
    api._current_license.return_value = SimpleNamespace(retention_days=7)
    assert source._license(
        Mock(), Mock(owner_id=UUID(int=4)), UUID(int=1), AT - timedelta(days=2)
    ) == AT + timedelta(days=5)


def test_empty_modeled_sources_have_no_catalog_or_financial_reads() -> None:
    source = store()
    session = Mock()
    auth = Mock()
    value = source.capture(session, auth, (), retained_at=AT)
    assert value.snapshot is None and value.sources == () and value.license_version_ids == ()
    assert value.expires_at == AT + timedelta(days=30)
    session.execute.assert_not_called()
    session.scalar.assert_not_called()


def test_unlicensed_snapshot_has_no_invented_expiry_and_reload_keeps_original_copy() -> None:
    source = store()
    original_at = AT - timedelta(days=90)
    metadata = {
        "created_at": original_at,
        "valuation_at": original_at,
        "reporting_currency": "EUR",
        "calculation_run_id": UUID(int=12),
    }
    calculation = {"reporting_currency": "EUR", "output_fingerprint": "f" * 64}
    with patch.object(
        source, "_metadata", side_effect=[metadata, calculation, metadata, calculation]
    ):
        retained_at = AT - timedelta(days=2)
        first = source._snapshot_header(Mock(), Mock(), UUID(int=11), retained_at=retained_at)
        source._clock = lambda: AT + timedelta(days=1)
        second = source._snapshot_header(Mock(), Mock(), UUID(int=11), retained_at=retained_at)
    assert first.original_created_at == second.original_created_at == original_at
    assert first.expires_at == second.expires_at == retained_at + timedelta(days=30)
    assert "expires_at" not in first.metadata[0]
