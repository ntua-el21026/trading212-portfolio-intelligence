from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from trading212_application.targets import (
    CreateTargetVersionCommand,
    CreateVirtualPortfolioCommand,
    ReplaceTargetDraftCommand,
    TargetPageQuery,
    TargetServiceError,
    TargetServiceErrorCode,
    TargetVersionQuery,
    UpdateVirtualPortfolioCommand,
    ValidateTargetCommand,
    VirtualPortfolioQuery,
    require_target_revision,
    target_etag,
    validate_target_idempotency_key,
)
from trading212_domain import CurrencyCode, DomainError, canonical_json, exact_decimal
from trading212_domain.targets import (
    TargetCatalog,
    TargetConstraint,
    TargetConstraintKind,
    TargetContent,
    TargetExclusion,
    TargetHoldingMapping,
    TargetIdentifier,
    TargetIdentifierKind,
    TargetInstrumentReference,
    TargetIssueSeverity,
    TargetListingReference,
    TargetMappingState,
    TargetNode,
    TargetNodeKind,
    compare_target_content,
    target_content_digest,
    validate_target_content,
)

pytestmark = pytest.mark.unit
EUR = CurrencyCode("EUR")
AS_OF = datetime(2026, 9, 7, tzinfo=UTC)
INSTRUMENT = UUID(int=1)
SECOND_INSTRUMENT = UUID(int=2)
LISTING = UUID(int=3)
SECOND_LISTING = UUID(int=4)
OTHER_LISTING = UUID(int=5)
ENTITY = UUID(int=6)
CATALOG = TargetCatalog(
    (TargetInstrumentReference(INSTRUMENT, ENTITY), TargetInstrumentReference(SECOND_INSTRUMENT)),
    (
        TargetListingReference(LISTING, INSTRUMENT),
        TargetListingReference(SECOND_LISTING, INSTRUMENT),
        TargetListingReference(OTHER_LISTING, SECOND_INSTRUMENT),
    ),
)


def holding(
    key: str = "stock",
    weight: str = "1",
    *,
    parent: str | None = None,
    order: int = 0,
    instrument: UUID = INSTRUMENT,
    listing: UUID | None = None,
) -> TargetNode:
    return TargetNode(
        key,
        parent,
        TargetNodeKind.HOLDING,
        key,
        order,
        Decimal(weight),
        TargetHoldingMapping(TargetMappingState.RESOLVED, instrument, listing),
    )


def group(key: str, weight: str, *, parent: str | None = None, order: int = 0) -> TargetNode:
    return TargetNode(key, parent, TargetNodeKind.GROUP, key, order, Decimal(weight))


def cash(
    key: str = "cash", weight: str = "1", *, parent: str | None = None, order: int = 0
) -> TargetNode:
    return TargetNode(key, parent, TargetNodeKind.CASH, key, order, Decimal(weight))


def validate(content: TargetContent, *, normalize: bool = False):  # type: ignore[no-untyped-def]
    return validate_target_content(
        content, reporting_currency=EUR, effective_at=AS_OF, catalog=CATALOG, normalize=normalize
    )


def codes(content: TargetContent) -> set[str]:
    return {issue.code for issue in validate(content).issues}


def test_hierarchy_products_and_depth_first_order() -> None:
    result = validate(
        TargetContent(
            (
                holding("b", "0.75", parent="group", order=1, instrument=SECOND_INSTRUMENT),
                cash(weight="0.4", order=1),
                group("group", "0.6"),
                holding("a", "0.25", parent="group"),
            )
        )
    )
    assert result.valid
    assert [item.node.key for item in result.flattened_nodes] == ["group", "a", "b", "cash"]
    assert [item.depth for item in result.flattened_nodes] == [1, 2, 2, 1]
    assert [item.effective_weight for item in result.flattened_nodes] == [
        Decimal("0.6"),
        Decimal("0.15"),
        Decimal("0.45"),
        Decimal("0.4"),
    ]
    assert result.flattened_nodes[1].path_factors == (Decimal("0.6"), Decimal("0.25"))
    assert result.effective_weight_rounding_residual == 0
    assert '"effective_weight":"0.15"' in canonical_json(result)


def test_opt_in_normalization_retains_originals_and_deterministic_remainder_tie() -> None:
    content = TargetContent(
        (
            holding("a", "0.333333333333333333"),
            holding("b", "0.333333333333333333", order=1, instrument=SECOND_INSTRUMENT),
            cash(weight="0.333333333333333333", order=2),
        )
    )
    assert "sibling_sum_invalid" in codes(content)
    result = validate(content, normalize=True)
    assert result.valid
    weights = {node.key: node.weight for node in result.content.nodes}
    assert weights["a"] == Decimal("0.333333333333333334")
    assert sum(weights.values()) == 1
    assert result.input_digest != result.result_digest
    assert len(result.adjustments) == 3
    assert result.adjustments[0].original_sibling_sum == Decimal("0.999999999999999999")
    assert result.adjustments[0].original_weight == Decimal("0.333333333333333333")
    assert result.adjustments[0].remainder_rank == 0
    replay = validate(result.content, normalize=True)
    assert replay.valid and replay.adjustments == ()
    assert replay.input_digest == result.result_digest == replay.result_digest


@pytest.mark.parametrize("weight", ["0", "0.99", "-0.1", "1.1"])
def test_materially_invalid_weights_never_normalize(weight: str) -> None:
    result = validate(TargetContent((cash(weight=weight),)), normalize=True)
    assert not result.valid
    assert result.adjustments == ()
    assert result.content.nodes[0].weight == Decimal(weight)


def test_tree_errors_are_structured_and_do_not_recurse_indefinitely() -> None:
    assert "empty_tree" in codes(TargetContent(()))
    assert "missing_parent" in codes(TargetContent((holding(parent="absent"),)))
    assert "cycle_detected" in codes(
        TargetContent((group("a", "1", parent="b"), group("b", "1", parent="a")))
    )
    assert "duplicate_node_key" in codes(TargetContent((holding(), holding())))
    assert "duplicate_sibling_order" in codes(
        TargetContent((holding(weight="0.5"), cash(weight="0.5")))
    )
    assert "invalid_node_children" in codes(TargetContent((group("empty", "1"),)))
    assert "invalid_node_children" in codes(TargetContent((holding(), cash(parent="stock"))))
    assert "nested_cash_target" in codes(TargetContent((group("g", "1"), cash(parent="g"))))
    assert "multiple_cash_targets" in codes(
        TargetContent((cash("a", "0.5"), cash("b", "0.5", order=1)))
    )


def test_eight_factors_allowed_nine_rejected() -> None:
    nodes = tuple(
        group(f"g{depth}", "1", parent=f"g{depth - 1}" if depth else None) for depth in range(7)
    )
    assert validate(TargetContent((*nodes, holding(parent="g6")))).valid
    deeper = (*nodes, group("g7", "1", parent="g6"), holding(parent="g7"))
    assert "depth_exceeded" in codes(TargetContent(deeper))


def test_256_nodes_allowed_and_257_rejected_before_expensive_work() -> None:
    identifier = TargetIdentifier(TargetIdentifierKind.PROVIDER_KEY, "unmapped", "synthetic")
    mapping = TargetHoldingMapping(
        TargetMappingState.UNRESOLVED, requested_identifier=identifier, reason="Unmapped fixture"
    )
    nodes = tuple(
        TargetNode(str(i), None, TargetNodeKind.HOLDING, str(i), i, Decimal("0.00390625"), mapping)
        for i in range(256)
    )
    assert validate(TargetContent(nodes)).valid
    with pytest.raises(DomainError, match="bounded"):
        TargetContent((*nodes, nodes[0]))


def test_unresolved_mapping_can_publish_only_with_explicit_warning() -> None:
    unresolved = TargetHoldingMapping(
        TargetMappingState.AMBIGUOUS,
        requested_identifier=TargetIdentifier(TargetIdentifierKind.ISIN, "US0378331005"),
        reason="Multiple explicit candidates",
    )
    result = validate(TargetContent((replace(holding(), holding=unresolved),)))
    assert result.valid
    assert [(issue.code, issue.severity) for issue in result.issues] == [
        ("mapping_unresolved", TargetIssueSeverity.WARNING),
    ]
    with pytest.raises(DomainError):
        TargetHoldingMapping(TargetMappingState.UNRESOLVED)


def test_mapping_catalog_and_selector_disjointness() -> None:
    assert "unknown_instrument" in codes(TargetContent((holding(instrument=UUID(int=99)),)))
    assert "unknown_listing" in codes(TargetContent((holding(listing=UUID(int=99)),)))
    assert "listing_instrument_mismatch" in codes(TargetContent((holding(listing=OTHER_LISTING),)))
    assert "overlapping_holding_selectors" in codes(
        TargetContent((holding("a", "0.5"), holding("b", "0.5", order=1, listing=LISTING)))
    )
    assert "overlapping_holding_selectors" in codes(
        TargetContent(
            (holding("a", "0.5", listing=LISTING), holding("b", "0.5", order=1, listing=LISTING))
        )
    )
    allowed = validate(
        TargetContent(
            (
                holding("a", "0.5", listing=LISTING),
                holding("b", "0.5", order=1, listing=SECOND_LISTING),
            )
        )
    )
    assert allowed.valid
    assert "duplicate_economic_exposure" in {issue.code for issue in allowed.issues}
    mismatch = replace(
        holding(listing=LISTING),
        holding=TargetHoldingMapping(
            TargetMappingState.RESOLVED, INSTRUMENT, LISTING, SECOND_LISTING
        ),
    )
    assert "preferred_listing_mismatch" in codes(TargetContent((mismatch,)))


@pytest.mark.parametrize(
    "constraint",
    [
        TargetConstraint(
            "c",
            TargetConstraintKind.MINIMUM_FUNDED_AMOUNT,
            "stock",
            amount=Decimal("-1"),
            currency=EUR,
        ),
        TargetConstraint(
            "c", TargetConstraintKind.AMOUNT_INCREMENT, "stock", amount=Decimal("0"), currency=EUR
        ),
        TargetConstraint(
            "c",
            TargetConstraintKind.MINIMUM_FUNDED_AMOUNT,
            "stock",
            amount=Decimal("1"),
            currency=CurrencyCode("USD"),
        ),
        TargetConstraint(
            "c", TargetConstraintKind.MAXIMUM_POST_WEIGHT, "stock", weight=Decimal("1.1")
        ),
        TargetConstraint(
            "c", TargetConstraintKind.ELIGIBLE, "stock", enabled=True, weight=Decimal("1")
        ),
        TargetConstraint("c", TargetConstraintKind.MAXIMUM_FUNDED_LINES, count=257),
        TargetConstraint("c", TargetConstraintKind.PRIORITY, "stock", coefficient=Decimal("0")),
        TargetConstraint("c", TargetConstraintKind.CASH_RESERVE),
    ],
)
def test_constraint_field_variants_are_checked(constraint: TargetConstraint) -> None:
    assert "constraint_fields_invalid" in codes(TargetContent((holding(),), (constraint,)))


def test_constraint_scope_and_exact_bound_contradictions() -> None:
    minimum = TargetConstraint(
        "minimum", TargetConstraintKind.MINIMUM_POST_WEIGHT, "stock", weight=Decimal("0.7")
    )
    maximum = TargetConstraint(
        "maximum", TargetConstraintKind.MAXIMUM_POST_WEIGHT, "stock", weight=Decimal("0.6")
    )
    assert "constraint_bounds_conflict" in codes(TargetContent((holding(),), (minimum, maximum)))
    scope = TargetConstraint(
        "group",
        TargetConstraintKind.MINIMUM_GROUP_FUNDING,
        "stock",
        amount=Decimal("1"),
        currency=EUR,
    )
    assert "constraint_scope_invalid" in codes(TargetContent((holding(),), (scope,)))
    assert "duplicate_constraint_kind" in codes(
        TargetContent((holding(),), (maximum, replace(maximum, key="duplicate")))
    )
    assert "duplicate_constraint_key" in codes(TargetContent((holding(),), (maximum, maximum)))


def test_ancestor_funding_and_post_weight_conflicts_and_exclusions() -> None:
    tree = (group("g", "1"), group("child", "1", parent="g"), holding(parent="child"))
    minimum = TargetConstraint(
        "min",
        TargetConstraintKind.MINIMUM_GROUP_FUNDING,
        "child",
        amount=Decimal("11"),
        currency=EUR,
    )
    maximum = TargetConstraint(
        "max", TargetConstraintKind.MAXIMUM_GROUP_FUNDING, "g", amount=Decimal("10"), currency=EUR
    )
    assert "ancestor_constraint_conflict" in codes(TargetContent(tree, (minimum, maximum)))
    excluded = TargetExclusion("excluded", node_key="stock")
    assert "excluded_funding_conflict" in codes(TargetContent(tree, (minimum,), (excluded,)))
    weight_min = TargetConstraint(
        "weight_min", TargetConstraintKind.MINIMUM_POST_WEIGHT, "stock", weight=Decimal("0.8")
    )
    weight_max = TargetConstraint(
        "weight_max", TargetConstraintKind.MAXIMUM_POST_WEIGHT, "g", weight=Decimal("0.7")
    )
    assert "ancestor_constraint_conflict" in codes(TargetContent(tree, (weight_min, weight_max)))
    # A when-funded minimum does not require a positive allocation to an excluded holding.
    when_funded = TargetConstraint(
        "optional",
        TargetConstraintKind.MINIMUM_FUNDED_AMOUNT,
        "stock",
        amount=Decimal("20"),
        currency=EUR,
    )
    assert validate(TargetContent(tree, (when_funded,), (excluded,))).valid


def test_exclusion_identity_and_unknown_reference_validation() -> None:
    for exclusion in (
        TargetExclusion("e", instrument_id=UUID(int=99)),
        TargetExclusion("e", listing_id=UUID(int=99)),
    ):
        assert "exclusion_mapping_unknown" in codes(
            TargetContent((holding(),), exclusions=(exclusion,))
        )
    assert "exclusion_scope_invalid" in codes(
        TargetContent((holding(),), exclusions=(TargetExclusion("e", node_key="absent"),))
    )
    with pytest.raises(DomainError):
        TargetExclusion("bad", node_key="stock", instrument_id=INSTRUMENT)


def test_comparison_aligns_stable_keys_and_preserves_both_versions() -> None:
    before = TargetContent((holding(),))
    after = TargetContent(
        (replace(holding(weight="0.8"), name="Renamed"), cash(weight="0.2", order=1)),
        exclusions=(TargetExclusion("excluded", node_key="stock"),),
    )
    comparison = compare_target_content(
        before, after, left_effective_at=AS_OF, right_effective_at=AS_OF + timedelta(days=1)
    )
    assert [change.key for change in comparison.node_changes] == ["cash", "stock"]
    assert comparison.node_changes[0].changed_fields == ("added",)
    assert comparison.node_changes[1].changed_fields == ("name", "weight")
    assert comparison.exclusion_changes[0].key == "excluded"
    assert comparison.effective_time_changed
    assert before.nodes[0].weight == 1
    assert after.nodes[0].weight == Decimal("0.8")


def test_digest_binds_effective_time_currency_and_semantics_but_not_tuple_order() -> None:
    content = TargetContent((holding(weight="0.5"), cash(weight="0.5", order=1)))
    original = target_content_digest(content, reporting_currency=EUR, effective_at=AS_OF)
    assert original == target_content_digest(
        replace(content, nodes=tuple(reversed(content.nodes))),
        reporting_currency=EUR,
        effective_at=AS_OF,
    )
    assert original != target_content_digest(
        content, reporting_currency=EUR, effective_at=AS_OF + timedelta(seconds=1)
    )
    assert original != target_content_digest(
        content, reporting_currency=CurrencyCode("USD"), effective_at=AS_OF
    )


def test_ambient_decimal_context_does_not_change_validation_or_normalization() -> None:
    content = TargetContent((holding(weight="0.500000000000000001"), cash(weight="0.5", order=1)))
    expected = validate(content, normalize=True)
    with localcontext() as context:
        context.prec = 3
        actual = validate(content, normalize=True)
    assert actual == expected


@pytest.mark.parametrize(
    "value", [0.5, True, Decimal("NaN"), Decimal("Infinity"), Decimal("1e-19"), Decimal("1e20")]
)
def test_target_financial_scalars_reject_invalid_boundaries(value: object) -> None:
    with pytest.raises(DomainError):
        replace(holding(), weight=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        10**20,
        -(10**20),
        "100000000000000000000",
        "-100000000000000000000.1",
        Decimal("1E+20"),
        Decimal("99999999999999999999999999999999999999"),
    ],
)
def test_numeric_38_18_rejects_more_than_twenty_integer_digits(value: Decimal | int | str) -> None:
    with pytest.raises(DomainError, match="NUMERIC"):
        exact_decimal(value)


def test_numeric_38_18_accepts_extreme_twenty_digit_values() -> None:
    for value in ("99999999999999999999", "-99999999999999999999.999999999999999999"):
        assert exact_decimal(value) == Decimal(value)


def test_commands_queries_and_revision_helpers_enforce_their_boundary() -> None:
    assert VirtualPortfolioQuery(search="  STOCK  ").search == "stock"
    assert TargetVersionQuery().limit == TargetPageQuery().limit == 25
    for value in (True, 1.5, 0, 101):
        with pytest.raises(ValueError):
            TargetPageQuery(limit=value)  # type: ignore[arg-type]
    content = TargetContent((cash(),))
    assert CreateTargetVersionCommand(AS_OF, content=content).content == content
    assert ReplaceTargetDraftCommand(AS_OF, content).effective_at == AS_OF
    with pytest.raises(ValueError):
        CreateTargetVersionCommand(AS_OF)
    with pytest.raises(ValueError):
        CreateTargetVersionCommand(AS_OF, str(UUID(int=10)), content)
    with pytest.raises(ValueError):
        ValidateTargetCommand(normalize=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        UpdateVirtualPortfolioCommand()
    with pytest.raises(ValueError):
        CreateVirtualPortfolioCommand(" ", EUR)
    key = str(UUID(int=10))
    require_target_revision(target_etag(key, 2), key, 2)
    for header, error_code in (
        (None, TargetServiceErrorCode.REVISION_REQUIRED),
        (target_etag(key, 1), TargetServiceErrorCode.REVISION_MISMATCH),
    ):
        with pytest.raises(TargetServiceError) as caught:
            require_target_revision(header, key, 2)
        assert caught.value.code is error_code
    assert validate_target_idempotency_key("user.intent:2026-09-07")
    with pytest.raises(TargetServiceError):
        validate_target_idempotency_key("invalid\nkey")


def test_hierarchy_projection_is_independent_of_catalog_and_rejects_invalid_tree() -> None:
    from trading212_domain.targets import flatten_target_content

    content = TargetContent((holding(),))
    assert not validate_target_content(
        content, reporting_currency=EUR, effective_at=AS_OF, catalog=TargetCatalog((), ())
    ).valid
    result = flatten_target_content(content)
    assert result is not None
    assert len(result[0]) == 1 and result[0][0].effective_weight == Decimal(1)
    assert result[1] == 0
    assert flatten_target_content(TargetContent((holding(weight="0.9"),))) is None
    assert flatten_target_content(TargetContent((holding(parent="missing"),))) is None
