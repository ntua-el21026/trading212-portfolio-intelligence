"""Opaque secret-provider boundary; values never stringify or repr in plaintext."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class SecretResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class SecretValue:
    _value: str

    def __post_init__(self) -> None:
        if not self._value:
            raise SecretResolutionError("secret reference resolved to an empty value")

    def __repr__(self) -> str:
        return "SecretValue(redacted=True)"

    def __str__(self) -> str:
        return "[REDACTED]"

    def reveal(self) -> str:
        """Reveal only at the terminal consumer boundary."""
        return self._value


class SecretProvider(Protocol):
    async def resolve(self, reference: str) -> SecretValue: ...


_ENV_REFERENCE = re.compile(r"^env://([A-Z][A-Z0-9_]{0,127})$")


class EnvironmentSecretProvider:
    """Local/test adapter; only explicitly allowlisted variable references resolve."""

    def __init__(
        self,
        *,
        allowed_variables: frozenset[str],
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._allowed = allowed_variables
        self._environment = environment if environment is not None else os.environ

    async def resolve(self, reference: str) -> SecretValue:
        match = _ENV_REFERENCE.fullmatch(reference)
        if match is None or match.group(1) not in self._allowed:
            raise SecretResolutionError("secret reference is not allowed")
        value = self._environment.get(match.group(1))
        if not value:
            raise SecretResolutionError("secret reference is unavailable")
        return SecretValue(value)
