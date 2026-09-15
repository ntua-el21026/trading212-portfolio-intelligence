"""Small canonical saved calculations for projection REST adapter tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

from trading212_application import projection_presentation as presentation
from trading212_application import projection_views as views
from trading212_application.risk import PremiumJobState

from tests.unit.application.projection_presentation_factories import (
    ACCOUNT as ACCOUNT,
)
from tests.unit.application.projection_presentation_factories import (
    GOAL as GOAL,
)
from tests.unit.application.projection_presentation_factories import (
    VERSION as VERSION,
)
from tests.unit.application.projection_presentation_factories import (
    retained,
)

SET, GOAL_ID, JOB = UUID(int=8801), UUID(int=8802), UUID(int=8803)
RUN = UUID(int=104)


@lru_cache(maxsize=1)
def saved() -> presentation.RetainedProjectionPresentation:
    return retained()


NOW = datetime(2025, 2, 1, 0, 0, 1, 999999, tzinfo=UTC)
METADATA = views.ProjectionVersionMetadata(
    name="Synthetic EUR assumption", description="Exact saved basis"
)


def assumption_set() -> views.AssumptionSetView:
    return views.AssumptionSetView(
        id=SET,
        account_id=ACCOUNT,
        name=METADATA.name,
        revision=1,
        current_version_id=VERSION,
        created_at=NOW,
        updated_at=NOW,
    )


def assumption_version() -> views.AssumptionVersionView:
    value = saved().capture.assumption_version
    return views.AssumptionVersionView(
        id=VERSION,
        account_id=ACCOUNT,
        set_id=SET,
        version_number=1,
        predecessor_id=None,
        metadata=METADATA,
        content=value.content,
        content_digest=value.content_digest,
        created_at=NOW,
    )


def goal() -> views.GoalView:
    return views.GoalView(
        id=GOAL_ID,
        account_id=ACCOUNT,
        name=METADATA.name,
        revision=1,
        current_version_id=GOAL,
        created_at=NOW,
        updated_at=NOW,
    )


def goal_version() -> views.GoalVersionView:
    value = saved().capture.goal_version
    assert value is not None
    return views.GoalVersionView(
        id=GOAL,
        account_id=ACCOUNT,
        goal_id=GOAL_ID,
        version_number=1,
        predecessor_id=None,
        metadata=METADATA,
        content=value.content,
        content_digest=value.content_digest,
        created_at=NOW,
    )


def page(*, offset: int = 0, limit: int = 25) -> views.ProjectionResultPage:
    selected = presentation.select_projection_page(saved(), offset=offset, limit=limit)
    return presentation.finalize_projection_page(
        selected,
        next_cursor=None if selected.next_ordinal is None else f"signed_{selected.next_ordinal}",
    )


def run(*, offset: int = 0, limit: int = 25) -> views.ProjectionRunView:
    value = saved()
    return views.ProjectionRunView(
        id=RUN,
        account_id=ACCOUNT,
        assumption_version_id=VERSION,
        goal_version_id=GOAL,
        job_id=JOB,
        capture_digest=value.capture_digest,
        numerical_input_digest=value.capture.numerical_input_digest,
        state=PremiumJobState.SUCCEEDED,
        result_availability="available",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        completed_at=NOW,
        failure_code=None,
        result=page(offset=offset, limit=limit),
    )


def queued() -> views.ProjectionOperationalRunView:
    value = saved()
    return views.ProjectionOperationalRunView(
        id=RUN,
        account_id=ACCOUNT,
        assumption_version_id=VERSION,
        goal_version_id=GOAL,
        job_id=JOB,
        capture_digest=value.capture_digest,
        numerical_input_digest=value.capture.numerical_input_digest,
        state=PremiumJobState.QUEUED,
        result_availability="pending",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        completed_at=None,
        failure_code=None,
    )


def cancelled() -> views.ProjectionOperationalRunView:
    return replace(
        queued(),
        state=PremiumJobState.CANCELLED,
        completed_at=NOW,
        result_availability="unavailable",
    )
