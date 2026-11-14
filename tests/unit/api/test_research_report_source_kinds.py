"""Only actual typed research source references enter the closed profile-three DTO."""

import pytest
from pydantic import ValidationError
from trading212_api_contracts.premium_reports_v3 import PremiumReportSourceReferenceV3

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kind",
    ("research_citation", "research_source_origin", "research_capability_grant"),
)
def test_unused_research_source_kinds_are_rejected_without_changing_reference_shape(
    kind: str,
) -> None:
    reference = {
        "key": "research_source",
        "kind": "research_source_version",
        "subject_id": "00000000-0000-4000-8000-000000000001",
        "content_digest": "a" * 64,
        "parent_id": None,
        "source_at": None,
        "first_observed_at": None,
        "provider_id": None,
        "license_version_id": None,
        "mapping_version_id": None,
    }
    assert (
        PremiumReportSourceReferenceV3.model_validate(reference).kind == "research_source_version"
    )
    with pytest.raises(ValidationError) as raised:
        PremiumReportSourceReferenceV3.model_validate({**reference, "kind": kind})
    assert [(error["loc"], error["type"]) for error in raised.value.errors()] == [
        (("kind",), "literal_error")
    ]
