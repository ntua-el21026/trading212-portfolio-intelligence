"""Small synthetic canonical result shared by risk transport tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from uuid import UUID

from trading212_analytics.risk import calculate_risk
from trading212_application import risk as app
from trading212_domain.risk_serialization import canonical_risk_bytes
from trading212_persistence.risk_service import public_risk_result

from tests.unit.worker.test_risk_process import inputs

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
ACCOUNT = UUID("d778f930-9d2e-4f47-b24f-5b1fa99c6eee")
DEFINITION = UUID("45f8f732-2e9d-4ca2-a811-21671202a683")
VERSION = UUID("b8532ba7-36e4-43ef-aee4-a4e67c75ef9d")
RUN = UUID("e42d5fa3-cd19-44ea-890a-e892845b685a")
SNAPSHOT = UUID("7b1e8b1a-7f75-421e-ab99-9d5e916dbd0a")
JOB = UUID("7275a07e-4c56-4cac-b617-535e9940e26d")


def definition() -> app.RiskDefinitionView:
    return app.RiskDefinitionView(
        id=DEFINITION,
        account_id=ACCOUNT,
        name="Risk",
        revision=1,
        archived=False,
        current_version_id=VERSION,
        created_at=NOW,
        updated_at=NOW,
    )


def version() -> app.RiskVersionView:
    return app.RiskVersionView(
        id=VERSION,
        account_id=ACCOUNT,
        definition_id=DEFINITION,
        version_number=1,
        predecessor_id=None,
        content=inputs().definition,
        content_digest="a" * 64,
        created_at=NOW,
    )


@lru_cache(maxsize=1)
def run() -> app.RiskRunView:
    value = inputs()
    result = calculate_risk(value.historical, value.definition)
    public = public_risk_result(result, sha256(canonical_risk_bytes(result)).hexdigest())
    return app.RiskRunView(
        id=RUN,
        account_id=UUID(value.historical.account_id),
        definition_version_id=VERSION,
        portfolio_snapshot_id=SNAPSHOT,
        historical_input_snapshot_id=SNAPSHOT,
        xray_run_id=None,
        job_id=JOB,
        state=app.PremiumJobState.SUCCEEDED,
        failure_code=None,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        completed_at=NOW,
        input_digest="b" * 64,
        result=public,
        result_availability="available",
    )


def queued() -> app.RiskRunView:
    return replace(
        run(),
        state=app.PremiumJobState.QUEUED,
        completed_at=None,
        result=None,
        result_availability="pending",
    )


def matrix() -> app.RiskMatrixView:
    value = run()
    assert value.result is not None
    result = value.result
    return app.RiskMatrixView(
        run_id=value.id,
        account_id=value.account_id,
        definition_version_id=value.definition_version_id,
        definition=result.definition,
        historical_context=result.historical_context,
        omitted_sources=result.omitted_sources,
        omitted_warnings=result.omitted_warnings,
        content_digest=result.content_digest,
        numerical_profile=result.numerical_profile,
        matrix=result.matrix,
    )
