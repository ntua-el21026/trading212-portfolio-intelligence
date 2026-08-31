"""Terminal adapter from opaque secret references to Trading 212 credentials."""

from __future__ import annotations

import json
from collections.abc import Sequence

from trading212_provider.configuration import BrokerEnvironment
from trading212_provider.credentials import Trading212Credentials
from trading212_security.secrets import SecretProvider, SecretResolutionError


def _reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SecretResolutionError("credential bundle has an invalid shape")
        result[key] = value
    return result


class SecretReferenceCredentialProvider:
    """Resolve a strict JSON credential bundle only at outbound dispatch time."""

    def __init__(self, secret_provider: SecretProvider) -> None:
        self._secrets = secret_provider

    async def resolve_trading212(
        self,
        *,
        credential_reference: str,
        environment: BrokerEnvironment,
    ) -> Trading212Credentials:
        bundle = await self._secrets.resolve(credential_reference)
        try:
            payload = json.loads(bundle.reveal(), object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise SecretResolutionError("credential bundle is not valid JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"api_key", "api_secret"}:
            raise SecretResolutionError("credential bundle has an invalid shape")
        api_key = payload["api_key"]
        api_secret = payload["api_secret"]
        if not isinstance(api_key, str) or not isinstance(api_secret, str):
            raise SecretResolutionError("credential bundle fields are invalid")
        return Trading212Credentials(
            api_key=api_key,
            api_secret=api_secret,
            environment=environment,
        )
