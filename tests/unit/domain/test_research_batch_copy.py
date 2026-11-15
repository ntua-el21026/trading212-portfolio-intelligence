"""Independent frozen-copy parity and eager validation with lazy bounded copying."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from trading212_analytics.xray import calculate_xray
from trading212_application import research as app
from trading212_domain import research_facts as facts
from trading212_domain.errors import DomainError
from trading212_domain.research import MAX_RESEARCH_PAGE
from trading212_domain.research_facts import ResearchPortfolioFacts, ResearchXrayPin
from trading212_domain.research_serialization import research_record_bytes
from trading212_domain.serialization import canonical_json
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import encode_xray_result
from trading212_domain.xray_result import XrayCalculation

from tests.unit.analytics.xray_factories import Builder, uid
from tests.unit.domain.research_copy_reference import legacy_copy_research_portfolio_facts
from tests.unit.domain.test_research_exposure_availability import ENTITY, _known_money, _missing_fx

pytestmark = pytest.mark.unit
BatchCopier = Callable[
    [ResearchXrayPin, XrayCalculation, tuple[UUID, ...]], Iterator[ResearchPortfolioFacts]
]


def _batch() -> BatchCopier:
    candidate = getattr(facts, "copy_research_portfolio_facts_many", None)
    assert callable(candidate), "A fully validated bounded batch copier is required."
    return cast(BatchCopier, candidate)


def _pin(value: XrayCalculation) -> ResearchXrayPin:
    return ResearchXrayPin(
        owner_id=value.owner_id,
        account_id=value.account_id,
        run_id=uid(123),
        snapshot_id=value.snapshot_id,
        input_digest=value.input_digest,
        result_digest=value.content_digest,
        reporting_currency=value.reporting_currency,
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        quality_evaluated_at=value.quality_evaluated_at.value,
        policy_id=value.policy.id,
        policy_version=value.policy.version,
    )


def _calculation(mode: str, fund: bool = False) -> XrayCalculation:
    builder = Builder()
    builder.reporting_currency = CurrencyCode("GBP")
    if mode in {"unknown", "partial"}:
        _missing_fx(builder, fund=fund)
    if mode in {"positive", "zero", "partial"}:
        _known_money(builder, "0" if mode == "zero" else "25")
    for entity in sorted({row.entity_id for row in builder.entities}, key=str):
        builder.classifications_for(entity, key=str(entity))
    return calculate_xray(builder.finish())


@pytest.mark.parametrize(
    ("mode", "fund"),
    [
        ("positive", False),
        ("zero", False),
        ("unknown", False),
        ("unknown", True),
        ("partial", False),
    ],
)
def test_batch_facts_and_previews_equal_frozen_original_complete_bytes(
    mode: str, fund: bool
) -> None:
    value = _calculation(mode, fund)
    pin = _pin(value)
    entities = (ENTITY, uid(999), ENTITY)
    source_before = encode_xray_result(value)
    expected = tuple(
        legacy_copy_research_portfolio_facts(pin, value, entity) for entity in entities
    )
    actual = tuple(_batch()(pin, value, entities))
    assert actual == expected
    assert tuple(map(research_record_bytes, actual)) == tuple(map(research_record_bytes, expected))
    assert canonical_json(tuple(map(app.preview_research_portfolio, actual))) == canonical_json(
        tuple(map(app.preview_research_portfolio, expected))
    )
    assert encode_xray_result(value) == source_before
    assert actual[0] == actual[2] and actual[1].effective_exposure is None
    expected_money = None if mode == "unknown" else Decimal("0" if mode == "zero" else "25")
    assert (
        None if actual[0].effective_exposure is None else actual[0].effective_exposure.amount
    ) == expected_money
    if actual[0].effective_exposure is not None:
        assert actual[0].effective_exposure.currency == CurrencyCode("GBP")


def test_25_distinct_entities_hash_once_upfront_and_copy_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = Builder()
    entities = tuple(uid(5000 + index) for index in range(25))
    for index, entity in enumerate(entities):
        instrument = uid(1000 + index)
        builder.position(instrument, str(index + 1))
        builder.identity(instrument, entity)
        builder.classifications_for(entity, key=str(entity))
    value = calculate_xray(builder.finish())
    pin = _pin(value)
    expected = tuple(
        legacy_copy_research_portfolio_facts(pin, value, entity) for entity in entities
    )
    batch = _batch()
    copier = getattr(facts, "_copy_research_portfolio_facts_from_validated_result", None)
    assert callable(copier)
    digest_property = cast(property, XrayCalculation.content_digest)
    assert digest_property.fget is not None
    counts = {"digests": 0, "copies": 0}

    def digest(calculation: XrayCalculation) -> str:
        counts["digests"] += 1
        assert digest_property.fget is not None
        return cast(str, digest_property.fget(calculation))

    def copied(*args: Any, **kwargs: Any) -> ResearchPortfolioFacts:
        counts["copies"] += 1
        return cast(ResearchPortfolioFacts, copier(*args, **kwargs))

    monkeypatch.setattr(XrayCalculation, "content_digest", property(digest))
    monkeypatch.setattr(facts, "_copy_research_portfolio_facts_from_validated_result", copied)
    pending = batch(pin, value, entities)
    assert iter(pending) is pending
    assert counts == {"digests": 1, "copies": 0}
    for index, reference in enumerate(expected):
        actual = next(pending)
        assert research_record_bytes(actual) == research_record_bytes(reference)
        assert counts == {"digests": 1, "copies": index + 1}
    with pytest.raises(StopIteration):
        next(pending)
    assert counts == {"digests": 1, "copies": 25}


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("owner_id", uid(91)),
        ("account_id", uid(92)),
        ("snapshot_id", uid(93)),
        ("input_digest", "a" * 64),
        ("result_digest", "b" * 64),
        ("reporting_currency", CurrencyCode("USD")),
        ("valuation_at", timedelta(microseconds=1)),
        ("source_cutoff_at", timedelta(microseconds=1)),
        ("quality_evaluated_at", timedelta(microseconds=1)),
        ("policy_id", uid(94)),
        ("policy_version", "different"),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
def test_every_variable_pin_field_rejected_before_iterator_is_returned(
    field: str, changed: Any, empty: bool
) -> None:
    value = _calculation("positive")
    pin = _pin(value)
    if isinstance(changed, timedelta):
        changed = getattr(pin, field) + changed
    wrong = replace(pin, **{field: changed})
    with pytest.raises(DomainError):
        _batch()(wrong, value, () if empty else (ENTITY,))
    with pytest.raises(DomainError):
        facts.copy_research_portfolio_facts(wrong, value, ENTITY)


@pytest.mark.parametrize(
    "invalid",
    [[], [ENTITY], ("not-a-uuid",), (ENTITY,) * (MAX_RESEARCH_PAGE + 1)],
)
def test_batch_rejects_unbounded_or_noncanonical_entity_selection_before_copy(
    invalid: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = _calculation("positive")
    pin = _pin(value)
    batch = _batch()
    digest_property = cast(property, XrayCalculation.content_digest)
    assert digest_property.fget is not None
    hashes = 0

    def digest(calculation: XrayCalculation) -> str:
        nonlocal hashes
        hashes += 1
        assert digest_property.fget is not None
        return cast(str, digest_property.fget(calculation))

    monkeypatch.setattr(XrayCalculation, "content_digest", property(digest))
    with pytest.raises(DomainError):
        batch(pin, value, invalid)
    assert hashes == 0
