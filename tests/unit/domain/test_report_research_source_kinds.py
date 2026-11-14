"""Proof-only research data does not add unsupported source reference kinds."""

import json

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import decode_report_proof, encode_report_proof

from tests.unit.domain.report_factories import uid

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kind", ("research_citation", "research_source_origin", "research_capability_grant")
)
def test_research_proof_rejects_unsupported_source_kind_strings(kind: str) -> None:
    original = r.ReportProof(
        source_references=(
            r.ReportSourceReference(
                key="research.source.selected",
                kind=r.ReportSourceKind.RESEARCH_SOURCE_VERSION,
                subject_id=uid(80),
                content_digest="0" * 64,
            ),
        )
    )
    encoded = encode_report_proof(original)
    assert decode_report_proof(encoded) == original
    payload = json.loads(encoded)
    payload["source_references"][0]["kind"] = kind
    with pytest.raises(DomainError):
        decode_report_proof(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
