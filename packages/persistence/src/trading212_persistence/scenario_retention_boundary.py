"""Current physical and licensed retention boundaries for private scenario copies."""

from datetime import datetime

from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code


def require_scenario_retention(
    *, expires_at: datetime, copy_deadline: datetime, now: datetime
) -> None:
    if expires_at <= now or expires_at > copy_deadline:
        raise ScenarioStorageError(Code.RUN_EXPIRED)
