"""Validate a complete typed provider chain before opening an ingestion transaction."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from trading212_application.source_providers import (
    ClassificationPage,
    ClassificationRequest,
    ConstituentPage,
    ConstituentRequest,
)
from trading212_domain.errors import fail_validation
from trading212_domain.serialization import canonical_json
from trading212_domain.source_details import ClassificationObservation, ConstituentHolding
from trading212_domain.sources import MAX_SOURCE_PAGES, SourceProvenance, source_tuple


@dataclass(frozen=True, slots=True)
class ClassificationBatch:
    request: ClassificationRequest
    provenance: SourceProvenance
    observations: tuple[ClassificationObservation, ...]
    request_digest: str
    economic_digest: str


@dataclass(frozen=True, slots=True)
class ConstituentBatch:
    request: ConstituentRequest
    header: ConstituentPage
    holdings: tuple[ConstituentHolding, ...]
    request_digest: str
    economic_digest: str


def _digest(value: object) -> str:
    payload = canonical_json(value).encode("utf-8")
    if len(payload) > 33_554_432:
        fail_validation("The complete enrichment source exceeds its byte bound.", field="pages")
    return hashlib.sha256(payload).hexdigest()


def _provenance(value: SourceProvenance) -> tuple[object, ...]:
    # Provider-reported retrieval time is not trusted store first knowledge.
    return (
        value.provider_id,
        value.license_version_id,
        value.adapter_version,
        value.schema_version,
        value.source_revision,
        value.revision_order,
        value.effective_at,
        value.synthetic,
    )


def _chain(
    request: ClassificationRequest | ConstituentRequest,
    pages: tuple[ClassificationPage | ConstituentPage, ...],
) -> SourceProvenance:
    if request.continuation is not None or not pages:
        fail_validation("Ingestion requires a complete initial page chain.", field="pages")
    token: str | None = None
    seen: set[str] = set()
    first = pages[0].provenance
    for ordinal, page in enumerate(pages):
        if page.request != replace(request, continuation=token):
            fail_validation("The provider page does not echo its exact request.", field="request")
        if _provenance(page.provenance) != _provenance(first):
            fail_validation("Provider provenance changed within a page chain.", field="provenance")
        if page.provenance.effective_at > request.source_cutoff_at:
            fail_validation(
                "The provider source follows the requested cutoff.", field="effective_at"
            )
        token = page.continuation
        if token is None:
            if ordinal != len(pages) - 1:
                fail_validation("A completed chain cannot contain more pages.", field="pages")
        elif token in seen:
            fail_validation("The provider continuation chain repeats.", field="continuation")
        else:
            seen.add(token)
    if token is not None:
        fail_validation("The provider continuation chain is incomplete.", field="continuation")
    return first


def classifications(
    request: ClassificationRequest,
    pages: tuple[ClassificationPage, ...],
) -> ClassificationBatch:
    if not isinstance(request, ClassificationRequest):
        fail_validation("A typed classification request is required.", field="request")
    source_tuple(pages, ClassificationPage, "pages", MAX_SOURCE_PAGES)
    provenance = _chain(request, pages)
    if sum(len(page.observations) for page in pages) > 100_000:
        fail_validation("The classification row bound was exceeded.", field="observations")
    rows = tuple(sorted((row for page in pages for row in page.observations), key=canonical_json))
    keys = tuple(canonical_json(row) for row in rows)
    if len(set(keys)) != len(keys):
        fail_validation("The classification chain contains duplicate rows.", field="observations")
    # The cutoff controls retrieval, not immutable source identity or first knowledge.
    identity = (tuple(sorted(request.instrument_ids)), request.taxonomy, request.taxonomy_version)
    return ClassificationBatch(
        request,
        provenance,
        rows,
        _digest(identity),
        _digest((identity, _provenance(provenance), rows)),
    )


def constituents(
    request: ConstituentRequest,
    pages: tuple[ConstituentPage, ...],
) -> ConstituentBatch:
    if not isinstance(request, ConstituentRequest):
        fail_validation("A typed constituent request is required.", field="request")
    source_tuple(pages, ConstituentPage, "pages", MAX_SOURCE_PAGES)
    provenance = _chain(request, pages)
    header = pages[0]
    metadata = (
        header.effective_at,
        header.stated_coverage,
        header.unresolved_weight,
        header.cash_weight,
    )
    for page in pages:
        if (
            page.effective_at,
            page.stated_coverage,
            page.unresolved_weight,
            page.cash_weight,
        ) != metadata:
            fail_validation("Constituent headers changed within a page chain.", field="pages")
    if header.effective_at != provenance.effective_at:
        fail_validation("Constituent source dates disagree.", field="effective_at")
    if sum(len(page.holdings) for page in pages) > 100_000:
        fail_validation("The constituent row bound was exceeded.", field="holdings")
    rows = tuple(
        sorted((row for page in pages for row in page.holdings), key=lambda row: row.source_key)
    )
    if len({row.source_key for row in rows}) != len(rows):
        fail_validation("Constituent source keys repeat across pages.", field="holdings")
    identity = (request.fund_series_id, header.effective_at)
    return ConstituentBatch(
        request,
        header,
        rows,
        _digest(identity),
        _digest((identity, _provenance(provenance), metadata, rows)),
    )
