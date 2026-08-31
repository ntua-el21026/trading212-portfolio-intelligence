#!/usr/bin/env python3
"""Opt-in, sanitized Trading 212 Demo connectivity smoke.

The probe has no Live execution path and accepts credentials only through the
strict JSON bundle named by ``CREDENTIAL_BUNDLE_VARIABLE``. It deliberately
prints no portfolio values, provider identifiers, response bodies,
request-specific URLs, or credential-derived material.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import cast

from trading212_provider import (
    BrokerEnvironment,
    ProviderError,
    StaticCredentialProvider,
    Trading212Client,
    Trading212Credentials,
    Trading212Settings,
)

CREDENTIAL_BUNDLE_VARIABLE = "T212PI_TRADING212_CREDENTIAL_BUNDLE"
EXECUTION_GATE_VARIABLE = "T212PI_RUN_TRADING212_DEMO_SMOKE"
PROVIDER_ENVIRONMENT_VARIABLE = "T212PI_TRADING212_ENVIRONMENT"
LIVE_GATE_VARIABLE = "T212PI_TRADING212_LIVE_ENABLED"


class DemoSmokeConfigurationError(RuntimeError):
    """Sanitized configuration failure raised before provider transport."""


@dataclass(frozen=True, slots=True)
class CapabilityCheck:
    capability: str
    status_code: int
    observed_at: str
    record_count: int
    rate_limit_observed: bool


@dataclass(frozen=True, slots=True)
class DemoSmokeResult:
    result: str
    environment: str
    origin: str
    checks: tuple[CapabilityCheck, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "checks": [asdict(check) for check in self.checks],
            "environment": self.environment,
            "origin": self.origin,
            "result": self.result,
        }


def _reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DemoSmokeConfigurationError("credential bundle has an invalid shape")
        result[key] = value
    return result


def _credentials_from_environment(environment: Mapping[str, str]) -> Trading212Credentials:
    raw_bundle = environment.get(CREDENTIAL_BUNDLE_VARIABLE)
    if not raw_bundle:
        raise DemoSmokeConfigurationError("credential bundle is unavailable")
    try:
        decoded = json.loads(raw_bundle, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DemoSmokeConfigurationError("credential bundle is not valid JSON") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"api_key", "api_secret"}:
        raise DemoSmokeConfigurationError("credential bundle has an invalid shape")
    payload = cast(dict[str, object], decoded)
    api_key = payload["api_key"]
    api_secret = payload["api_secret"]
    if not isinstance(api_key, str) or not isinstance(api_secret, str):
        raise DemoSmokeConfigurationError("credential bundle fields are invalid")
    return Trading212Credentials(
        api_key=api_key,
        api_secret=api_secret,
        environment=BrokerEnvironment.DEMO,
    )


def _assert_demo_only(environment: Mapping[str, str]) -> None:
    selected = environment.get(PROVIDER_ENVIRONMENT_VARIABLE, "demo").strip().casefold()
    live_enabled = environment.get(LIVE_GATE_VARIABLE, "false").strip().casefold()
    if selected != "demo" or live_enabled not in {"", "0", "false", "no", "off"}:
        raise DemoSmokeConfigurationError("the Demo smoke refuses non-Demo configuration")


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def run_demo_smoke(
    *,
    environment: Mapping[str, str] | None = None,
) -> DemoSmokeResult:
    """Execute exactly two allowlisted Demo GETs and return sanitized evidence."""
    values = environment if environment is not None else os.environ
    _assert_demo_only(values)
    credentials = _credentials_from_environment(values)
    settings = Trading212Settings(
        environment=BrokerEnvironment.DEMO,
        live_mode_explicitly_enabled=False,
        max_attempts=1,
    )
    async with Trading212Client(
        settings=settings,
        credential_provider=StaticCredentialProvider(credentials),
        credential_reference="env://T212PI_TRADING212_CREDENTIAL_BUNDLE",
    ) as client:
        account = await client.get_account_summary()
        positions = await client.get_positions()

    return DemoSmokeResult(
        result="passed",
        environment="demo",
        origin=settings.base_url.removesuffix("/api/v0"),
        checks=(
            CapabilityCheck(
                capability="account_summary",
                status_code=account.status_code,
                observed_at=_isoformat(account.observed_at),
                record_count=1,
                rate_limit_observed=account.rate_limit is not None,
            ),
            CapabilityCheck(
                capability="portfolio_positions",
                status_code=positions.status_code,
                observed_at=_isoformat(positions.observed_at),
                record_count=len(positions.data),
                rate_limit_observed=positions.rate_limit is not None,
            ),
        ),
    )


def _emit(payload: Mapping[str, object]) -> None:
    print(json.dumps(dict(payload), separators=(",", ":"), sort_keys=True))


def main(environment: Mapping[str, str] | None = None) -> int:
    """Run only after explicit opt-in; all failures are intentionally sanitized."""
    values = environment if environment is not None else os.environ
    if values.get(EXECUTION_GATE_VARIABLE) != "1":
        _emit(
            {
                "environment": "demo",
                "reason": "explicit Demo smoke opt-in is not enabled",
                "result": "blocked_external",
            }
        )
        return 2
    try:
        result = asyncio.run(run_demo_smoke(environment=values))
    except DemoSmokeConfigurationError:
        _emit({"environment": "demo", "failure_category": "configuration", "result": "failed"})
        return 2
    except ProviderError as exc:
        _emit(
            {
                "environment": "demo",
                "failure_category": exc.kind.value,
                "result": "failed",
            }
        )
        return 1
    except Exception:
        _emit({"environment": "demo", "failure_category": "internal", "result": "failed"})
        return 1
    _emit(result.public_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
