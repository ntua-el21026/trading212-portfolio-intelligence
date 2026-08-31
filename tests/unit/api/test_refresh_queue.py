from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from trading212_api.refresh_queue import _effective_selection
from trading212_application.ingestion import (
    CURRENT_REFRESH_ORDER,
    FULL_REFRESH_ORDER,
    RunMode,
)


class SelectionSession:
    def __init__(self, *, capabilities: tuple[str, ...], snapshot_id: UUID | None) -> None:
        self.capabilities = capabilities
        self.snapshot_id = snapshot_id

    def scalars(self, statement: Any) -> tuple[str, ...]:
        del statement
        return self.capabilities

    def scalar(self, statement: Any) -> UUID | None:
        del statement
        return self.snapshot_id


def test_complete_checkpoints_without_canonical_snapshot_still_force_initial_full_sync() -> None:
    session = cast(
        Session,
        SelectionSession(
            capabilities=tuple(capability.value for capability in FULL_REFRESH_ORDER),
            snapshot_id=None,
        ),
    )

    mode, capabilities, warning = _effective_selection(
        session,
        account_id=uuid4(),
        requested_mode=RunMode.INCREMENTAL,
        requested_capabilities=CURRENT_REFRESH_ORDER,
    )

    assert mode is RunMode.FULL
    assert capabilities == FULL_REFRESH_ORDER
    assert warning is not None


def test_complete_canonical_baseline_honors_requested_scope_and_mode() -> None:
    session = cast(
        Session,
        SelectionSession(
            capabilities=tuple(capability.value for capability in FULL_REFRESH_ORDER),
            snapshot_id=uuid4(),
        ),
    )

    mode, capabilities, warning = _effective_selection(
        session,
        account_id=uuid4(),
        requested_mode=RunMode.INCREMENTAL,
        requested_capabilities=CURRENT_REFRESH_ORDER,
    )

    assert mode is RunMode.INCREMENTAL
    assert capabilities == CURRENT_REFRESH_ORDER
    assert warning is None
