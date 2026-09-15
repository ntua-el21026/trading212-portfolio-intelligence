"""Shared accounting for bounded source, historical and X-ray payload expiry.

This module does not authorize a read, perform SQL or decide that a source is
fully purged. Callers retain their exact-source locks and pending-work state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

MAX_PURGE_CAPTURES = 100
MAX_PURGE_RUNS = 100
MAX_PURGE_ROWS = 4096
MAX_PURGE_BYTES = 64 * 1024 * 1024
MAX_PURGE_BATCH_ROWS = 512

PurgeFamily = Literal[
    "historical", "xray", "report", "export", "alert", "risk", "scenario", "projection", "research"
]


def _count(value: int, maximum: int, field_name: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"A bounded nonnegative {field_name} is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadCopyCost:
    """Size metadata for one physical row's licensed payload being cleared.

    The SQL participant computes logical bytes for its closed payload columns,
    before fetching those columns. Distinct copies get distinct costs, including
    a duplicate canonical document. Tombstone identity is not copied payload.
    """

    row_id: UUID
    payload_bytes: int
    # Includes fixed SQL trigger/constraint work performed by this exact mutation.
    inspection_rows: int = 1
    payload_inspections: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.row_id, UUID):
            raise ValueError("A typed payload row identity is required.")
        # An oversized existing row must remain pending, not wrap or be rounded.
        if type(self.payload_bytes) is not int or self.payload_bytes < 0:
            raise ValueError("A nonnegative logical payload byte size is required.")
        if (
            type(self.inspection_rows) is not int
            or not 1 <= self.inspection_rows <= MAX_PURGE_BATCH_ROWS
        ):
            raise ValueError("A bounded positive physical inspection cost is required.")
        if type(self.payload_inspections) is not int or not 1 <= self.payload_inspections <= 2:
            raise ValueError("A bounded payload inspection multiplicity is required.")


@dataclass(slots=True, kw_only=True)
class SourcePurgeBudget:
    """One invocation's remaining limits, shared by every typed participant.

    Smaller initial allowances support a caller's remaining budget and focused
    boundary checks. No allowance may exceed ADR-0017. A participant is counted
    once per invocation; each repeated physical inspection is charged again.
    """

    captures: int = MAX_PURGE_CAPTURES
    runs: int = MAX_PURGE_RUNS
    rows_inspected: int = MAX_PURGE_ROWS
    rows_removed: int = MAX_PURGE_ROWS
    bytes_inspected: int = MAX_PURGE_BYTES
    bytes_removed: int = MAX_PURGE_BYTES
    artifacts: int = 100
    _captures_seen: set[tuple[PurgeFamily, UUID]] = field(
        default_factory=set, init=False, repr=False
    )
    _runs_seen: set[tuple[PurgeFamily, UUID]] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        for name, maximum in (
            ("captures", MAX_PURGE_CAPTURES),
            ("runs", MAX_PURGE_RUNS),
            ("rows_inspected", MAX_PURGE_ROWS),
            ("rows_removed", MAX_PURGE_ROWS),
            ("bytes_inspected", MAX_PURGE_BYTES),
            ("bytes_removed", MAX_PURGE_BYTES),
            ("artifacts", 100),
        ):
            _count(getattr(self, name), maximum, name)

    def _enter(self, family: PurgeFamily, identifier: UUID, *, capture: bool) -> bool:
        if family not in (
            "historical",
            "xray",
            "report",
            "export",
            "alert",
            "risk",
            "scenario",
            "projection",
            "research",
        ) or not isinstance(identifier, UUID):
            raise ValueError("A typed purge participant is required.")
        seen = self._captures_seen if capture else self._runs_seen
        key = (family, identifier)
        if key in seen:
            return True
        name = "captures" if capture else "runs"
        remaining = getattr(self, name)
        if remaining == 0:
            return False
        setattr(self, name, remaining - 1)
        seen.add(key)
        return True

    def enter_capture(self, family: PurgeFamily, identifier: UUID) -> bool:
        """Reserve an exact capture before inspecting its payload phases."""
        return self._enter(family, identifier, capture=True)

    def enter_run(self, family: PurgeFamily, identifier: UUID) -> bool:
        """Reserve an exact run before inspecting its payload phases."""
        return self._enter(family, identifier, capture=False)

    @property
    def metadata_limit(self) -> int:
        """Maximum indexed size-only rows a caller may request next.

        The caller then charges every returned row with inspect(rows=n,
        payload_bytes=0), including rows whose payload will not fit. Fetching
        the payload later is a second physical inspection, charged separately.
        """
        return min(MAX_PURGE_BATCH_ROWS, self.rows_inspected)

    def inspect(self, *, rows: int, payload_bytes: int = 0) -> bool:
        """Reserve one bounded read before payload I/O, without partial charge."""
        _count(rows, MAX_PURGE_BATCH_ROWS, "inspection row count")
        _count(payload_bytes, MAX_PURGE_BYTES, "inspection byte count")
        if rows == 0 and payload_bytes:
            raise ValueError("Payload inspection requires a physical row.")
        if rows > self.rows_inspected or payload_bytes > self.bytes_inspected:
            return False
        self.rows_inspected -= rows
        self.bytes_inspected -= payload_bytes
        return True

    def reserve_clear_batch(self, costs: Sequence[PayloadCopyCost]) -> tuple[UUID, ...]:
        """Reserve a stable prefix for SQL clearing/deletion, before mutation.

        Input is an already charged size-only batch ordered by the participant's
        indexed key. Every affected row is both inspected and removed even when
        an UPDATE retains its tombstone. Stop at the first non-fitting row; never
        skip it and advance a keyset cursor past pending work. SQL must mutate
        only these IDs with the same owner/parent/phase predicates under a lock.
        A failed transaction discards this budget; there is no refund-and-retry
        path that could conceal repeated inspections.
        """
        _count(len(costs), MAX_PURGE_BATCH_ROWS, "payload batch size")
        if any(not isinstance(cost, PayloadCopyCost) for cost in costs):
            raise ValueError("Typed payload size metadata is required.")
        if len({cost.row_id for cost in costs}) != len(costs):
            raise ValueError("A physical row must occur once in a payload batch.")
        count = size = inspected_rows = inspected_bytes = 0
        row_limit = min(self.rows_removed, MAX_PURGE_BATCH_ROWS)
        inspection_limit = min(self.rows_inspected, MAX_PURGE_BATCH_ROWS)
        for cost in costs:
            inspect_bytes = cost.payload_bytes * cost.payload_inspections
            if (
                count == row_limit
                or cost.inspection_rows > inspection_limit - inspected_rows
                or cost.payload_bytes > self.bytes_removed - size
                or inspect_bytes > self.bytes_inspected - inspected_bytes
            ):
                break
            count += 1
            size += cost.payload_bytes
            inspected_rows += cost.inspection_rows
            inspected_bytes += inspect_bytes
        if count == 0:
            return ()
        self.rows_inspected -= inspected_rows
        self.rows_removed -= count
        self.bytes_inspected -= inspected_bytes
        self.bytes_removed -= size
        return tuple(cost.row_id for cost in costs[:count])
