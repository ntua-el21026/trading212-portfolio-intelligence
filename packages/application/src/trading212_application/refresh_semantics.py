"""Canonical requested refresh identity shared by every application adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from .ingestion import IngestionCapability, RunMode

REFRESH_REQUEST_SCHEMA_VERSION = 1


class RefreshIdempotencyConflictError(RuntimeError):
    """An account-scoped key is already bound to different request semantics."""


@dataclass(frozen=True, slots=True)
class RefreshRequestSemantics:
    """Requested semantics before any state-dependent initial-sync promotion."""

    owner_id: str
    account_id: str
    mode: RunMode
    capabilities: tuple[IngestionCapability, ...]
    create_snapshot: bool = True
    schema_version: int = REFRESH_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.owner_id or not self.account_id:
            raise ValueError("refresh owner and account identities are required")
        if not self.capabilities or len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("refresh capabilities must be non-empty and unique")
        if self.schema_version != REFRESH_REQUEST_SCHEMA_VERSION:
            raise ValueError("unsupported refresh request schema version")

    @classmethod
    def create(
        cls,
        *,
        owner_id: object,
        account_id: object,
        mode: RunMode,
        capabilities: Sequence[IngestionCapability],
    ) -> RefreshRequestSemantics:
        if not isinstance(mode, RunMode):
            raise ValueError("only typed refresh modes are accepted")
        selected = tuple(capabilities)
        if any(not isinstance(capability, IngestionCapability) for capability in selected):
            raise ValueError("only typed ingestion capabilities are accepted")
        return cls(
            owner_id=str(owner_id),
            account_id=str(account_id),
            mode=mode,
            capabilities=selected,
        )

    @property
    def capability_values(self) -> list[str]:
        return [capability.value for capability in self.capabilities]

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "account_id": self.account_id,
                "create_snapshot": self.create_snapshot,
                "owner_id": self.owner_id,
                "requested_capabilities": self.capability_values,
                "requested_mode": self.mode.value,
                "schema_version": self.schema_version,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
