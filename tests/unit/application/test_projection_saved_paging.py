"""Complete saved point traversal and stable actor/resource cursor boundaries."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from trading212_application.projection import (
    ProjectionErrorCode,
    ProjectionPointPageQuery,
    ProjectionServiceError,
)
from trading212_application.projection_capture import projection_capture_digest
from trading212_application.projection_paging import project_saved_projection_page
from trading212_application.projection_presentation import (
    RetainedProjectionPresentation,
    projection_public_bytes,
)
from trading212_application.projection_views import ProjectionPointRow
from trading212_application.queries import CursorCodec
from trading212_security.principals import Principal, Scope

from tests.unit.application.projection_presentation_factories import retained

AT = datetime(2026, 9, 15, tzinfo=UTC)
UNTIL = AT + timedelta(days=1)
KEY = b"synthetic-projection-cursor-boundary" * 2


@pytest.fixture(scope="module")
def saved() -> RetainedProjectionPresentation:
    return retained(observed=False, source_count=0)


def actor() -> Principal:
    return Principal(
        str(UUID(int=10001)),
        str(UUID(int=10002)),
        "synthetic.issuer",
        "same-subject",
        frozenset(Scope),
        AT - timedelta(hours=1),
        AT + timedelta(days=2),
    )


def test_point_pages_preserve_every_saved_variant_path_checkpoint_once(
    saved: RetainedProjectionPresentation,
) -> None:
    cursor = None
    codec = CursorCodec(KEY, clock=lambda: AT)
    all_rows: list[ProjectionPointRow] = []
    summaries = None
    for _ in range(100):
        page = project_saved_projection_page(
            actor(),
            saved,
            ProjectionPointPageQuery(point_limit=5, point_cursor=cursor),
            cursors=codec,
            expires_at=UNTIL,
            now=AT,
        )
        assert page.context.saved_result_digest == saved.saved_result_digest
        assert len(projection_public_bytes(page)) <= 1024 * 1024
        assert page.points.items and len(page.points.items) <= 5
        if summaries is not None:
            assert page.variants == summaries
        summaries = page.variants
        all_rows.extend(page.points.items)
        cursor = page.points.next_cursor
        if cursor is None:
            break
    else:
        pytest.fail("Retained paging did not finish within its finite point count.")
    expected = [
        (variant.variant, path.index, ordinal, point.month, point.nominal, point.real)
        for variant in saved.calculation.variants
        for path in variant.paths
        for ordinal, point in enumerate(path.points)
    ]
    assert [
        (
            row.variant,
            row.path_index,
            row.point_index,
            row.point.month,
            row.point.nominal.amount,
            row.point.real.amount,
        )
        for row in all_rows
    ] == expected
    assert [row.ordinal for row in all_rows] == list(range(len(expected)))


def test_refreshing_a_token_preserves_cursor_identity(
    saved: RetainedProjectionPresentation,
) -> None:
    principal = actor()
    codec = CursorCodec(KEY, clock=lambda: AT)
    first = project_saved_projection_page(
        principal,
        saved,
        ProjectionPointPageQuery(point_limit=3),
        cursors=codec,
        expires_at=UNTIL,
        now=AT,
    )
    assert first.points.next_cursor is not None
    refreshed = replace(principal, authenticated_at=AT, expires_at=AT + timedelta(days=3))
    page = project_saved_projection_page(
        refreshed,
        saved,
        ProjectionPointPageQuery(point_limit=3, point_cursor=first.points.next_cursor),
        cursors=codec,
        expires_at=UNTIL,
        now=AT,
    )
    assert page.points.start_ordinal == 3


@pytest.mark.parametrize(
    "change", ("issuer", "subject", "owner", "run", "result", "account", "limit", "expiry")
)
def test_cursor_cannot_change_its_authorized_saved_resource(
    saved: RetainedProjectionPresentation, change: str
) -> None:
    principal = actor()
    codec = CursorCodec(KEY, clock=lambda: AT)
    first = project_saved_projection_page(
        principal,
        saved,
        ProjectionPointPageQuery(point_limit=3),
        cursors=codec,
        expires_at=UNTIL,
        now=AT,
    )
    assert first.points.next_cursor is not None
    target, limit, expiry = saved, 3, UNTIL
    if change == "issuer":
        principal = replace(principal, issuer="other.issuer")
    elif change == "subject":
        principal = replace(principal, subject="other-subject")
    elif change == "owner":
        principal = replace(principal, owner_id=str(UUID(int=10003)))
    elif change == "run":
        target = replace(saved, run_id=UUID(int=10004))
    elif change == "result":
        target = replace(saved, result_id=UUID(int=10005))
    elif change == "account":
        account = UUID(int=10006)
        capture = replace(
            saved.capture,
            selection=replace(saved.capture.selection, account_id=account),
            assumption_version=replace(saved.capture.assumption_version, account_id=account),
            goal_version=None
            if saved.capture.goal_version is None
            else replace(saved.capture.goal_version, account_id=account),
        )
        target = replace(
            saved,
            account_id=account,
            capture=capture,
            capture_digest=projection_capture_digest(capture),
        )
    elif change == "limit":
        limit = 4
    else:
        expiry -= timedelta(hours=1)
    with pytest.raises(ProjectionServiceError) as rejected:
        project_saved_projection_page(
            principal,
            target,
            ProjectionPointPageQuery(point_limit=limit, point_cursor=first.points.next_cursor),
            cursors=codec,
            expires_at=expiry,
            now=AT,
        )
    assert rejected.value.code is ProjectionErrorCode.CURSOR_INVALID


def test_expired_source_boundary_rejects_before_cursor_decode(
    saved: RetainedProjectionPresentation,
) -> None:
    with pytest.raises(ProjectionServiceError) as expired:
        project_saved_projection_page(
            actor(),
            saved,
            ProjectionPointPageQuery(point_cursor="invalid-cursor"),
            cursors=CursorCodec(KEY, clock=lambda: AT),
            expires_at=AT,
            now=AT,
        )
    assert expired.value.code is ProjectionErrorCode.RUN_EXPIRED
