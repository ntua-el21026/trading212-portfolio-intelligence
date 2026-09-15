"""Closed owner-assumption commands and stable definition/version metadata pages."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import scenario as app
from trading212_application.scenario_views import ScenarioDefinitionView, ScenarioVersionView
from trading212_application.views import Page
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotResource
from .report_authorization import ReportAuthorization
from .scenario_models import ScenarioDefinitionModel, ScenarioVersionModel
from .scenario_service_base import ScenarioServiceBase, scenario_error
from .scenario_store_types import StoredScenarioDefinition, StoredScenarioVersion


def definition_view(value: StoredScenarioDefinition) -> ScenarioDefinitionView:
    return ScenarioDefinitionView(
        id=value.id,
        account_id=value.account_id,
        name=value.name,
        revision=value.revision,
        archived=value.archived,
        current_version_id=value.current_version_id,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def version_view(value: StoredScenarioVersion) -> ScenarioVersionView:
    return ScenarioVersionView(
        id=value.id,
        account_id=value.account_id,
        definition_id=value.definition_id,
        version_number=value.version_number,
        predecessor_id=value.predecessor_id,
        content=value.content,
        content_digest=value.content_digest,
        created_at=value.created_at,
    )


class ScenarioDefinitionService(ScenarioServiceBase):
    async def create_definition(
        self, principal: Principal, command: app.CreateScenario
    ) -> ScenarioDefinitionView:
        if type(command) is not app.CreateScenario:
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)
        return await self._execute(
            principal,
            command.account_id,
            lambda session, auth: definition_view(
                self.publish_definition(
                    session,
                    auth,
                    command.content,
                    idempotency_key=command.idempotency_key,
                    correlation_id=command.correlation_id,
                )
            ),
            write=True,
        )

    async def create_version(
        self, principal: Principal, command: app.CreateScenarioVersion
    ) -> ScenarioVersionView:
        if type(command) is not app.CreateScenarioVersion:
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)
        return await self._execute(
            principal,
            None,
            lambda session, auth: version_view(
                self.publish_version(
                    session,
                    auth,
                    command.scenario_id,
                    command.expected_revision,
                    command.content,
                    idempotency_key=command.idempotency_key,
                    correlation_id=command.correlation_id,
                )
            ),
            write=True,
            resource=(ScenarioDefinitionModel, command.scenario_id),
        )

    async def get_definition(
        self, principal: Principal, scenario_id: UUID
    ) -> ScenarioDefinitionView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: definition_view(self.read_definition(session, auth, scenario_id)),
            resource=(ScenarioDefinitionModel, scenario_id),
        )

    async def get_version(self, principal: Principal, version_id: UUID) -> ScenarioVersionView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: version_view(self.read_version(session, auth, version_id)),
            resource=(ScenarioVersionModel, version_id),
        )

    async def list_definitions(
        self, principal: Principal, account_id: UUID, query: app.ScenarioPageQuery
    ) -> Page[ScenarioDefinitionView]:
        def operation(session: Session, auth: ReportAuthorization) -> Page[ScenarioDefinitionView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.SCENARIO_DEFINITIONS,
                query,
                select(ScenarioDefinitionModel.id)
                .where(
                    ScenarioDefinitionModel.owner_id == auth.owner_id,
                    ScenarioDefinitionModel.account_id == auth.account_id,
                )
                .order_by(
                    ScenarioDefinitionModel.created_at.desc(), ScenarioDefinitionModel.id.desc()
                ),
            )
            rows = tuple(
                definition_view(self.read_definition(session, auth, identifier))
                for identifier in page.record_ids
            )
            return Page(rows, page.next_cursor, page.limit, page.exact_total)

        return await self._execute(principal, account_id, operation)

    async def list_versions(
        self, principal: Principal, scenario_id: UUID, query: app.ScenarioPageQuery
    ) -> Page[ScenarioVersionView]:
        def operation(session: Session, auth: ReportAuthorization) -> Page[ScenarioVersionView]:
            self.read_definition(session, auth, scenario_id)
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.SCENARIO_VERSIONS,
                query,
                select(ScenarioVersionModel.id)
                .where(
                    ScenarioVersionModel.owner_id == auth.owner_id,
                    ScenarioVersionModel.account_id == auth.account_id,
                    ScenarioVersionModel.definition_id == scenario_id,
                    ScenarioVersionModel.sealed.is_(True),
                )
                .order_by(
                    ScenarioVersionModel.version_number.desc(), ScenarioVersionModel.id.desc()
                ),
                scenario_id,
            )
            rows = tuple(
                version_view(self.read_version(session, auth, identifier))
                for identifier in page.record_ids
            )
            return Page(rows, page.next_cursor, page.limit, page.exact_total)

        return await self._execute(
            principal, None, operation, resource=(ScenarioDefinitionModel, scenario_id)
        )
