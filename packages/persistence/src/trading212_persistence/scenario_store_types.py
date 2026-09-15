"""Private typed scenario persistence seams; no transport or source registration API."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from trading212_domain.scenario import ScenarioRecord, ScenarioVersionContent
from trading212_domain.scenario_execution import ScenarioExecutionInput, ScenarioReplaySelection
from trading212_domain.values import CurrencyCode


class ScenarioStorageErrorCode(StrEnum):
    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    RATE_LIMITED = "RATE_LIMITED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SCENARIO_UNAVAILABLE = "SCENARIO_UNAVAILABLE"
    RUN_EXPIRED = "RUN_EXPIRED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(slots=True)
class ScenarioStorageError(Exception):
    code: ScenarioStorageErrorCode

    def __str__(self) -> str:
        return "The scenario operation cannot be completed."


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredScenarioDefinition:
    id: UUID
    account_id: UUID
    name: str
    revision: int
    archived: bool
    current_version_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredScenarioVersion:
    id: UUID
    account_id: UUID
    definition_id: UUID
    version_number: int
    predecessor_id: UUID | None
    content: ScenarioVersionContent
    content_digest: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioCaptureSelection(ScenarioRecord):
    scenario_version_id: UUID
    portfolio_snapshot_id: UUID
    xray_run_id: UUID
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    replay: ScenarioReplaySelection | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedScenarioInputs:
    value: ScenarioExecutionInput
    license_version_ids: tuple[UUID, ...]
