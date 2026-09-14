"""Fixed-schema private risk codec with canonical semantic digest verification."""

from hashlib import sha256
from hmac import compare_digest

from .errors import fail_validation
from .historical import historical_digest
from .historical_serialization import historical_canonical_bytes, historical_value_from_json
from .risk_result import RiskCalculation


def canonical_risk_bytes(value: RiskCalculation) -> bytes:
    if not isinstance(value, RiskCalculation):
        fail_validation("A canonical risk result is required.", field="risk")
    return historical_canonical_bytes(value)


def risk_result_digest(value: RiskCalculation) -> str:
    return sha256(canonical_risk_bytes(value)).hexdigest()


def risk_result_from_json(value: str | bytes, *, expected_digest: str) -> RiskCalculation:
    historical_digest(expected_digest, "expected_digest")
    result = historical_value_from_json(value, RiskCalculation)
    if not compare_digest(risk_result_digest(result), expected_digest):
        fail_validation("Risk result does not match its retained digest.", field="digest")
    return result
