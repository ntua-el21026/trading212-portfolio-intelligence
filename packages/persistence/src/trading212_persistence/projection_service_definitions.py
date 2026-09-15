"""Twelve closed assumption/goal operations over immutable authorized stores."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import projection as app
from trading212_application.projection_views import (
    AssumptionSetView,
    AssumptionVersionView,
    GoalVersionView,
    GoalView,
)
from trading212_application.views import Page
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotResource
from .projection_models import (
    AssumptionSetModel,
    AssumptionVersionModel,
    GoalModel,
    GoalVersionModel,
)
from .projection_service_base import ProjectionServiceBase
from .report_authorization import ReportAuthorization


class ProjectionDefinitionService(ProjectionServiceBase):
    """The base owns transactions, current grants, locks and stable actor cursors.

    Each public result goes through its inherited immutable read/publication method,
    including every row in a collection snapshot. IDs in a saved collection never
    substitute for the current authority of the selected calibration sources.
    """

    async def create_assumption_set(
        self, principal: Principal, command: app.CreateAssumptionSet
    ) -> AssumptionSetView:
        if type(command) is not app.CreateAssumptionSet:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)
        return await self._execute(
            principal,
            command.account_id,
            lambda session, auth: self.publish_assumption_set(session, auth, command),
            write="assumption",
        )

    async def create_assumption_version(
        self, principal: Principal, command: app.CreateAssumptionVersion
    ) -> AssumptionVersionView:
        if type(command) is not app.CreateAssumptionVersion:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)
        return await self._execute(
            principal,
            None,
            lambda session, auth: self.publish_assumption_version(session, auth, command),
            write="assumption",
            resource=(AssumptionSetModel, command.set_id),
        )

    async def get_assumption_set(self, principal: Principal, set_id: UUID) -> AssumptionSetView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self.read_assumption_set(session, auth, set_id),
            resource=(AssumptionSetModel, set_id),
        )

    async def get_assumption_version(
        self, principal: Principal, version_id: UUID
    ) -> AssumptionVersionView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self.read_assumption_version(session, auth, version_id),
            resource=(AssumptionVersionModel, version_id),
        )

    async def list_assumption_sets(
        self, principal: Principal, account_id: UUID, query: app.ProjectionPageQuery
    ) -> Page[AssumptionSetView]:
        if type(query) is not app.ProjectionPageQuery:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> Page[AssumptionSetView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.ASSUMPTION_SETS,
                query,
                select(AssumptionSetModel.id)
                .where(
                    AssumptionSetModel.owner_id == auth.owner_id,
                    AssumptionSetModel.account_id == auth.account_id,
                )
                .order_by(AssumptionSetModel.created_at.desc(), AssumptionSetModel.id.desc()),
            )
            rows = tuple(
                self.read_assumption_set(session, auth, identifier)
                for identifier in page.record_ids
            )
            return Page(rows, page.next_cursor, page.limit, page.exact_total)

        return await self._execute(principal, account_id, operation)

    async def list_assumption_versions(
        self, principal: Principal, set_id: UUID, query: app.ProjectionPageQuery
    ) -> Page[AssumptionVersionView]:
        if type(query) is not app.ProjectionPageQuery:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> Page[AssumptionVersionView]:
            self.read_assumption_set(session, auth, set_id)
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.ASSUMPTION_VERSIONS,
                query,
                select(AssumptionVersionModel.id)
                .where(
                    AssumptionVersionModel.owner_id == auth.owner_id,
                    AssumptionVersionModel.account_id == auth.account_id,
                    AssumptionVersionModel.set_id == set_id,
                    AssumptionVersionModel.sealed.is_(True),
                )
                .order_by(
                    AssumptionVersionModel.version_number.desc(),
                    AssumptionVersionModel.id.desc(),
                ),
                set_id,
            )
            rows = tuple(
                self.read_assumption_version(session, auth, identifier)
                for identifier in page.record_ids
            )
            return Page(rows, page.next_cursor, page.limit, page.exact_total)

        return await self._execute(
            principal, None, operation, resource=(AssumptionSetModel, set_id)
        )

    async def create_goal(self, principal: Principal, command: app.CreateGoal) -> GoalView:
        if type(command) is not app.CreateGoal:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)
        return await self._execute(
            principal,
            command.account_id,
            lambda session, auth: self.publish_goal(session, auth, command),
            write="goal",
        )

    async def create_goal_version(
        self, principal: Principal, command: app.CreateGoalVersion
    ) -> GoalVersionView:
        if type(command) is not app.CreateGoalVersion:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)
        return await self._execute(
            principal,
            None,
            lambda session, auth: self.publish_goal_version(session, auth, command),
            write="goal",
            resource=(GoalModel, command.goal_id),
        )

    async def get_goal(self, principal: Principal, goal_id: UUID) -> GoalView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self.read_goal(session, auth, goal_id),
            resource=(GoalModel, goal_id),
        )

    async def get_goal_version(self, principal: Principal, version_id: UUID) -> GoalVersionView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self.read_goal_version(session, auth, version_id),
            resource=(GoalVersionModel, version_id),
        )

    async def list_goals(
        self, principal: Principal, account_id: UUID, query: app.ProjectionPageQuery
    ) -> Page[GoalView]:
        if type(query) is not app.ProjectionPageQuery:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> Page[GoalView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.GOALS,
                query,
                select(GoalModel.id)
                .where(
                    GoalModel.owner_id == auth.owner_id,
                    GoalModel.account_id == auth.account_id,
                )
                .order_by(GoalModel.created_at.desc(), GoalModel.id.desc()),
            )
            rows = tuple(
                self.read_goal(session, auth, identifier) for identifier in page.record_ids
            )
            return Page(rows, page.next_cursor, page.limit, page.exact_total)

        return await self._execute(principal, account_id, operation)

    async def list_goal_versions(
        self, principal: Principal, goal_id: UUID, query: app.ProjectionPageQuery
    ) -> Page[GoalVersionView]:
        if type(query) is not app.ProjectionPageQuery:
            raise app.ProjectionServiceError(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> Page[GoalVersionView]:
            self.read_goal(session, auth, goal_id)
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.GOAL_VERSIONS,
                query,
                select(GoalVersionModel.id)
                .where(
                    GoalVersionModel.owner_id == auth.owner_id,
                    GoalVersionModel.account_id == auth.account_id,
                    GoalVersionModel.goal_id == goal_id,
                    GoalVersionModel.sealed.is_(True),
                )
                .order_by(GoalVersionModel.version_number.desc(), GoalVersionModel.id.desc()),
                goal_id,
            )
            rows = tuple(
                self.read_goal_version(session, auth, identifier) for identifier in page.record_ids
            )
            return Page(rows, page.next_cursor, page.limit, page.exact_total)

        return await self._execute(principal, None, operation, resource=(GoalModel, goal_id))
