"""Exact authorized origins are deduplicated; missing and oversized lineage fails."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from trading212_application.projection import ProjectionErrorCode
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_source_memberships import retained_source_keys
from trading212_persistence.projection_source_store import ProjectionSourceHeader, SourceKind

AT = datetime(2026, 9, 15, 12, tzinfo=UTC)


def header(kind: SourceKind, identity: int) -> ProjectionSourceHeader:
    return ProjectionSourceHeader(
        kind=kind,
        role="calibration",
        subject_id=UUID(int=identity),
        content_digest="1" * 64,
        original_created_at=AT,
        expires_at=AT + timedelta(days=1),
        metadata=(),
        license_version_ids=(),
    )


def test_dedup_preserves_earliest_original_license_clock_and_exact_parent_kind() -> None:
    history = replace(
        header("historical_input", 10),
        retained_sources=(
            ("historical", UUID(int=10), AT),
            ("price", UUID(int=11), AT - timedelta(days=2)),
            ("license", UUID(int=12), AT),
        ),
    )
    other = replace(
        header("historical_input", 20),
        retained_sources=(
            ("historical", UUID(int=20), AT - timedelta(days=1)),
            ("price", UUID(int=11), AT - timedelta(days=2)),
            ("license", UUID(int=12), AT - timedelta(days=1)),
        ),
    )
    direct = replace(
        header("price_total_return", 11),
        retained_sources=(("price", UUID(int=11), AT - timedelta(days=2)),),
    )
    actual = retained_source_keys((other, direct, history))
    assert actual == (
        ("historical", UUID(int=10), AT),
        ("historical", UUID(int=20), AT - timedelta(days=1)),
        ("license", UUID(int=12), AT - timedelta(days=1)),
        ("price", UUID(int=11), AT - timedelta(days=2)),
    )
    assert retained_source_keys((history, other, direct)) == actual


@pytest.mark.parametrize(
    "members",
    [
        (),
        (("fx", UUID(int=1), AT),),
        (("arbitrary", UUID(int=1), AT),),
        (("price", UUID(int=1), AT.replace(tzinfo=None)),),
    ],
)
def test_missing_mistyped_or_non_utc_original_origin_is_rejected(
    members: tuple[tuple[str, UUID, datetime], ...],
) -> None:
    with pytest.raises(ProjectionStorageError) as error:
        retained_source_keys((replace(header("price_total_return", 1), retained_sources=members),))
    assert error.value.code is ProjectionErrorCode.SOURCE_UNAVAILABLE


def test_aggregate_membership_limit_rejects_instead_of_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trading212_persistence.projection_source_memberships as module

    monkeypatch.setattr(module, "MAX_RETAINED_SOURCE_MEMBERSHIPS", 2)
    value = replace(
        header("historical_input", 1),
        retained_sources=(
            ("historical", UUID(int=1), AT),
            ("price", UUID(int=2), AT),
            ("fx", UUID(int=3), AT),
        ),
    )
    with pytest.raises(ProjectionStorageError) as error:
        retained_source_keys((value,))
    assert error.value.code is ProjectionErrorCode.INPUT_BOUND_EXCEEDED
