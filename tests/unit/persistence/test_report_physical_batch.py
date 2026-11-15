"""Bounds and fail-closed SQL shape for batched physical report authority."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session
from trading212_domain.reports import MAX_REPORT_DATASET_ROWS, ReportSourceUse
from trading212_persistence import report_sources as sources
from trading212_security.principals import AuthorizationError

NOW = datetime(2026, 11, 15, tzinfo=UTC)
OWNER = UUID(int=1000)


class MetadataSession:
    """Return only physical-header scalars; never emulate license or payload readers."""

    def __init__(self, **override: object) -> None:
        self.override = override
        self.sql: list[str] = []
        self.windows: list[tuple[UUID, ...]] = []

    def execute(self, statement: Any) -> Any:
        dialect_factory = cast(Callable[[], Dialect], postgresql.dialect)
        compiled = statement.compile(dialect=dialect_factory())
        self.sql.append(str(compiled))
        windows = [
            tuple(value)
            for value in compiled.params.values()
            if isinstance(value, (list, tuple))
            and value
            and all(isinstance(member, UUID) for member in value)
        ]
        assert len(windows) == 1
        identifiers = windows[0]
        self.windows.append(identifiers)
        rows = [
            SimpleNamespace(
                **{
                    "id": identifier,
                    "expires_at": NOW + timedelta(days=1),
                    "expiry_pending": False,
                    "retention_pending": False,
                    "acquisition_restricted": False,
                    **self.override,
                }
            )
            for identifier in identifiers
        ]
        return SimpleNamespace(all=lambda: rows)


def permit(session: MetadataSession, identifiers: tuple[UUID, ...], **override: Any) -> None:
    candidate = sources._physical_permit_many
    candidate(
        cast(Session, session),
        owner_id=OWNER,
        family="fx",
        source_ids=identifiers,
        source_use=ReportSourceUse.REPORT,
        now=NOW,
        **override,
    )


def test_empty_physical_membership_selects_nothing() -> None:
    session = MetadataSession()
    permit(session, ())
    assert session.sql == []


def test_physical_membership_keeps_512_id_windows_and_selects_metadata_only() -> None:
    session = MetadataSession()
    identifiers = tuple(UUID(int=index + 1) for index in range(1025))
    permit(session, identifiers)
    assert [len(window) for window in session.windows] == [512, 512, 1]
    assert tuple(member for window in session.windows for member in window) == identifiers
    assert all("acquisition_source_restricted" in sql for sql in session.sql)
    assert all(
        "source_expiry_events" in sql and "source_retention_work" in sql for sql in session.sql
    )
    assert all("CASE WHEN" in sql and "adapter_version" in sql for sql in session.sql)
    assert all(
        not any(
            token in sql.lower()
            for token in (
                "canonical_",
                "metadata_json",
                "contents",
                "observations",
                "rate",
                "payload",
            )
        )
        for sql in session.sql
    )


@pytest.mark.parametrize("family", tuple(sources._PHYSICAL))
def test_each_closed_family_uses_the_original_pending_tables(family: str) -> None:
    session = MetadataSession()
    candidate = sources._physical_permit_many
    candidate(
        cast(Session, session),
        owner_id=OWNER,
        family=family,
        source_ids=(UUID(int=1),),
        source_use=ReportSourceUse.REPORT,
        now=NOW,
    )
    sql = session.sql[0]
    physical = family in {"price", "fx", "benchmark", "corporate_action", "constituent"}
    assert ("source_expiry_events" in sql) is physical
    assert ("source_retention_work" in sql) is physical
    assert ("enrichment_expiry_events" in sql) is not physical
    assert ("enrichment_retention_work" in sql) is not physical
    assert ("acquisition_source_restricted" in sql) is (family in {"price", "fx"})


@pytest.mark.parametrize("flag", ("expiry_pending", "retention_pending", "acquisition_restricted"))
def test_any_physical_restriction_denies(flag: str) -> None:
    with pytest.raises(AuthorizationError):
        permit(MetadataSession(**{flag: True}), (UUID(int=1),))


@pytest.mark.parametrize("value", (None, 0, "false"))
def test_non_false_acquisition_result_never_allows(value: object) -> None:
    with pytest.raises(AuthorizationError):
        permit(MetadataSession(acquisition_restricted=value), (UUID(int=1),))


@pytest.mark.parametrize("expiry", (NOW, NOW - timedelta(microseconds=1)))
def test_original_expiry_comparison_is_closed_at_the_boundary(expiry: datetime) -> None:
    with pytest.raises(AuthorizationError):
        permit(MetadataSession(expires_at=expiry), (UUID(int=1),))


def test_missing_or_wrong_source_identity_denies() -> None:
    with pytest.raises(AuthorizationError):
        permit(MetadataSession(id=UUID(int=999)), (UUID(int=1),))


@pytest.mark.parametrize(
    "identifiers",
    (
        (UUID(int=1),) * (MAX_REPORT_DATASET_ROWS + 1),
        (UUID(int=1), UUID(int=1)),
    ),
)
def test_invalid_inventory_fails_before_query(identifiers: tuple[UUID, ...]) -> None:
    session = MetadataSession()
    with pytest.raises(AuthorizationError):
        permit(session, identifiers)
    assert session.sql == []


@pytest.mark.parametrize("family", ("unknown", "fx;SELECT", "https://invalid.test"))
def test_family_cannot_select_a_table_or_provider(family: str) -> None:
    session = MetadataSession()
    candidate = sources._physical_permit_many
    with pytest.raises(AuthorizationError):
        candidate(
            cast(Session, session),
            owner_id=OWNER,
            family=family,
            source_ids=(UUID(int=1),),
            source_use=ReportSourceUse.REPORT,
            now=NOW,
        )
    assert session.sql == []


def test_fresh_authority_call_does_not_reuse_a_previous_permit() -> None:
    session = MetadataSession()
    permit(session, (UUID(int=1),))
    session.override["retention_pending"] = True
    with pytest.raises(AuthorizationError):
        permit(session, (UUID(int=1),))
    assert len(session.sql) == 2


@pytest.mark.parametrize("source_use", ("report", "export", None))
def test_untyped_source_use_denies_before_query(source_use: object) -> None:
    session = MetadataSession()
    candidate = sources._physical_permit_many
    with pytest.raises(AuthorizationError):
        candidate(
            cast(Session, session),
            owner_id=OWNER,
            family="fx",
            source_ids=(UUID(int=1),),
            source_use=cast(ReportSourceUse, source_use),
            now=NOW,
        )
    assert session.sql == []
