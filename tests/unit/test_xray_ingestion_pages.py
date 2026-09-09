"""Complete source identity survives repagination; malformed provider chains fail closed."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_application.source_providers import (
    ClassificationPage,
    ClassificationRequest,
    ConstituentPage,
    ConstituentRequest,
)
from trading212_domain.errors import DomainError
from trading212_domain.source_details import (
    ClassificationDimension,
    ClassificationObservation,
    ConstituentHolding,
    ConstituentState,
)
from trading212_domain.sources import SourceProvenance
from trading212_domain.values import CurrencyCode
from trading212_persistence.xray_ingestion_pages import classifications, constituents

AT = datetime(2026, 9, 1, tzinfo=UTC)


def identity(value: int) -> str:
    return str(UUID(int=value))


def provenance() -> SourceProvenance:
    return SourceProvenance(
        provider_id=identity(1),
        license_version_id=identity(2),
        adapter_version="test_v1",
        schema_version="1",
        source_revision="r1",
        revision_order=1,
        effective_at=AT,
        first_observed_at=AT + timedelta(hours=1),
        synthetic=True,
    )


def request() -> ConstituentRequest:
    return ConstituentRequest(
        fund_series_id=identity(3), effective_at=AT, source_cutoff_at=AT + timedelta(days=2)
    )


def holding(key: str) -> ConstituentHolding:
    return ConstituentHolding(
        source_key=key,
        weight=Decimal("0.5"),
        state=ConstituentState.RESOLVED,
        currency=CurrencyCode("EUR"),
        entity_id=identity(4),
        evidence_key="issuer_statement",
    )


def page(
    req: ConstituentRequest, keys: tuple[str, ...], continuation: str | None = None
) -> ConstituentPage:
    return ConstituentPage(
        request=req,
        provenance=provenance(),
        effective_at=AT,
        holdings=tuple(holding(key) for key in keys),
        stated_coverage=Decimal("1"),
        unresolved_weight=Decimal("0"),
        cash_weight=Decimal("0"),
        continuation=continuation,
    )


def test_complete_source_digest_is_independent_of_page_layout_and_provider_receipt_time() -> None:
    req = request()
    one = constituents(req, (page(req, ("b", "a")),))
    first = page(req, ("a",), "next")
    second = page(replace(req, continuation="next"), ("b",))
    second = replace(
        second, provenance=replace(second.provenance, first_observed_at=AT + timedelta(days=1))
    )
    two = constituents(req, (first, second))
    assert one.economic_digest == two.economic_digest
    assert one.holdings == two.holdings
    assert one.holdings[0].entity_id == identity(4)
    assert one.holdings[0].instrument_id is None
    assert one.holdings[0].currency == CurrencyCode("EUR")


def test_later_retrieval_cutoff_does_not_create_a_new_economic_source() -> None:
    req = request()
    later = replace(req, source_cutoff_at=req.source_cutoff_at + timedelta(days=1))
    assert (
        constituents(req, (page(req, ("a", "b")),)).economic_digest
        == constituents(
            later,
            (page(later, ("a", "b")),),
        ).economic_digest
    )


def test_changed_rate_free_constituent_economics_change_digest() -> None:
    req = request()
    original = page(req, ("a", "b"))
    changed = replace(
        original,
        holdings=(replace(original.holdings[0], entity_id=identity(5)), original.holdings[1]),
    )
    assert (
        constituents(req, (original,)).economic_digest
        != constituents(req, (changed,)).economic_digest
    )


@pytest.mark.parametrize(
    "case",
    [
        "incomplete",
        "early_end",
        "duplicate_key",
        "wrong_request",
        "changed_header",
        "changed_provenance",
        "repeated_token",
    ],
)
def test_incomplete_or_inconsistent_constituent_chains_fail(case: str) -> None:
    req = request()
    first = page(req, ("a",), "next")
    second = page(replace(req, continuation="next"), ("b",))
    pages: tuple[ConstituentPage, ...]
    if case == "incomplete":
        pages = (first,)
    elif case == "early_end":
        pages = (replace(first, continuation=None), second)
    elif case == "duplicate_key":
        pages = (first, replace(second, holdings=first.holdings))
    elif case == "wrong_request":
        pages = (
            first,
            replace(second, request=replace(second.request, fund_series_id=identity(99))),
        )
    elif case == "changed_header":
        pages = (
            first,
            replace(second, stated_coverage=Decimal("0.9"), unresolved_weight=Decimal("0.1")),
        )
    elif case == "changed_provenance":
        pages = (
            first,
            replace(second, provenance=replace(second.provenance, source_revision="r2")),
        )
    else:
        pages = (first, replace(second, continuation="next"))
    with pytest.raises(DomainError):
        constituents(req, pages)


def test_complete_chain_cannot_start_at_a_continuation() -> None:
    req = replace(request(), continuation="next")
    with pytest.raises(DomainError):
        constituents(req, (page(req, ("a", "b")),))


def test_classification_conflict_is_retained_but_duplicate_page_row_is_rejected() -> None:
    req = ClassificationRequest(
        instrument_ids=(identity(4),),
        taxonomy="gics",
        taxonomy_version="2026",
        source_cutoff_at=AT + timedelta(days=2),
    )
    observation = ClassificationObservation(
        instrument_id=identity(4),
        dimension=ClassificationDimension.SECTOR,
        taxonomy="gics",
        taxonomy_version="2026",
        category="technology",
        evidence_key="statement",
        valid_from=AT,
        valid_to=None,
        confidence=Decimal("0.9"),
    )
    other = replace(observation, category="industrials", evidence_key="other_statement")
    first = ClassificationPage(
        request=req, provenance=provenance(), observations=(observation,), continuation="next"
    )
    second = ClassificationPage(
        request=replace(req, continuation="next"), provenance=provenance(), observations=(other,)
    )
    retained = classifications(req, (first, second))
    assert {row.category for row in retained.observations} == {"technology", "industrials"}
    with pytest.raises(DomainError):
        classifications(req, (first, replace(second, observations=(observation,))))
