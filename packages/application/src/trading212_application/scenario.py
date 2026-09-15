"""Closed scenario commands, page queries and authorized service protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_domain.errors import fail_validation
from trading212_domain.scenario import ScenarioVersionContent
from trading212_domain.scenario_execution import ScenarioReplaySelection
from trading212_domain.sources import source_integer
from trading212_domain.values import CurrencyCode, require_bounded_text, require_utc
from trading212_security.principals import Principal

from .scenario_views import (
    ScenarioComparisonPage,
    ScenarioDefinitionView,
    ScenarioRunView,
    ScenarioVersionView,
)
from .targets import TargetServiceError, validate_target_idempotency_key
from .views import Page


class ScenarioErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SCENARIO_UNAVAILABLE = "SCENARIO_UNAVAILABLE"
    RUN_EXPIRED = "RUN_EXPIRED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    CURSOR_INVALID = "CURSOR_INVALID"


@dataclass(slots=True)
class ScenarioServiceError(Exception):
    code: ScenarioErrorCode
    message: str = "The scenario operation cannot be completed."

    def __str__(self) -> str:
        return self.message


def _ids(*values: UUID) -> None:
    if any(type(value) is not UUID for value in values):
        fail_validation("Canonical UUID identities are required.", field="id")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioCommand:
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        try:
            validate_target_idempotency_key(self.idempotency_key)
        except TargetServiceError:
            fail_validation("Invalid scenario idempotency key.", field="idempotency_key")
        require_bounded_text(self.correlation_id, field="correlation_id", maximum=120)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateScenario(ScenarioCommand):
    account_id: UUID
    content: ScenarioVersionContent

    def __post_init__(self) -> None:
        ScenarioCommand.__post_init__(self)
        _ids(self.account_id)
        if type(self.content) is not ScenarioVersionContent:
            fail_validation("A canonical scenario definition is required.", field="content")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateScenarioVersion(ScenarioCommand):
    scenario_id: UUID
    expected_revision: int
    content: ScenarioVersionContent

    def __post_init__(self) -> None:
        ScenarioCommand.__post_init__(self)
        _ids(self.scenario_id)
        source_integer(self.expected_revision, "expected_revision", 1, 512)
        if type(self.content) is not ScenarioVersionContent:
            fail_validation("A canonical scenario definition is required.", field="content")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateScenarioRun(ScenarioCommand):
    account_id: UUID
    scenario_version_id: UUID
    portfolio_snapshot_id: UUID
    xray_run_id: UUID
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    replay: ScenarioReplaySelection | None = None

    def __post_init__(self) -> None:
        ScenarioCommand.__post_init__(self)
        _ids(
            self.account_id, self.scenario_version_id, self.portfolio_snapshot_id, self.xray_run_id
        )
        if type(self.reporting_currency) is not CurrencyCode:
            fail_validation(
                "An explicit reporting currency is required.", field="reporting_currency"
            )
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        if self.replay is not None and type(self.replay) is not ScenarioReplaySelection:
            fail_validation("A saved replay selection is required.", field="replay")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelScenarioRun(ScenarioCommand):
    run_id: UUID

    def __post_init__(self) -> None:
        ScenarioCommand.__post_init__(self)
        _ids(self.run_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioPageQuery:
    limit: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        source_integer(self.limit, "limit", 1, 100)
        if self.cursor is not None:
            require_bounded_text(self.cursor, field="cursor", maximum=2048)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComponentPageQuery:
    component_limit: int = 25
    component_cursor: str | None = None

    def __post_init__(self) -> None:
        source_integer(self.component_limit, "component_limit", 1, 100)
        if self.component_cursor is not None:
            require_bounded_text(self.component_cursor, field="component_cursor", maximum=2048)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioComparisonQuery(ScenarioComponentPageQuery):
    run_ids: tuple[UUID, UUID]

    def __post_init__(self) -> None:
        ScenarioComponentPageQuery.__post_init__(self)
        if type(self.run_ids) is not tuple or len(self.run_ids) != 2:
            fail_validation("Exactly two ordered scenario run IDs are required.", field="run_ids")
        _ids(*self.run_ids)
        if self.run_ids[0] == self.run_ids[1]:
            fail_validation("Select distinct scenario runs.", field="run_ids")


class ScenarioService(Protocol):
    """Implementations authorize current scopes and source rights before decoding or paging."""

    async def create_definition(
        self, principal: Principal, command: CreateScenario
    ) -> ScenarioDefinitionView: ...

    async def create_version(
        self, principal: Principal, command: CreateScenarioVersion
    ) -> ScenarioVersionView: ...

    async def get_definition(
        self, principal: Principal, scenario_id: UUID
    ) -> ScenarioDefinitionView: ...

    async def get_version(self, principal: Principal, version_id: UUID) -> ScenarioVersionView: ...

    async def list_definitions(
        self, principal: Principal, account_id: UUID, query: ScenarioPageQuery
    ) -> Page[ScenarioDefinitionView]: ...

    async def list_versions(
        self, principal: Principal, scenario_id: UUID, query: ScenarioPageQuery
    ) -> Page[ScenarioVersionView]: ...

    async def create_run(
        self, principal: Principal, command: CreateScenarioRun
    ) -> ScenarioRunView: ...

    async def get_run(
        self,
        principal: Principal,
        run_id: UUID,
        query: ScenarioComponentPageQuery,
        *,
        expected_account_id: UUID | None = None,
    ) -> ScenarioRunView: ...

    async def list_runs(
        self, principal: Principal, account_id: UUID, query: ScenarioPageQuery
    ) -> Page[ScenarioRunView]: ...

    async def compare(
        self, principal: Principal, account_id: UUID, query: ScenarioComparisonQuery
    ) -> ScenarioComparisonPage: ...

    async def cancel_run(
        self, principal: Principal, command: CancelScenarioRun
    ) -> ScenarioRunView: ...
