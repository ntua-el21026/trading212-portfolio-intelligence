"""Pure bounded target-tree validation, normalization, and stable comparison."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from uuid import UUID

from .errors import fail_validation
from .identifiers import require_uuid
from .serialization import canonical_json
from .values import CurrencyCode, exact_decimal, require_bounded_text, require_utc

TARGET_VALIDATION_METHOD = "target_validation_v1"
TARGET_VALIDATION_VERSION = "1.0.0"
MAX_TARGET_NODES = 256
MAX_TARGET_DEPTH = 8
TARGET_QUANTUM = Decimal("0.000000000000000001")
TARGET_NORMALIZATION_TOLERANCE = Decimal("0.000000000001")
_ISSUE_LIMIT = 1024


class TargetNodeKind(StrEnum):
    GROUP = "group"
    HOLDING = "holding"
    CASH = "cash"


class TargetMappingState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


class TargetIdentifierKind(StrEnum):
    ISIN = "isin"
    PROVIDER_KEY = "provider_key"
    MIC_TICKER = "mic_ticker"


class TargetConstraintKind(StrEnum):
    MINIMUM_FUNDED_AMOUNT = "minimum_funded_amount"
    AMOUNT_INCREMENT = "amount_increment"
    MINIMUM_POST_WEIGHT = "minimum_post_weight"
    MAXIMUM_POST_WEIGHT = "maximum_post_weight"
    MINIMUM_GROUP_FUNDING = "minimum_group_funding"
    MAXIMUM_GROUP_FUNDING = "maximum_group_funding"
    CASH_RESERVE = "cash_reserve"
    ELIGIBLE = "eligible"
    MAXIMUM_FUNDED_LINES = "maximum_funded_lines"
    PRIORITY = "priority"


class TargetIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


def _text(value: str, name: str, maximum: int, *, empty: bool = False) -> None:
    require_bounded_text(value, field=name, maximum=maximum, allow_empty=empty)
    if not empty and not value.strip():
        fail_validation(f"{name} must contain non-whitespace text", field=name)


def _optional_uuid(value: UUID | None, name: str) -> None:
    if value is not None:
        require_uuid(value, field=name)


def _tuple_of[T](value: tuple[T, ...], kind: type[T], name: str, maximum: int = 256) -> None:
    if (
        not isinstance(value, tuple)
        or len(value) > maximum
        or any(not isinstance(item, kind) for item in value)
    ):
        fail_validation(f"{name} must be a bounded immutable typed tuple", field=name)


@dataclass(frozen=True, slots=True)
class TargetIdentifier:
    kind: TargetIdentifierKind
    value: str
    provider: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TargetIdentifierKind):
            fail_validation("invalid identifier kind", field="identifier.kind")
        _text(self.value, "identifier.value", 80)
        patterns = {
            TargetIdentifierKind.ISIN: r"[A-Z]{2}[A-Z0-9]{9}[0-9]",
            TargetIdentifierKind.PROVIDER_KEY: r"[A-Za-z0-9._:-]{1,80}",
            TargetIdentifierKind.MIC_TICKER: r"[A-Z0-9]{4}:[A-Za-z0-9._-]{1,64}",
        }
        if re.fullmatch(patterns[self.kind], self.value) is None:
            fail_validation("invalid typed identifier", field="identifier.value")
        if self.kind is TargetIdentifierKind.PROVIDER_KEY:
            if (
                not isinstance(self.provider, str)
                or re.fullmatch(r"[A-Za-z0-9._-]{1,80}", self.provider) is None
            ):
                fail_validation("provider-key identifier requires a provider", field="identifier")
        elif self.provider is not None:
            fail_validation("provider is only valid for a provider key", field="identifier")


@dataclass(frozen=True, slots=True)
class TargetHoldingMapping:
    state: TargetMappingState
    instrument_id: UUID | None = None
    listing_id: UUID | None = None
    preferred_listing_id: UUID | None = None
    requested_identifier: TargetIdentifier | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, TargetMappingState):
            fail_validation("invalid mapping state", field="holding.state")
        for name in ("instrument_id", "listing_id", "preferred_listing_id"):
            _optional_uuid(getattr(self, name), name)
        if self.requested_identifier is not None and not isinstance(
            self.requested_identifier, TargetIdentifier
        ):
            fail_validation("invalid requested identifier", field="holding.requested_identifier")
        if self.reason is not None:
            _text(self.reason, "holding.reason", 1000)
        if self.state is TargetMappingState.RESOLVED and self.instrument_id is None:
            fail_validation(
                "resolved mapping requires an instrument", field="holding.instrument_id"
            )
        if self.state is not TargetMappingState.RESOLVED and (
            self.requested_identifier is None or self.reason is None
        ):
            fail_validation("unresolved mapping requires identifier and reason", field="holding")


@dataclass(frozen=True, slots=True)
class TargetNode:
    key: str
    parent_key: str | None
    kind: TargetNodeKind
    name: str
    order: int
    weight: Decimal
    holding: TargetHoldingMapping | None = None

    def __post_init__(self) -> None:
        _text(self.key, "node.key", 80)
        if self.parent_key is not None:
            _text(self.parent_key, "node.parent_key", 80)
        if not isinstance(self.kind, TargetNodeKind):
            fail_validation("invalid node kind", field="node.kind")
        _text(self.name, "node.name", 120)
        if (
            isinstance(self.order, bool)
            or not isinstance(self.order, int)
            or not 0 <= self.order < 256
        ):
            fail_validation("node order must be an integer from 0 through 255", field="node.order")
        object.__setattr__(self, "weight", exact_decimal(self.weight, field="node.weight"))
        if self.holding is not None and not isinstance(self.holding, TargetHoldingMapping):
            fail_validation("invalid holding mapping", field="node.holding")


@dataclass(frozen=True, slots=True)
class TargetConstraint:
    key: str
    kind: TargetConstraintKind
    node_key: str | None = None
    amount: Decimal | None = None
    currency: CurrencyCode | None = None
    weight: Decimal | None = None
    enabled: bool | None = None
    count: int | None = None
    coefficient: Decimal | None = None

    def __post_init__(self) -> None:
        _text(self.key, "constraint.key", 80)
        if not isinstance(self.kind, TargetConstraintKind):
            fail_validation("invalid constraint kind", field="constraint.kind")
        if self.node_key is not None:
            _text(self.node_key, "constraint.node_key", 80)
        for name in ("amount", "weight", "coefficient"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, exact_decimal(value, field=f"constraint.{name}"))
        if self.currency is not None and not isinstance(self.currency, CurrencyCode):
            fail_validation("invalid constraint currency", field="constraint.currency")
        if self.enabled is not None and not isinstance(self.enabled, bool):
            fail_validation("eligible value must be boolean", field="constraint.enabled")
        if self.count is not None and (
            isinstance(self.count, bool) or not isinstance(self.count, int)
        ):
            fail_validation("funded line count must be an integer", field="constraint.count")


@dataclass(frozen=True, slots=True)
class TargetExclusion:
    key: str
    node_key: str | None = None
    instrument_id: UUID | None = None
    listing_id: UUID | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _text(self.key, "exclusion.key", 80)
        if self.node_key is not None:
            _text(self.node_key, "exclusion.node_key", 80)
        _optional_uuid(self.instrument_id, "exclusion.instrument_id")
        _optional_uuid(self.listing_id, "exclusion.listing_id")
        _text(self.reason, "exclusion.reason", 1000, empty=True)
        if (
            sum(value is not None for value in (self.node_key, self.instrument_id, self.listing_id))
            != 1
        ):
            fail_validation("exclusion requires exactly one selector", field="exclusion")


@dataclass(frozen=True, slots=True)
class TargetContent:
    nodes: tuple[TargetNode, ...]
    constraints: tuple[TargetConstraint, ...] = ()
    exclusions: tuple[TargetExclusion, ...] = ()

    def __post_init__(self) -> None:
        _tuple_of(self.nodes, TargetNode, "nodes")
        _tuple_of(self.constraints, TargetConstraint, "constraints")
        _tuple_of(self.exclusions, TargetExclusion, "exclusions")


@dataclass(frozen=True, slots=True)
class TargetInstrumentReference:
    instrument_id: UUID
    economic_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        require_uuid(self.instrument_id, field="instrument_id")
        _optional_uuid(self.economic_entity_id, "economic_entity_id")


@dataclass(frozen=True, slots=True)
class TargetListingReference:
    listing_id: UUID
    instrument_id: UUID
    eligible: bool = True

    def __post_init__(self) -> None:
        require_uuid(self.listing_id, field="listing_id")
        require_uuid(self.instrument_id, field="instrument_id")
        if not isinstance(self.eligible, bool):
            fail_validation("listing eligibility must be boolean", field="eligible")


@dataclass(frozen=True, slots=True)
class TargetCatalog:
    instruments: tuple[TargetInstrumentReference, ...] = ()
    listings: tuple[TargetListingReference, ...] = ()

    def __post_init__(self) -> None:
        _tuple_of(self.instruments, TargetInstrumentReference, "catalog.instruments", 1024)
        _tuple_of(self.listings, TargetListingReference, "catalog.listings", 4096)
        instrument_ids = {item.instrument_id for item in self.instruments}
        if len(instrument_ids) != len(self.instruments) or len(
            {item.listing_id for item in self.listings}
        ) != len(self.listings):
            fail_validation("catalog identities must be unique", field="catalog")
        if any(item.instrument_id not in instrument_ids for item in self.listings):
            fail_validation("catalog listing references unknown instrument", field="catalog")


@dataclass(frozen=True, slots=True)
class TargetValidationIssue:
    code: str
    severity: TargetIssueSeverity
    message: str
    node_keys: tuple[str, ...] = ()
    constraint_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetNormalizationAdjustment:
    node_key: str
    parent_key: str | None
    original_weight: Decimal
    normalized_weight: Decimal
    original_sibling_sum: Decimal
    remainder_rank: int


@dataclass(frozen=True, slots=True)
class FlattenedTargetNode:
    node: TargetNode
    depth: int
    ordinal: int
    path_keys: tuple[str, ...]
    path_factors: tuple[Decimal, ...]
    effective_weight: Decimal


@dataclass(frozen=True, slots=True)
class TargetValidation:
    valid: bool
    content: TargetContent
    input_digest: str
    result_digest: str
    issues: tuple[TargetValidationIssue, ...]
    adjustments: tuple[TargetNormalizationAdjustment, ...]
    flattened_nodes: tuple[FlattenedTargetNode, ...]
    effective_weight_rounding_residual: Decimal | None


@dataclass(frozen=True, slots=True)
class TargetNodeChange:
    key: str
    changed_fields: tuple[str, ...]
    left: TargetNode | None
    right: TargetNode | None


@dataclass(frozen=True, slots=True)
class TargetConstraintChange:
    key: str
    left: TargetConstraint | None
    right: TargetConstraint | None


@dataclass(frozen=True, slots=True)
class TargetExclusionChange:
    key: str
    left: TargetExclusion | None
    right: TargetExclusion | None


@dataclass(frozen=True, slots=True)
class TargetComparison:
    node_changes: tuple[TargetNodeChange, ...]
    constraint_changes: tuple[TargetConstraintChange, ...]
    exclusion_changes: tuple[TargetExclusionChange, ...]
    effective_time_changed: bool


def canonical_target_content(content: TargetContent) -> TargetContent:
    """Ordering of an input tuple is not financial or hierarchy semantics."""
    return TargetContent(
        nodes=tuple(sorted(content.nodes, key=lambda node: (node.key, canonical_json(node)))),
        constraints=tuple(
            sorted(content.constraints, key=lambda item: (item.key, canonical_json(item)))
        ),
        exclusions=tuple(
            sorted(content.exclusions, key=lambda item: (item.key, canonical_json(item)))
        ),
    )


def target_content_digest(
    content: TargetContent, *, reporting_currency: CurrencyCode, effective_at: datetime
) -> str:
    if not isinstance(content, TargetContent) or not isinstance(reporting_currency, CurrencyCode):
        fail_validation("typed content and reporting currency are required", field="content")
    effective_at = require_utc(effective_at, field="effective_at")
    return hashlib.sha256(
        canonical_json(
            {
                "schema_version": "1.0.0",
                "method": TARGET_VALIDATION_METHOD,
                "method_version": TARGET_VALIDATION_VERSION,
                "reporting_currency": reporting_currency,
                "effective_at": effective_at,
                "content": canonical_target_content(content),
            }
        ).encode("utf-8")
    ).hexdigest()


class _Issues:
    def __init__(self) -> None:
        self.items: list[TargetValidationIssue] = []
        self.exceeded = False

    def add(
        self,
        code: str,
        message: str,
        *,
        nodes: tuple[str, ...] = (),
        constraints: tuple[str, ...] = (),
        warning: bool = False,
    ) -> None:
        if len(self.items) >= _ISSUE_LIMIT - 1:
            self.exceeded = True
            return
        self.items.append(
            TargetValidationIssue(
                code,
                TargetIssueSeverity.WARNING if warning else TargetIssueSeverity.ERROR,
                message,
                tuple(sorted(nodes)),
                tuple(sorted(constraints)),
            )
        )

    def finish(self) -> tuple[TargetValidationIssue, ...]:
        if self.exceeded:
            self.items.append(
                TargetValidationIssue(
                    "validation_issue_limit",
                    TargetIssueSeverity.ERROR,
                    "Additional issues exceed the bounded result; correct listed issues first.",
                )
            )
        return tuple(
            sorted(
                set(self.items),
                key=lambda issue: (
                    issue.severity.value,
                    issue.code,
                    issue.node_keys,
                    issue.constraint_keys,
                ),
            )
        )


def _tree(
    content: TargetContent,
    issues: _Issues,
) -> tuple[dict[str, TargetNode], dict[str | None, list[TargetNode]], bool]:
    nodes: dict[str, TargetNode] = {}
    children: dict[str | None, list[TargetNode]] = defaultdict(list)
    valid = bool(content.nodes)
    if not content.nodes:
        issues.add("empty_tree", "A target version must contain at least one node.")
    for node in content.nodes:
        if node.key in nodes:
            issues.add("duplicate_node_key", "Node keys must be unique.", nodes=(node.key,))
            valid = False
        nodes[node.key] = node
        children[node.parent_key].append(node)
    for group in children.values():
        group.sort(key=lambda node: (node.order, node.key))
        orders: dict[int, str] = {}
        for node in group:
            if node.order in orders:
                issues.add(
                    "duplicate_sibling_order",
                    "Sibling orders must be unique.",
                    nodes=(orders[node.order], node.key),
                )
                valid = False
            orders[node.order] = node.key
    cash = tuple(node.key for node in content.nodes if node.kind is TargetNodeKind.CASH)
    if len(cash) > 1:
        issues.add("multiple_cash_targets", "Only one cash target is permitted.", nodes=cash)
        valid = False
    for node in content.nodes:
        if node.parent_key is not None and node.parent_key not in nodes:
            issues.add(
                "missing_parent", "A parent must belong to this target version.", nodes=(node.key,)
            )
            valid = False
        if (node.kind is TargetNodeKind.GROUP) != bool(children.get(node.key)):
            issues.add(
                "invalid_node_children",
                "Groups require children and leaves cannot have children.",
                nodes=(node.key,),
            )
            valid = False
        if node.kind is TargetNodeKind.CASH and node.parent_key is not None:
            issues.add("nested_cash_target", "Cash must be a top-level leaf.", nodes=(node.key,))
            valid = False
        visited: set[str] = set()
        current: TargetNode | None = node
        while current is not None:
            if current.key in visited:
                issues.add(
                    "cycle_detected", "Target parent links must be acyclic.", nodes=(node.key,)
                )
                valid = False
                break
            visited.add(current.key)
            if len(visited) == MAX_TARGET_DEPTH + 1:
                issues.add(
                    "depth_exceeded",
                    "Target depth exceeds eight weighted edges.",
                    nodes=(node.key,),
                )
                valid = False
            current = nodes.get(current.parent_key) if current.parent_key is not None else None
    return nodes, children, valid


def _mappings(content: TargetContent, catalog: TargetCatalog, issues: _Issues) -> None:
    instruments = {item.instrument_id: item for item in catalog.instruments}
    listings = {item.listing_id: item for item in catalog.listings}
    selectors: dict[UUID, list[TargetNode]] = defaultdict(list)
    entities: dict[UUID, list[str]] = defaultdict(list)
    for node in content.nodes:
        mapping = node.holding
        if node.kind is TargetNodeKind.HOLDING and mapping is None:
            issues.add(
                "holding_mapping_required", "A holding requires a typed mapping.", nodes=(node.key,)
            )
            continue
        if node.kind is not TargetNodeKind.HOLDING and mapping is not None:
            issues.add(
                "holding_mapping_not_allowed",
                "Only holding nodes have mappings.",
                nodes=(node.key,),
            )
            continue
        if mapping is None:
            continue
        if mapping.state is not TargetMappingState.RESOLVED:
            issues.add(
                "mapping_unresolved",
                "Mapping remains unresolved; dependent planning is unavailable.",
                nodes=(node.key,),
                warning=True,
            )
        if mapping.instrument_id is not None:
            if mapping.instrument_id not in instruments:
                issues.add(
                    "unknown_instrument",
                    "Mapped instrument is not in the canonical catalog.",
                    nodes=(node.key,),
                )
            else:
                entity = instruments[mapping.instrument_id].economic_entity_id
                if entity is not None:
                    entities[entity].append(node.key)
            selectors[mapping.instrument_id].append(node)
        for listing_id in (mapping.listing_id, mapping.preferred_listing_id):
            if listing_id is None:
                continue
            listing = listings.get(listing_id)
            if listing is None:
                issues.add(
                    "unknown_listing",
                    "Mapped listing is not in the canonical catalog.",
                    nodes=(node.key,),
                )
            elif listing.instrument_id != mapping.instrument_id:
                issues.add(
                    "listing_instrument_mismatch",
                    "Listing must belong to the selected instrument.",
                    nodes=(node.key,),
                )
        if mapping.listing_id is not None and mapping.preferred_listing_id not in (
            None,
            mapping.listing_id,
        ):
            issues.add(
                "preferred_listing_mismatch",
                "Funding preference must match an explicit listing selector.",
                nodes=(node.key,),
            )
    for selected in selectors.values():
        if len(selected) > 1:
            seen: set[UUID | None] = set()
            overlapping = False
            for node in selected:
                assert node.holding is not None
                selector = node.holding.listing_id
                overlapping = overlapping or selector is None or selector in seen
                seen.add(selector)
            if overlapping:
                issues.add(
                    "overlapping_holding_selectors",
                    "Instrument-wide and listing-specific selectors must be disjoint.",
                    nodes=tuple(node.key for node in selected),
                )
            else:
                issues.add(
                    "duplicate_economic_exposure",
                    "Multiple listings select the same canonical instrument.",
                    nodes=tuple(node.key for node in selected),
                    warning=True,
                )
    for keys in entities.values():
        if len(keys) > 1:
            issues.add(
                "duplicate_economic_exposure",
                "Holdings share a documented economic entity.",
                nodes=tuple(keys),
                warning=True,
            )


def _normalize(
    content: TargetContent,
    children: dict[str | None, list[TargetNode]],
    issues: _Issues,
    normalize: bool,
) -> tuple[TargetContent, tuple[TargetNormalizationAdjustment, ...]]:
    replacements: dict[str, TargetNode] = {}
    adjustments: list[TargetNormalizationAdjustment] = []
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        for parent in sorted(children, key=lambda key: (key is not None, key or "")):
            siblings = children[parent]
            if any(not 0 <= node.weight <= 1 for node in siblings):
                issues.add(
                    "weight_out_of_range",
                    "Sibling weights must lie between zero and one.",
                    nodes=tuple(node.key for node in siblings if not 0 <= node.weight <= 1),
                )
                continue
            total = sum((node.weight for node in siblings), Decimal(0))
            if total == 1:
                continue
            if total <= 0:
                issues.add(
                    "zero_sibling_sum",
                    "Sibling weights require a positive sum.",
                    nodes=tuple(node.key for node in siblings),
                )
                continue
            if not normalize or abs(total - 1) > TARGET_NORMALIZATION_TOLERANCE:
                issues.add(
                    "sibling_sum_invalid",
                    "Sibling sum must be exactly one; permitted normalization must be explicit.",
                    nodes=tuple(node.key for node in siblings),
                )
                continue
            exact = {node.key: node.weight / total for node in siblings}
            rounded = {
                key: value.quantize(TARGET_QUANTUM, rounding=ROUND_FLOOR)
                for key, value in exact.items()
            }
            ranked = sorted(exact, key=lambda key: (-(exact[key] - rounded[key]), key))
            units = int((1 - sum(rounded.values(), Decimal(0))) / TARGET_QUANTUM)
            for key in ranked[:units]:
                rounded[key] += TARGET_QUANTUM
            for rank, key in enumerate(ranked):
                node = next(node for node in siblings if node.key == key)
                replacements[key] = replace(node, weight=rounded[key])
                adjustments.append(
                    TargetNormalizationAdjustment(
                        key,
                        parent,
                        node.weight,
                        rounded[key],
                        total,
                        rank,
                    )
                )
    return replace(
        content, nodes=tuple(replacements.get(node.key, node) for node in content.nodes)
    ), tuple(sorted(adjustments, key=lambda item: item.node_key))


def _flatten(content: TargetContent) -> tuple[tuple[FlattenedTargetNode, ...], Decimal]:
    children: dict[str | None, list[TargetNode]] = defaultdict(list)
    for node in content.nodes:
        children[node.parent_key].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.order, node.key))
    flattened: list[FlattenedTargetNode] = []
    with localcontext() as context:
        context.prec = 160
        context.rounding = ROUND_HALF_EVEN
        pending: list[tuple[TargetNode, tuple[str, ...], tuple[Decimal, ...], Decimal]] = [
            (node, (), (), Decimal(1)) for node in reversed(children[None])
        ]
        while pending:
            node, keys, factors, preceding = pending.pop()
            path_keys = (*keys, node.key)
            path_factors = (*factors, node.weight)
            product = preceding * node.weight
            flattened.append(
                FlattenedTargetNode(
                    node,
                    len(path_keys),
                    len(flattened),
                    path_keys,
                    path_factors,
                    product.quantize(TARGET_QUANTUM),
                )
            )
            pending.extend(
                (child, path_keys, path_factors, product) for child in reversed(children[node.key])
            )
        residual = 1 - sum(
            (
                item.effective_weight
                for item in flattened
                if item.node.kind is not TargetNodeKind.GROUP
            ),
            Decimal(0),
        )
    return tuple(flattened), exact_decimal(residual)


def _constraint_fields(item: TargetConstraint, currency: CurrencyCode) -> bool:
    present = {
        name
        for name in ("amount", "currency", "weight", "enabled", "count", "coefficient")
        if getattr(item, name) is not None
    }
    amounts = {
        TargetConstraintKind.MINIMUM_FUNDED_AMOUNT,
        TargetConstraintKind.AMOUNT_INCREMENT,
        TargetConstraintKind.MINIMUM_GROUP_FUNDING,
        TargetConstraintKind.MAXIMUM_GROUP_FUNDING,
    }
    if item.kind in amounts:
        return (
            present == {"amount", "currency"}
            and item.currency == currency
            and item.amount is not None
            and (
                item.amount > 0
                if item.kind is TargetConstraintKind.AMOUNT_INCREMENT
                else item.amount >= 0
            )
        )
    if item.kind in {
        TargetConstraintKind.MINIMUM_POST_WEIGHT,
        TargetConstraintKind.MAXIMUM_POST_WEIGHT,
    }:
        return present == {"weight"} and item.weight is not None and 0 <= item.weight <= 1
    if item.kind is TargetConstraintKind.CASH_RESERVE:
        return (
            present in ({"amount", "currency"}, {"weight"}, {"amount", "currency", "weight"})
            and (item.amount is None or (item.amount >= 0 and item.currency == currency))
            and (item.weight is None or 0 <= item.weight <= 1)
        )
    if item.kind is TargetConstraintKind.ELIGIBLE:
        return present == {"enabled"}
    if item.kind is TargetConstraintKind.MAXIMUM_FUNDED_LINES:
        return present == {"count"} and item.count is not None and 0 <= item.count <= 256
    return (
        present == {"coefficient"}
        and item.coefficient is not None
        and Decimal("0.000001") <= item.coefficient <= 1000
    )


def _constraints(
    content: TargetContent,
    nodes: dict[str, TargetNode],
    catalog: TargetCatalog,
    currency: CurrencyCode,
    issues: _Issues,
    tree_valid: bool,
) -> None:
    kinds = TargetConstraintKind
    portfolio_kinds = {kinds.CASH_RESERVE, kinds.MAXIMUM_FUNDED_LINES}
    holding_kinds = {kinds.MINIMUM_FUNDED_AMOUNT, kinds.AMOUNT_INCREMENT, kinds.ELIGIBLE}
    group_kinds = {kinds.MINIMUM_GROUP_FUNDING, kinds.MAXIMUM_GROUP_FUNDING}
    by_scope: dict[str | None, dict[TargetConstraintKind, TargetConstraint]] = defaultdict(dict)
    seen: set[str] = set()
    for item in content.constraints:
        if item.key in seen:
            issues.add(
                "duplicate_constraint_key",
                "Constraint keys must be unique.",
                constraints=(item.key,),
            )
        seen.add(item.key)
        node = nodes.get(item.node_key) if item.node_key is not None else None
        scope_valid = (
            item.node_key is None
            if item.kind in portfolio_kinds
            else node is not None
            and (
                node.kind is TargetNodeKind.HOLDING
                if item.kind in holding_kinds
                else node.kind is TargetNodeKind.GROUP
                if item.kind in group_kinds
                else node.kind in {TargetNodeKind.HOLDING, TargetNodeKind.GROUP}
            )
        )
        if not scope_valid:
            issues.add(
                "constraint_scope_invalid",
                "Constraint is not valid at the selected scope.",
                constraints=(item.key,),
            )
        if not _constraint_fields(item, currency):
            issues.add(
                "constraint_fields_invalid",
                "Constraint fields, bounds, or currency are incompatible with its kind.",
                constraints=(item.key,),
            )
            continue
        if item.kind in by_scope[item.node_key]:
            issues.add(
                "duplicate_constraint_kind",
                "A scope permits one constraint of each kind.",
                constraints=(item.key, by_scope[item.node_key][item.kind].key),
            )
        by_scope[item.node_key][item.kind] = item
    excluded: set[str] = set()
    excluded_keys: set[str] = set()
    excluded_selectors: set[tuple[str | None, UUID | None, UUID | None]] = set()
    instruments = {item.instrument_id for item in catalog.instruments}
    listings = {item.listing_id for item in catalog.listings}
    for exclusion in content.exclusions:
        if exclusion.key in excluded_keys:
            issues.add("duplicate_exclusion_key", "Exclusion keys must be unique.")
        excluded_keys.add(exclusion.key)
        selector = (exclusion.node_key, exclusion.instrument_id, exclusion.listing_id)
        if selector in excluded_selectors:
            issues.add("duplicate_exclusion_selector", "An exclusion selector must be unique.")
        excluded_selectors.add(selector)
        if exclusion.node_key is not None and (
            exclusion.node_key not in nodes
            or nodes[exclusion.node_key].kind is not TargetNodeKind.HOLDING
        ):
            issues.add("exclusion_scope_invalid", "Exclusion node must identify a holding.")
        if (exclusion.instrument_id is not None and exclusion.instrument_id not in instruments) or (
            exclusion.listing_id is not None and exclusion.listing_id not in listings
        ):
            issues.add(
                "exclusion_mapping_unknown", "Exclusion references an unknown canonical identity."
            )
        for node in content.nodes:
            mapping = node.holding
            if exclusion.node_key == node.key or (
                mapping is not None
                and (
                    (
                        exclusion.instrument_id is not None
                        and exclusion.instrument_id == mapping.instrument_id
                    )
                    or (
                        exclusion.listing_id is not None
                        and exclusion.listing_id
                        in (mapping.listing_id, mapping.preferred_listing_id)
                    )
                )
            ):
                excluded.add(node.key)
    for scope, values in by_scope.items():
        eligibility = values.get(kinds.ELIGIBLE)
        if scope is not None and eligibility is not None and eligibility.enabled is False:
            excluded.add(scope)
        for low_kind, high_kind, field in (
            (kinds.MINIMUM_POST_WEIGHT, kinds.MAXIMUM_POST_WEIGHT, "weight"),
            (kinds.MINIMUM_GROUP_FUNDING, kinds.MAXIMUM_GROUP_FUNDING, "amount"),
        ):
            low, high = values.get(low_kind), values.get(high_kind)
            if low is not None and high is not None and getattr(low, field) > getattr(high, field):
                issues.add(
                    "constraint_bounds_conflict",
                    "Minimum constraint exceeds maximum at the same scope.",
                    constraints=(low.key, high.key),
                )
    if not tree_valid:
        return
    _ancestor_constraints(nodes, by_scope, excluded, issues)


def _ancestor_constraints(
    nodes: dict[str, TargetNode],
    constraints: dict[str | None, dict[TargetConstraintKind, TargetConstraint]],
    excluded: set[str],
    issues: _Issues,
) -> None:
    kinds = TargetConstraintKind
    children: dict[str, list[TargetNode]] = defaultdict(list)
    for node in nodes.values():
        if node.parent_key is not None:
            children[node.parent_key].append(node)

    def visit(key: str) -> tuple[Decimal, Decimal | None, Decimal, Decimal, int, int]:
        node = nodes[key]
        values = constraints.get(key, {})
        child_bounds = [
            visit(child.key) for child in sorted(children[key], key=lambda item: item.key)
        ]
        weight_low = Decimal(0)
        weight_high = Decimal(1)
        funding_low = Decimal(0)
        funding_high: Decimal | None = None
        eligible_count = int(node.kind is TargetNodeKind.HOLDING and key not in excluded)
        required_lines = 0
        if child_bounds:
            weight_low = sum((bound[2] for bound in child_bounds), Decimal(0))
            weight_high = min(Decimal(1), sum((bound[3] for bound in child_bounds), Decimal(0)))
            funding_low = sum((bound[0] for bound in child_bounds), Decimal(0))
            if all(bound[1] is not None for bound in child_bounds):
                funding_high = sum(
                    (bound[1] for bound in child_bounds if bound[1] is not None), Decimal(0)
                )
            eligible_count = sum(bound[4] for bound in child_bounds)
            required_lines = sum(bound[5] for bound in child_bounds)
        if node.kind is TargetNodeKind.HOLDING and key in excluded:
            funding_high = Decimal(0)
        for kind, field in (
            (kinds.MINIMUM_POST_WEIGHT, "weight"),
            (kinds.MAXIMUM_POST_WEIGHT, "weight"),
            (kinds.MINIMUM_GROUP_FUNDING, "amount"),
            (kinds.MAXIMUM_GROUP_FUNDING, "amount"),
        ):
            item = values.get(kind)
            if item is None:
                continue
            value: Decimal = getattr(item, field)
            if kind is kinds.MINIMUM_POST_WEIGHT:
                weight_low = max(weight_low, value)
            elif kind is kinds.MAXIMUM_POST_WEIGHT:
                weight_high = min(weight_high, value)
            elif kind is kinds.MINIMUM_GROUP_FUNDING:
                funding_low = max(funding_low, value)
            else:
                funding_high = min(funding_high, value) if funding_high is not None else value
        if weight_low > weight_high or (funding_high is not None and funding_low > funding_high):
            issues.add(
                "ancestor_constraint_conflict",
                "Ancestor and descendant bounds cannot hold together.",
                nodes=(key,),
            )
        if funding_low > 0 and eligible_count == 0:
            issues.add(
                "excluded_funding_conflict",
                "Required group funding has no eligible descendant holding.",
                nodes=(key,),
            )
        # One funded descendant can satisfy all its ancestors, while disjoint
        # child subtrees with positive funding each require a separate line.
        required_lines = max(required_lines, int(funding_low > 0))
        return funding_low, funding_high, weight_low, weight_high, eligible_count, required_lines

    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        top = [
            visit(node.key)
            for node in sorted(nodes.values(), key=lambda item: item.key)
            if node.parent_key is None
        ]
        if sum((bound[2] for bound in top), Decimal(0)) > 1:
            issues.add(
                "portfolio_weight_bounds_conflict",
                "Disjoint required post-weights exceed the full portfolio.",
            )
        line_limit = constraints.get(None, {}).get(kinds.MAXIMUM_FUNDED_LINES)
        if (
            line_limit is not None
            and line_limit.count is not None
            and sum(bound[5] for bound in top) > line_limit.count
        ):
            issues.add(
                "funded_line_conflict",
                "Disjoint required group funding exceeds the funded-line limit.",
                constraints=(line_limit.key,),
            )


def flatten_target_content(
    content: TargetContent,
) -> tuple[tuple[FlattenedTargetNode, ...], Decimal] | None:
    """Project exact hierarchy weights independently of mutable catalog validation.

    Invalid topology or sibling weights have no hierarchy projection. Mapping and
    funding validation remain separate, so a historical read never changes because
    the current instrument catalog or a future planner changes.
    """
    if not isinstance(content, TargetContent):
        fail_validation("typed target content is required", field="content")
    canonical = canonical_target_content(content)
    issues = _Issues()
    _, children, tree_valid = _tree(canonical, issues)
    _normalize(canonical, children, issues, False)
    if not tree_valid or any(
        issue.severity is TargetIssueSeverity.ERROR for issue in issues.finish()
    ):
        return None
    return _flatten(canonical)


def validate_target_content(
    content: TargetContent,
    *,
    reporting_currency: CurrencyCode,
    effective_at: datetime,
    catalog: TargetCatalog,
    normalize: bool = False,
) -> TargetValidation:
    """Return stable issues for relational invalidity; reject malformed scalar shapes."""
    if not isinstance(content, TargetContent) or not isinstance(catalog, TargetCatalog):
        fail_validation("typed target content and catalog are required", field="content")
    if not isinstance(normalize, bool):
        fail_validation("normalize must be boolean", field="normalize")
    initial = canonical_target_content(content)
    input_digest = target_content_digest(
        initial, reporting_currency=reporting_currency, effective_at=effective_at
    )
    issues = _Issues()
    nodes, children, tree_valid = _tree(initial, issues)
    _mappings(initial, catalog, issues)
    _constraints(initial, nodes, catalog, reporting_currency, issues, tree_valid)
    normalized, adjustments = _normalize(initial, children, issues, normalize and tree_valid)
    final_issues = issues.finish()
    valid = not any(issue.severity is TargetIssueSeverity.ERROR for issue in final_issues)
    flattened, residual = _flatten(normalized) if valid else ((), None)
    return TargetValidation(
        valid,
        normalized,
        input_digest,
        target_content_digest(
            normalized,
            reporting_currency=reporting_currency,
            effective_at=effective_at,
        ),
        final_issues,
        adjustments,
        flattened,
        residual,
    )


def compare_target_content(
    left: TargetContent,
    right: TargetContent,
    *,
    left_effective_at: datetime,
    right_effective_at: datetime,
) -> TargetComparison:
    if not isinstance(left, TargetContent) or not isinstance(right, TargetContent):
        fail_validation("comparison requires typed target content", field="content")
    left_effective_at = require_utc(left_effective_at)
    right_effective_at = require_utc(right_effective_at)
    for content in (left, right):
        for name, items in (
            ("nodes", content.nodes),
            ("constraints", content.constraints),
            ("exclusions", content.exclusions),
        ):
            if len({item.key for item in items}) != len(items):
                fail_validation("comparison requires unique stable keys", field=name)
    left_nodes, right_nodes = (
        {node.key: node for node in left.nodes},
        {node.key: node for node in right.nodes},
    )
    node_changes: list[TargetNodeChange] = []
    for key in sorted(left_nodes.keys() | right_nodes.keys()):
        before, after = left_nodes.get(key), right_nodes.get(key)
        if before == after:
            continue
        fields = (
            ("added",)
            if before is None
            else ("removed",)
            if after is None
            else tuple(
                name
                for name in ("parent_key", "kind", "name", "order", "weight", "holding")
                if getattr(before, name) != getattr(after, name)
            )
        )
        node_changes.append(TargetNodeChange(key, fields, before, after))
    left_constraints = {item.key: item for item in left.constraints}
    right_constraints = {item.key: item for item in right.constraints}
    left_exclusions = {item.key: item for item in left.exclusions}
    right_exclusions = {item.key: item for item in right.exclusions}
    return TargetComparison(
        tuple(node_changes),
        tuple(
            TargetConstraintChange(key, left_constraints.get(key), right_constraints.get(key))
            for key in sorted(left_constraints.keys() | right_constraints.keys())
            if left_constraints.get(key) != right_constraints.get(key)
        ),
        tuple(
            TargetExclusionChange(key, left_exclusions.get(key), right_exclusions.get(key))
            for key in sorted(left_exclusions.keys() | right_exclusions.keys())
            if left_exclusions.get(key) != right_exclusions.get(key)
        ),
        left_effective_at != right_effective_at,
    )
