"""Identity-bound pages over already authorized immutable projection results.

The persistence service must establish current grants and source authority before
calling this helper and recheck them before returning its financial view.
"""

from __future__ import annotations

from datetime import datetime

from trading212_domain.serialization import canonical_json
from trading212_domain.values import require_utc
from trading212_security.principals import Principal

from .projection import ProjectionErrorCode, ProjectionPointPageQuery, ProjectionServiceError
from .projection_presentation import (
    RetainedProjectionPresentation,
    finalize_projection_page,
    select_projection_page,
)
from .projection_views import PROJECTION_PUBLIC_VIEW_VERSION, ProjectionResultPage
from .queries import CursorCodec, CursorValidationError

_RESOURCE = "projection_points_v1"


def project_saved_projection_page(
    principal: Principal,
    retained: RetainedProjectionPresentation,
    query: ProjectionPointPageQuery,
    *,
    cursors: CursorCodec,
    expires_at: datetime,
    now: datetime,
) -> ProjectionResultPage:
    """Bind every page to original financial/calendar identity and current expiry."""
    now, expires_at = require_utc(now), require_utc(expires_at)
    if type(query) is not ProjectionPointPageQuery:
        raise ProjectionServiceError(ProjectionErrorCode.VALIDATION_FAILED)
    if expires_at <= now:
        raise ProjectionServiceError(ProjectionErrorCode.RUN_EXPIRED)
    binding = canonical_json(
        {
            "issuer": principal.issuer,
            "subject": principal.subject,
            "owner_id": principal.owner_id,
            "account_id": retained.account_id,
            "run_id": retained.run_id,
            "result_id": retained.result_id,
            "capture_digest": retained.capture_digest,
            "numerical_input_digest": retained.capture.numerical_input_digest,
            "saved_result_digest": retained.saved_result_digest,
            "view": PROJECTION_PUBLIC_VIEW_VERSION,
            "resource": _RESOURCE,
            "limit": query.point_limit,
            "expires_at": expires_at,
        }
    )
    total = sum(
        len(path.points) for variant in retained.calculation.variants for path in variant.paths
    )
    offset, cutoff = 0, now
    if query.point_cursor is not None:
        try:
            cutoff, key = cursors.decode(
                query.point_cursor, resource=_RESOURCE, binding=binding, key_size=2
            )
            offset = int(key[0])
            if (
                str(offset) != key[0]
                or not 0 < offset < total
                or key[1] != expires_at.isoformat()
                or cutoff > now
                or cutoff >= expires_at
            ):
                raise CursorValidationError("invalid cursor")
        except (CursorValidationError, ValueError):
            raise ProjectionServiceError(ProjectionErrorCode.CURSOR_INVALID) from None
    selected = select_projection_page(retained, offset=offset, limit=query.point_limit)
    cursor = None
    if selected.next_ordinal is not None:
        cursor = cursors.encode(
            resource=_RESOURCE,
            binding=binding,
            read_cutoff=cutoff,
            key=(str(selected.next_ordinal), expires_at.isoformat()),
        )
    return finalize_projection_page(selected, next_cursor=cursor)
