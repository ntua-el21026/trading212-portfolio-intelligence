import traceback
from dataclasses import replace

import pytest
from trading212_application.source_providers import (
    PriceHistoryRequest,
    SourceCapability,
    SourceFailure,
    SourceProviderError,
)
from trading212_domain import DomainError, canonical_json
from trading212_domain.sources import source_snapshot_digest

from tests.unit.analytics.source_factories import AT, calendar, price

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "field",
    [
        "source_revision",
        "adapter_version",
        "provider_key",
        "continuation",
        "failure",
        "timezone",
        "uuid",
    ],
)
def test_signed_provider_urls_never_enter_canonical_source_records_or_safe_errors(
    field: str,
) -> None:
    marker = "_".join(("SOURCE", "URL", "CANARY"))
    hostile = "https://" + ".".join(("signed", "source", "invalid")) + "/data?token=" + marker
    original = price()
    try:
        if field == "source_revision":
            replace(original.provenance, source_revision=hostile)
        elif field == "adapter_version":
            replace(original.provenance, adapter_version=hostile)
        elif field == "provider_key":
            replace(original.series, provider_key=hostile)
        elif field == "timezone":
            replace(calendar(), timezone=hostile)
        elif field == "uuid":
            replace(original, id=marker.ljust(32, "Z"))
        elif field == "continuation":
            PriceHistoryRequest(
                series=original.series,
                period=original.period,
                source_cutoff_at=AT,
                continuation=hostile,
            )
        else:
            SourceFailure(
                code=SourceProviderError.INVALID_SCHEMA,
                capability=SourceCapability.PRICE_HISTORY,
                provider_key=hostile,
            )
    except DomainError as error:
        formatted = "".join(traceback.format_exception(error))
        assert marker not in formatted and hostile not in formatted
        assert marker not in str(error) and hostile not in repr(error)
    else:
        pytest.fail("The hostile provider value crossed the canonical boundary.")
    assert marker not in canonical_json(original)
    assert source_snapshot_digest(original) == source_snapshot_digest(price())


def test_failure_record_has_only_closed_safe_fields() -> None:
    result = SourceFailure(
        code=SourceProviderError.NOT_CONFIGURED,
        capability=SourceCapability.BENCHMARK_SERIES,
        provider_key="unconfigured-reference-provider",
    )
    assert not result.retryable
    assert canonical_json(result) == (
        '{"capability":"benchmark_series","code":"not_configured","correlation_id":null,'
        '"provider_key":"unconfigured-reference-provider","retry_after_seconds":null,'
        '"retryable":false}'
    )
    with pytest.raises(TypeError):
        SourceFailure(
            code=SourceProviderError.INVALID_SCHEMA,
            capability=SourceCapability.PRICE_HISTORY,
            provider_key="synthetic",
            raw_payload="untrusted",
        )  # type: ignore[call-arg]
