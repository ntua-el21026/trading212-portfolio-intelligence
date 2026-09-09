"""One complete, pending-branch-reserving traversal over real snapshot roots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.xray import (
    XrayCash,
    XrayDependencyKind,
    XrayDimension,
    XrayHoldingKind,
    XrayInput,
    XrayPosition,
    XrayReason,
)
from trading212_domain.xray_result import (
    XrayFundEdge,
    XrayHeldFund,
    XrayPathClassification,
    XrayRootExact,
)
from trading212_domain.xray_validation import bound, decimal_role, invalid

from trading212_analytics._xray_decimal import (
    ONE,
    UNIT,
    ZERO,
    arithmetic,
    coefficient18,
    path_relative,
)
from trading212_analytics._xray_sources import SourceIndex, confidence, quality


@dataclass(frozen=True, slots=True)
class Branch:
    root_key: str
    key: str
    instrument_id: UUID | None
    entity_id: UUID | None
    listing_id: UUID | None
    money: Decimal | None
    cash: bool
    reason: XrayReason | None
    edges: tuple[XrayFundEdge, ...]
    ancestry: tuple[UUID, ...]
    identity_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    sources: tuple[UUID, ...]
    quality: QualityState
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class RawPath:
    key: str
    root_key: str
    instrument_id: UUID | None
    entity_id: UUID | None
    explicit_cash: bool
    unresolved_reason: XrayReason | None
    fund_edges: tuple[XrayFundEdge, ...]
    relative_coefficient: Decimal
    money_coefficient: Decimal | None
    identity_decision_ids: tuple[UUID, ...]
    source_reference_ids: tuple[UUID, ...]
    classifications: tuple[XrayPathClassification, ...]
    quality: QualityState
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class Graph:
    paths: tuple[RawPath, ...]
    roots: tuple[XrayRootExact, ...]
    held_funds: tuple[XrayHeldFund, ...]
    visited_paths: int


def _attach(
    branch: Branch, evidence: tuple[UUID, ...], index: SourceIndex, *, identity: bool = False
) -> Branch | None:
    references = {index.evidence[item].source_reference_id for item in evidence}
    combined = set(branch.sources) | references
    decisions = set(branch.identity_ids) | {
        item
        for item in evidence
        if identity
        or index.dependencies[index.evidence[item].source_reference_id].kind
        in (XrayDependencyKind.IDENTITY, XrayDependencyKind.RELATIONSHIP)
    }
    if len(combined) > 256 or len(decisions) > 256:
        return None
    index.consume(evidence, branch.key)
    return replace(
        branch,
        sources=tuple(sorted(combined, key=str)),
        identity_ids=tuple(sorted(decisions, key=str)),
        evidence_ids=tuple(sorted(set(branch.evidence_ids + evidence), key=str)),
        confidence=confidence(
            (branch.confidence, *(index.evidence[item].confidence for item in evidence))
        ),
        quality=quality(
            (branch.quality, *(index.evidence_quality(index.evidence[item]) for item in evidence))
        ),
    )


def _terminal(branch: Branch, index: SourceIndex) -> RawPath:
    entity = branch.entity_id
    if not branch.cash and branch.reason is None and branch.instrument_id is not None:
        assert branch.instrument_id is not None
        identity = index.identity(branch.instrument_id, branch.listing_id)
        attached = _attach(branch, identity.evidence_ids, index, identity=True)
        if attached is None:
            branch = replace(branch, reason=XrayReason.PROOF_LIMIT)
        else:
            conflict = (
                entity is not None
                and identity.entity_id is not None
                and entity != identity.entity_id
            )
            reason = (
                XrayReason.AMBIGUOUS_IDENTITY
                if conflict
                else identity.reason
                if identity.reason not in (None, XrayReason.MISSING_IDENTITY)
                else None
                if entity is not None
                else identity.reason
            )
            branch = replace(
                attached, reason=reason, quality=quality((attached.quality, identity.quality))
            )
            entity = None if reason is not None else entity or identity.entity_id
    if branch.reason is not None:
        entity = None
    classifications: list[XrayPathClassification] = []
    for dimension in XrayDimension:
        if dimension is XrayDimension.COMPANY:
            continue
        if entity is None:
            classifications.append(
                XrayPathClassification(
                    dimension, None, None, branch.reason or XrayReason.MISSING_CLASSIFICATION, None
                )
            )
            continue
        assignment, evidence = index.classification(entity, dimension)
        attached = _attach(branch, evidence, index)
        if attached is None:
            assignment = XrayPathClassification(dimension, None, None, XrayReason.PROOF_LIMIT, None)
        else:
            branch = replace(
                attached, confidence=confidence((attached.confidence, assignment.confidence))
            )
        classifications.append(assignment)
    inherited_sources = index.consume(branch.evidence_ids, branch.key)
    for reference in branch.sources:
        if reference not in inherited_sources:
            dependency = index.dependencies[reference]
            index.consume_references(
                (reference,), branch.key, dependency.subject_id, (dependency.kind,)
            )
    relative = path_relative(tuple(item.weight for item in branch.edges))
    money = (
        None if branch.money is None else decimal_role(branch.money * relative, "path_coefficient")
    )
    return RawPath(
        branch.key,
        branch.root_key,
        branch.instrument_id,
        entity,
        branch.cash,
        branch.reason,
        branch.edges,
        relative,
        money,
        branch.identity_ids,
        branch.sources,
        tuple(classifications),
        branch.quality,
        branch.confidence,
    )


def _root(item: XrayPosition | XrayCash, value: XrayInput, index: SourceIndex) -> Branch:
    root_key = item.root.key
    subject = (
        item.root.position_id if isinstance(item, XrayPosition) else item.root.snapshot_cash_id
    )
    index.consume_references(
        item.valuation_refs, root_key, subject, (XrayDependencyKind.VALUATION,)
    )
    index.consume_references(
        item.fx_refs, root_key, subject, (XrayDependencyKind.FX, XrayDependencyKind.BROKER_FX)
    )
    references = tuple(sorted(set(item.valuation_refs + item.fx_refs), key=str))
    bound(len(references) <= 256, "root.source_references")
    metric_refs = set(
        item.original_value.source_reference_ids + item.reporting_value.source_reference_ids
    )
    if not metric_refs.issubset(references):
        invalid("root.metric_provenance")
    if item.reporting_value.value is not None:
        if not item.valuation_refs:
            invalid("root.valuation_provenance")
        if item.original_value.value is not None and (
            item.original_value.value.currency != value.reporting_currency and not item.fx_refs
        ):
            invalid("root.fx_provenance")
        money = decimal_role(coefficient18(item.reporting_value.value.amount), "root_coefficient")
    else:
        money = None
    root_metric = index.root_metric(item)
    return Branch(
        root_key,
        root_key,
        item.root.instrument_id if isinstance(item, XrayPosition) else None,
        None,
        item.root.listing_id if isinstance(item, XrayPosition) else None,
        money,
        isinstance(item, XrayCash),
        None,
        (),
        (),
        (),
        (),
        references,
        root_metric.quality,
        root_metric.confidence,
    )


def walk(value: XrayInput, index: SourceIndex) -> Graph:
    with arithmetic():
        ordered: tuple[XrayPosition | XrayCash, ...] = (
            *sorted(value.positions, key=lambda item: str(item.root.position_id)),
            *sorted(value.cash, key=lambda item: str(item.root.snapshot_cash_id)),
        )
        roots = tuple(_root(item, value, index) for item in ordered)
        stack = list(reversed(roots))
        paths: list[RawPath] = []
        visited = 0
        held: dict[UUID, list[str]] = {}
        for item in ordered:
            if isinstance(item, XrayPosition) and item.root.instrument_id in index.definitions:
                held.setdefault(item.root.instrument_id, []).append(item.root.key)
        while stack:
            branch = stack.pop()
            visited += 1
            instrument = branch.instrument_id
            if branch.cash or branch.reason is not None or instrument not in index.definitions:
                paths.append(_terminal(branch, index))
                continue
            assert instrument is not None
            if instrument in branch.ancestry:
                paths.append(_terminal(replace(branch, reason=XrayReason.CYCLE), index))
                continue
            if len(branch.edges) == 4:
                paths.append(_terminal(replace(branch, reason=XrayReason.DEPTH_LIMIT), index))
                continue
            definition = index.pick(
                index.definitions[instrument],
                f"definition:{instrument}",
                XrayDependencyKind.FUND_DEFINITION,
                instrument,
            )
            mapping = index.pick(
                index.mappings.get(instrument, ()),
                f"mapping:{instrument}",
                XrayDependencyKind.FUND_MAPPING,
                instrument,
                XrayReason.MISSING_MAPPING,
            )
            evidence = definition.evidence_ids + mapping.evidence_ids
            attached = _attach(branch, evidence, index)
            if attached is None:
                paths.append(_terminal(replace(branch, reason=XrayReason.PROOF_LIMIT), index))
                continue
            branch = attached
            if definition.value is None or mapping.value is None:
                paths.append(
                    _terminal(replace(branch, reason=definition.reason or mapping.reason), index)
                )
                continue
            candidate = index.pick(
                index.constituents.get(mapping.value.id, ()),
                f"constituents:{mapping.value.id}",
                XrayDependencyKind.CONSTITUENTS,
                mapping.value.id,
            )
            attached = _attach(branch, candidate.evidence_ids, index)
            if attached is None:
                paths.append(_terminal(replace(branch, reason=XrayReason.PROOF_LIMIT), index))
                continue
            branch = attached
            if candidate.value is None:
                paths.append(_terminal(replace(branch, reason=candidate.reason), index))
                continue
            source = candidate.value
            assert source.stated_coverage is not None and source.cash_weight is not None
            assert source.unresolved_weight is not None
            total = sum((item.weight for item in source.holdings), ZERO)
            if total > ONE:
                invalid("constituents.oversum")
            cash_rows = sum(
                (item.weight for item in source.holdings if item.kind is XrayHoldingKind.CASH), ZERO
            )
            unknown_rows = sum(
                (
                    item.weight
                    for item in source.holdings
                    if item.kind is XrayHoldingKind.UNRESOLVED
                ),
                ZERO,
            )
            header_cash = source.cash_weight - cash_rows
            header_unknown = source.unresolved_weight - unknown_rows
            residual = ONE - total - header_cash - header_unknown
            count = len(source.holdings) + sum(
                1 for weight in (header_cash, header_unknown, residual) if weight > ZERO
            )
            if visited + len(stack) + count > value.policy.traversal_policy.max_visited_paths:
                paths.append(_terminal(replace(branch, reason=XrayReason.PATH_LIMIT), index))
                continue
            children: list[Branch] = []
            for holding in sorted(source.holdings, key=lambda item: str(item.id)):
                edge = XrayFundEdge(
                    instrument, mapping.value.id, source.id, holding.id, holding.weight
                )
                children.append(
                    replace(
                        branch,
                        key=f"{branch.key}/holding:{holding.id}",
                        instrument_id=holding.instrument_id,
                        entity_id=holding.entity_id,
                        listing_id=holding.listing_id,
                        identity_ids=tuple(
                            sorted(
                                set(
                                    branch.identity_ids
                                    + ((holding.id,) if holding.entity_id is not None else ())
                                ),
                                key=str,
                            )
                        ),
                        confidence=confidence((branch.confidence, holding.confidence)),
                        cash=holding.kind is XrayHoldingKind.CASH,
                        reason=XrayReason.SOURCE_REMAINDER
                        if holding.kind is XrayHoldingKind.UNRESOLVED
                        else None,
                        edges=(*branch.edges, edge),
                        ancestry=(*branch.ancestry, instrument),
                    )
                )
            header_edges: tuple[
                tuple[Literal["header_cash", "header_unresolved", "remainder"], Decimal], ...
            ] = (
                ("header_cash", header_cash),
                ("header_unresolved", header_unknown),
                ("remainder", residual),
            )
            for origin, weight in header_edges:
                if weight <= ZERO:
                    continue
                edge = XrayFundEdge(instrument, mapping.value.id, source.id, None, weight, origin)
                children.append(
                    replace(
                        branch,
                        key=f"{branch.key}/{origin}:{source.id}",
                        instrument_id=None,
                        entity_id=None,
                        listing_id=None,
                        cash=origin == "header_cash",
                        reason=None if origin == "header_cash" else XrayReason.SOURCE_REMAINDER,
                        edges=(*branch.edges, edge),
                        ancestry=(*branch.ancestry, instrument),
                    )
                )
            for offset, child in enumerate(children):
                if len(child.identity_ids) > 256:
                    children[offset] = replace(
                        child,
                        instrument_id=None,
                        entity_id=None,
                        reason=XrayReason.PROOF_LIMIT,
                        identity_ids=branch.identity_ids,
                    )
            parent_r = path_relative(tuple(item.weight for item in branch.edges))
            child_r = sum(
                (path_relative(tuple(item.weight for item in child.edges)) for child in children),
                ZERO,
            )
            if child_r != parent_r:
                invalid("graph.unit_conservation")
            if branch.money is not None and child_r * branch.money != parent_r * branch.money:
                invalid("graph.money_conservation")
            stack.extend(reversed(children))
        by_root: dict[str, list[RawPath]] = defaultdict(list)
        for path in paths:
            by_root[path.root_key].append(path)
        for root in roots:
            selected = tuple(by_root[root.root_key])
            if sum((item.relative_coefficient for item in selected), ZERO) != UNIT:
                invalid("root.unit_conservation")
            if root.money is not None and sum(
                (item.money_coefficient for item in selected if item.money_coefficient is not None),
                ZERO,
            ) != (root.money * UNIT):
                invalid("root.money_conservation")
        return Graph(
            tuple(paths),
            tuple(XrayRootExact(item.root_key, item.money) for item in roots),
            tuple(
                XrayHeldFund(instrument, tuple(keys), keys[0])
                for instrument, keys in sorted(held.items(), key=lambda item: str(item[0]))
            ),
            visited,
        )
