"""Executable sealed capability registry derived from the frozen YAML contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Final

import yaml

from .errors import CapabilityError

_TICKER_PATTERN: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_ORDER_ID_PATTERN: Final = re.compile(r"^[0-9]{1,19}$")
_EXPECTED_CAPABILITIES: Final = (
    "account_summary",
    "metadata_instruments",
    "metadata_exchanges",
    "portfolio_positions",
    "pending_orders",
    "order_detail",
    "historical_orders",
    "historical_transactions",
    "historical_dividends",
    "historical_exports",
)
_QUERY_FIELDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "account_summary": frozenset(),
        "metadata_instruments": frozenset(),
        "metadata_exchanges": frozenset(),
        "portfolio_positions": frozenset({"ticker"}),
        "pending_orders": frozenset(),
        "order_detail": frozenset(),
        "historical_orders": frozenset({"cursor", "ticker", "limit"}),
        "historical_transactions": frozenset({"cursor", "time", "limit"}),
        "historical_dividends": frozenset({"cursor", "ticker", "limit"}),
        "historical_exports": frozenset(),
    }
)


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    path_template: str

    def resolve_path(self, *, order_id: str | None = None) -> str:
        if "{order_id}" not in self.path_template:
            if order_id is not None:
                raise CapabilityError(f"{self.name} does not accept a path identifier")
            return self.path_template
        if order_id is None or not _ORDER_ID_PATTERN.fullmatch(order_id):
            raise CapabilityError("order identifier must be a positive provider int64 string")
        if int(order_id) > 9_223_372_036_854_775_807:
            raise CapabilityError("order identifier exceeds provider int64 range")
        return self.path_template.replace("{order_id}", order_id)

    def normalize_query(self, values: Mapping[str, object] | None = None) -> dict[str, str]:
        supplied = dict(values or {})
        unknown = set(supplied) - _QUERY_FIELDS[self.name]
        if unknown:
            raise CapabilityError(f"unsupported query fields for {self.name}: {sorted(unknown)!r}")
        result: dict[str, str] = {}
        for key, value in supplied.items():
            if value is None:
                continue
            if key == "limit":
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 50:
                    raise CapabilityError("page limit must be an integer from 1 through 50")
                result[key] = str(value)
            elif key == "ticker":
                if not isinstance(value, str) or not _TICKER_PATTERN.fullmatch(value):
                    raise CapabilityError("ticker contains unsupported characters")
                result[key] = value
            elif key == "cursor" and self.name != "historical_transactions":
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise CapabilityError("cursor must be a non-negative provider integer")
                result[key] = str(value)
            elif key == "cursor":
                if not isinstance(value, str) or not value or len(value) > 512:
                    raise CapabilityError("transaction cursor must be a bounded opaque string")
                result[key] = value
            elif key == "time":
                if (
                    not isinstance(value, datetime)
                    or value.tzinfo is None
                    or value.utcoffset() is None
                ):
                    raise CapabilityError("transaction time must be timezone-aware")
                result[key] = value.astimezone(UTC).isoformat()
            else:  # pragma: no cover - registry and unknown-field checks make this unreachable
                raise CapabilityError(f"unsupported query field: {key}")
        return result


def _contract_path() -> Path:
    checkout_contract = (
        Path(__file__).resolve().parents[4] / "config/contracts/trading212-read-allowlist.yaml"
    )
    if checkout_contract.is_file():
        return checkout_contract
    packaged = files("trading212_provider").joinpath("contracts/trading212-read-allowlist.yaml")
    return Path(str(packaged))


def load_capability_registry(path: Path | None = None) -> Mapping[str, Capability]:
    payload = yaml.safe_load((path or _contract_path()).read_text(encoding="utf-8"))
    if payload.get("default_environment") != "demo":
        raise CapabilityError("Trading 212 allowlist must default to Demo")
    if payload.get("policy") != {
        "default_deny": True,
        "arbitrary_urls": False,
        "automatic_path_discovery": False,
        "redirects": False,
        "demo_by_default": True,
        "live_requires_explicit_configuration": True,
    }:
        raise CapabilityError("Trading 212 allowlist policy is not fail-closed")
    entries = payload.get("capabilities")
    if not isinstance(entries, list) or len(entries) != len(_EXPECTED_CAPABILITIES):
        raise CapabilityError("Trading 212 allowlist must contain exactly ten capabilities")
    registry: dict[str, Capability] = {}
    for entry in entries:
        name = entry.get("capability")
        method = entry.get("method")
        path_template = entry.get("path")
        if name not in _EXPECTED_CAPABILITIES or name in registry:
            raise CapabilityError(
                "Trading 212 allowlist contains an unknown or duplicate capability"
            )
        if method != "GET":
            raise CapabilityError("Trading 212 allowlist contains a non-read method")
        if not isinstance(path_template, str) or not path_template.startswith("/equity/"):
            raise CapabilityError("Trading 212 allowlist contains an invalid path")
        registry[name] = Capability(name=name, path_template=path_template)
    if tuple(registry) != _EXPECTED_CAPABILITIES:
        raise CapabilityError("Trading 212 capability order or membership drifted")
    return MappingProxyType(registry)


CAPABILITIES: Final = load_capability_registry()
