from __future__ import annotations

import logging

import pytest
from trading212_security.redaction import RedactingLogFilter, Redactor
from trading212_security.secrets import EnvironmentSecretProvider, SecretResolutionError

CANARY = "CANARY-SECRET-NEVER-EMIT"


@pytest.mark.asyncio
async def test_environment_provider_resolves_only_allowlisted_references() -> None:
    provider = EnvironmentSecretProvider(
        allowed_variables=frozenset({"T212_DEMO_SECRET"}),
        environment={"T212_DEMO_SECRET": CANARY, "UNRELATED": "private"},
    )
    value = await provider.resolve("env://T212_DEMO_SECRET")
    assert value.reveal() == CANARY
    assert CANARY not in repr(value)
    assert CANARY not in str(value)
    with pytest.raises(SecretResolutionError, match="not allowed"):
        await provider.resolve("env://UNRELATED")


def test_structured_and_text_redaction_removes_canaries_and_auth_headers() -> None:
    redactor = Redactor(canaries=(CANARY,))
    safe = redactor.value(
        {
            "api_key": "key-value",
            "nested": {"password": CANARY},
            "message": f"Authorization: Bearer token-value and {CANARY}",
        }
    )
    rendered = repr(safe)
    assert CANARY not in rendered
    assert "key-value" not in rendered
    assert "token-value" not in rendered
    assert rendered.count("[REDACTED]") >= 3


def test_log_filter_redacts_message_arguments_and_extra_fields() -> None:
    redactor = Redactor(canaries=(CANARY,))
    record = logging.LogRecord(
        "security-test",
        logging.INFO,
        __file__,
        1,
        "failure %s",
        (CANARY,),
        None,
    )
    record.authorization = f"Basic {CANARY}"
    assert RedactingLogFilter(redactor).filter(record) is True
    assert CANARY not in record.getMessage()
    assert CANARY not in str(record.__dict__["authorization"])
