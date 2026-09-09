"""Calculation-owned evidence indexes and dated, provider-first source decisions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.xray import (
    ConcentrationThresholdPolicy,
    XrayBrokerFx,
    XrayCash,
    XrayClassificationAssignment,
    XrayDependencyKind,
    XrayDimension,
    XrayEntityEvidence,
    XrayEvidence,
    XrayFxLeg,
    XrayInput,
    XrayMoneyMetric,
    XrayPosition,
    XrayReason,
    XraySourceState,
    XraySubjectKind,
)
from trading212_domain.xray_result import (
    XrayClassificationDecision,
    XrayPathClassification,
    XraySelection,
    XraySourceUse,
)
from trading212_domain.xray_validation import bound, invalid


class Evidenced(Protocol):
    @property
    def evidence(self) -> XrayEvidence: ...


@dataclass(frozen=True, slots=True)
class Assignment:
    value: XrayClassificationAssignment | None
    evidence: XrayEvidence


@dataclass(frozen=True, slots=True)
class Identity:
    entity_id: UUID | None
    evidence_ids: tuple[UUID, ...]
    reason: XrayReason | None
    quality: QualityState


@dataclass(frozen=True, slots=True)
class Pick[T]:
    value: T | None
    evidence_ids: tuple[UUID, ...]
    reason: XrayReason | None
    quality: QualityState


_QUALITY_ORDER = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.UNRECONCILED: 3,
    QualityState.PARTIAL: 4,
    QualityState.FAILED: 5,
}


def quality(states: tuple[QualityState, ...]) -> QualityState:
    return max(states, key=_QUALITY_ORDER.__getitem__, default=QualityState.FRESH)


def confidence(values: tuple[Decimal | None, ...]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    return min(value for value in values if value is not None)


def _semantic(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return tuple(
            (item.name, _semantic(getattr(value, item.name)))
            for item in fields(value)
            if item.name not in ("id", "evidence")
        )
    if isinstance(value, tuple):
        return tuple(sorted((_semantic(item) for item in value), key=repr))
    return value


class SourceIndex:
    """No state escapes this one calculation; result records retain actual decisions."""

    def __init__(self, value: XrayInput) -> None:
        self.value = value
        self.broker_fx = {item.root_key: item for item in value.broker_fx}
        self.licensed_fx = {item.consumer_key: item for item in value.licensed_fx}
        self.dependencies = {item.id: item for item in value.source_dependencies}
        self.evidence: dict[UUID, XrayEvidence] = {}
        self.selections: dict[str, XraySelection] = {}
        self.uses: dict[tuple[str, str, str, str], XraySourceUse] = {}
        if isinstance(value.policy.thresholds, ConcentrationThresholdPolicy):
            self.consume_references(
                (value.policy.thresholds.source_reference_id,),
                f"threshold:{value.policy.thresholds.id}",
                value.policy.thresholds.id,
                (XrayDependencyKind.THRESHOLD,),
            )
        for reference in value.reconciliation.source_reference_ids:
            dependency = self.dependencies.get(reference)
            if dependency is None or dependency.kind is not XrayDependencyKind.RECONCILIATION:
                invalid("reconciliation.source_binding")
            self.consume_references(
                (reference,),
                "reconciliation",
                dependency.subject_id,
                (XrayDependencyKind.RECONCILIATION,),
            )
        self.consume_references(
            value.portfolio_total.source_reference_ids,
            "portfolio_total",
            value.snapshot_id,
            (XrayDependencyKind.VALUATION, XrayDependencyKind.FX),
        )
        self.definitions = self._group(value.fund_definitions, "instrument_id")
        self.mappings = self._group(value.fund_mappings, "fund_instrument_id")
        self.constituents = self._group(value.constituent_candidates, "fund_mapping_id")
        self.entities = self._group(value.entity_evidence, "instrument_id")
        from trading212_domain.xray import XrayRelationshipKind

        self.relationships = self._group(
            tuple(
                item
                for item in value.relationship_versions
                if item.kind
                in (XrayRelationshipKind.SHARE_CLASS, XrayRelationshipKind.DEPOSITARY_RECEIPT)
            ),
            "instrument_id",
        )
        self.listing_relationships = self._group(
            tuple(
                item
                for item in value.relationship_versions
                if item.kind is XrayRelationshipKind.LISTING_OF
            ),
            "listing_id",
        )
        # Issuer-parent evidence remains in the immutable input and dependency inventory.
        # explicit_economic_entity_and_receipt_v1 does not assert equity equivalence
        # from corporate ownership, so it never follows those edges into money aggregation.
        self.assignments: dict[tuple[XraySubjectKind, UUID, XrayDimension], list[Assignment]] = (
            defaultdict(list)
        )
        for group, kind in (
            (value.fund_definitions, XrayDependencyKind.FUND_DEFINITION),
            (value.fund_mappings, XrayDependencyKind.FUND_MAPPING),
            (value.constituent_candidates, XrayDependencyKind.CONSTITUENTS),
            (value.entity_evidence, XrayDependencyKind.IDENTITY),
            (value.relationship_versions, XrayDependencyKind.RELATIONSHIP),
            (value.classification_batches, XrayDependencyKind.CLASSIFICATION),
        ):
            for item in group:
                self._register(item.evidence, kind)
        selected_taxonomy = {item.dimension: item for item in value.policy.taxonomy_versions}
        for batch in value.classification_batches:
            for assignment in batch.assignments:
                taxonomy = selected_taxonomy[assignment.dimension]
                if (assignment.taxonomy_id, assignment.taxonomy_version) != (
                    taxonomy.taxonomy_id,
                    taxonomy.version,
                ):
                    continue
                self.assignments[
                    (assignment.subject_kind, assignment.subject_id, assignment.dimension)
                ].append(Assignment(assignment, batch.evidence))
            assigned_keys = {
                (
                    row.subject_kind,
                    row.subject_id,
                    row.dimension,
                    row.taxonomy_id,
                    row.taxonomy_version,
                )
                for row in batch.assignments
            }
            for target in batch.requested_subjects:
                taxonomy = selected_taxonomy[target.dimension]
                if (target.taxonomy_id, target.taxonomy_version) != (
                    taxonomy.taxonomy_id,
                    taxonomy.version,
                ):
                    continue
                key = (
                    target.subject_kind,
                    target.subject_id,
                    target.dimension,
                    target.taxonomy_id,
                    target.taxonomy_version,
                )
                if key not in assigned_keys:
                    self.assignments[
                        (target.subject_kind, target.subject_id, target.dimension)
                    ].append(Assignment(None, batch.evidence))
        self.quality_evaluated_at = (
            value.valuation_at
            if value.policy.freshness_policy.evaluation_basis == "valuation_at"
            else value.source_cutoff_at
        )
        self.identities: dict[tuple[UUID, UUID | None], Identity] = {}
        self.instrument_identities: dict[UUID, list[Identity]] = defaultdict(list)
        self.entity_instruments: dict[UUID, set[UUID]] = defaultdict(set)
        self.classification_decisions: dict[str, XrayClassificationDecision] = {}
        self.classification_cache: dict[
            tuple[UUID, XrayDimension], tuple[XrayPathClassification, tuple[UUID, ...]]
        ] = {}
        identity_keys = {(item.instrument_id, item.listing_id) for item in value.entity_evidence}
        identity_keys.update(
            (item.root.instrument_id, item.root.listing_id) for item in value.positions
        )
        identity_keys.update(
            (item.instrument_id, item.listing_id)
            for candidate in value.constituent_candidates
            for item in candidate.holdings
            if item.instrument_id is not None
        )
        for instrument, listing in sorted(
            identity_keys, key=lambda item: (str(item[0]), str(item[1]))
        ):
            self.identity(instrument, listing)
        for instrument in sorted(set(self.entities) | set(self.relationships), key=str):
            identity = self.identity(instrument, None)
            if identity.entity_id is not None:
                self.entity_instruments[identity.entity_id].add(instrument)

    @staticmethod
    def _group[T](items: tuple[T, ...], field: str) -> dict[UUID, tuple[T, ...]]:
        grouped: dict[UUID, list[T]] = defaultdict(list)
        for item in items:
            grouped[getattr(item, field)].append(item)
        return {key: tuple(rows) for key, rows in grouped.items()}

    def _register(self, evidence: XrayEvidence, kind: XrayDependencyKind) -> None:
        dependency = self.dependencies.get(evidence.source_reference_id)
        if dependency is None or dependency.kind is not kind:
            invalid("evidence.source_binding")
        previous = self.evidence.setdefault(evidence.id, evidence)
        if previous != evidence:
            invalid("evidence.identity")

    def eligible(self, evidence: XrayEvidence) -> bool:
        return (
            evidence.effective_at <= self.value.valuation_at
            and evidence.first_known_at <= self.value.source_cutoff_at
            and (evidence.valid_until is None or self.value.valuation_at < evidence.valid_until)
        )

    def stale(self, evidence: XrayEvidence) -> bool:
        age = self.quality_evaluated_at.value - evidence.effective_at.value
        return age > timedelta(seconds=self.value.policy.freshness_policy.stale_after_seconds)

    def fx_quality(self, root_key: str) -> QualityState:
        broker = self.broker_fx.get(root_key)
        conversion = self.licensed_fx.get(root_key)
        quotes: tuple[XrayBrokerFx | XrayFxLeg, ...] = (
            *((broker,) if broker is not None else ()),
            *(conversion.legs if conversion is not None else ()),
        )
        states: list[QualityState] = []
        for quote in quotes:
            states.append(quote.quality)
            if quote.rate is None:
                states.append(QualityState.PARTIAL)
            if self.quality_evaluated_at.value - quote.observed_at.value > timedelta(
                seconds=self.value.policy.freshness_policy.stale_after_seconds
            ):
                states.append(QualityState.STALE)
        return quality(tuple(states))

    def root_metric(self, item: XrayPosition | XrayCash) -> XrayMoneyMetric:
        """Apply sourced FX metadata without mixing it into exact coefficient records."""
        quote = self.broker_fx.get(item.root.key)
        certainty = item.reporting_value.confidence
        if quote is not None:
            certainty = confidence((certainty, quote.confidence))
        return replace(
            item.reporting_value,
            quality=quality((item.reporting_value.quality, self.fx_quality(item.root.key))),
            confidence=certainty,
        )

    def evidence_quality(self, evidence: XrayEvidence) -> QualityState:
        stale = self.stale(evidence)
        return quality((evidence.quality, QualityState.STALE if stale else QualityState.FRESH))

    def pick[T: Evidenced](
        self,
        records: tuple[T, ...],
        key: str,
        kind: XrayDependencyKind,
        subject: UUID,
        missing: XrayReason = XrayReason.MISSING_SOURCE,
    ) -> Pick[T]:
        candidates = tuple(item for item in records if self.eligible(item.evidence))
        considered = tuple(sorted({item.evidence.id for item in candidates}, key=str))
        preferred: tuple[T, ...] = ()
        for provider in self.value.policy.provider_selection_policy.provider_order:
            preferred = tuple(
                item
                for item in candidates
                if self.dependencies[item.evidence.source_reference_id].provider_id == provider
            )
            if preferred:
                break
        reason: XrayReason | None = missing
        selected: tuple[UUID, ...] = ()
        chosen: T | None = None
        state = QualityState.PARTIAL
        if preferred:
            effective = max(item.evidence.effective_at for item in preferred)
            recent = tuple(item for item in preferred if item.evidence.effective_at == effective)
            revision = max(item.evidence.revision for item in recent)
            final = tuple(item for item in recent if item.evidence.revision == revision)
            first = min(final, key=lambda item: str(item.evidence.id))
            proofs = {
                repr(
                    (
                        _semantic(item),
                        item.evidence.state,
                        item.evidence.quality,
                        item.evidence.confidence,
                    )
                )
                for item in final
            }
            selected = tuple(sorted({item.evidence.id for item in final}, key=str))
            if len(proofs) != 1:
                reason = XrayReason.AMBIGUOUS_SOURCE
            elif first.evidence.state is XraySourceState.GAP:
                reason = XrayReason.SOURCE_GAP
            elif first.evidence.quality is QualityState.FAILED:
                reason = XrayReason.MISSING_SOURCE
            elif isinstance(first, Assignment) and first.value is None:
                # Complete request membership proves this target's gap even in a
                # batch which returned available assignments for other subjects.
                reason = XrayReason.SOURCE_GAP
            else:
                chosen, reason = first, None
                state = self.evidence_quality(first.evidence)
        selection = XraySelection(key, kind, subject, considered, selected, reason)
        previous = self.selections.setdefault(key, selection)
        if previous != selection:
            invalid("selection.identity")
        return Pick(chosen, selected, reason, state)

    def consume(self, evidence_ids: tuple[UUID, ...], consumer: str) -> tuple[UUID, ...]:
        references: set[UUID] = set()
        for evidence_id in evidence_ids:
            evidence = self.evidence[evidence_id]
            dependency = self.dependencies[evidence.source_reference_id]
            references.add(dependency.id)
            item = XraySourceUse(
                consumer, dependency.kind, dependency.id, evidence_id, dependency.subject_id
            )
            self.uses[(consumer, dependency.kind.value, str(dependency.id), str(evidence_id))] = (
                item
            )
            bound(len(self.uses) <= 100_000, "selected_uses")
        return tuple(sorted(references, key=str))

    def consume_references(
        self,
        references: tuple[UUID, ...],
        consumer: str,
        subject: UUID,
        kinds: tuple[XrayDependencyKind, ...],
    ) -> None:
        for reference in references:
            dependency = self.dependencies.get(reference)
            if dependency is None or dependency.kind not in kinds:
                invalid("root.source_binding")
            from trading212_domain.xray import XrayReferenceKind

            source_fx = (
                dependency.kind in (XrayDependencyKind.FX, XrayDependencyKind.BROKER_FX)
                and dependency.subject_kind is XraySubjectKind.SOURCE_RECORD
            )
            valuation_proof = (
                dependency.kind is XrayDependencyKind.VALUATION
                and dependency.reference.kind
                in (
                    XrayReferenceKind.PORTFOLIO_SNAPSHOT,
                    XrayReferenceKind.CALCULATION_RUN,
                    XrayReferenceKind.BROKER_SOURCE_RECORD,
                    XrayReferenceKind.PRICE_SNAPSHOT,
                    XrayReferenceKind.PRICE_OBSERVATION,
                )
            )
            if dependency.subject_id != subject and not (source_fx or valuation_proof):
                invalid("root.source_binding")
            item = XraySourceUse(consumer, dependency.kind, reference, None, dependency.subject_id)
            self.uses[(consumer, dependency.kind.value, str(reference), "")] = item
            bound(len(self.uses) <= 100_000, "selected_uses")

    def identity(self, instrument: UUID, listing: UUID | None) -> Identity:
        key = (instrument, listing)
        if key in self.identities:
            return self.identities[key]
        candidates: tuple[XrayEntityEvidence, ...] = self.entities.get(instrument, ())
        applicable = tuple(item for item in candidates if item.listing_id == listing)
        if listing is not None and not any(self.eligible(item.evidence) for item in applicable):
            applicable = tuple(item for item in candidates if item.listing_id is None)
        direct = self.pick(
            applicable,
            f"identity:{instrument}:{listing}",
            XrayDependencyKind.IDENTITY,
            instrument,
            XrayReason.MISSING_IDENTITY,
        )
        relation = self.pick(
            self.relationships.get(instrument, ()),
            f"relationship:{instrument}",
            XrayDependencyKind.RELATIONSHIP,
            instrument,
            XrayReason.MISSING_IDENTITY,
        )
        listing_pick = (
            None
            if listing is None
            else self.pick(
                self.listing_relationships.get(listing, ()),
                f"listing:{listing}",
                XrayDependencyKind.RELATIONSHIP,
                listing,
                XrayReason.MISSING_IDENTITY,
            )
        )
        listing_ids = () if listing_pick is None else listing_pick.evidence_ids
        ids = tuple(sorted(set(direct.evidence_ids + relation.evidence_ids + listing_ids), key=str))
        entities = {
            item.entity_id
            for item in (direct.value, relation.value)
            if item is not None and item.entity_id is not None
        }
        conflict = len(entities) > 1 or any(
            reason in (XrayReason.AMBIGUOUS_SOURCE, XrayReason.SOURCE_GAP)
            for reason in (
                direct.reason,
                relation.reason,
                None if listing_pick is None else listing_pick.reason,
            )
        )
        if (
            listing_pick is not None
            and listing_pick.value is not None
            and (listing_pick.value.instrument_id != instrument)
        ):
            conflict = True
        unavailable = any(
            item is not None and item.reason is XrayReason.MISSING_SOURCE
            for item in (direct, relation, listing_pick)
        )
        entity = (
            next(iter(entities))
            if len(entities) == 1 and not conflict and not unavailable
            else None
        )
        result = Identity(
            entity,
            ids,
            None
            if entity is not None
            else (
                XrayReason.AMBIGUOUS_IDENTITY
                if conflict
                else XrayReason.MISSING_SOURCE
                if unavailable
                else XrayReason.MISSING_IDENTITY
            ),
            quality(
                tuple(
                    item.quality
                    for item in (direct, relation, listing_pick)
                    if item is not None and item.value is not None
                )
            ),
        )
        self.identities[key] = result
        if entity is not None:
            self.entity_instruments[entity].add(instrument)
            self.instrument_identities[instrument].append(result)
        return result

    def classification(
        self, entity: UUID, dimension: XrayDimension
    ) -> tuple[XrayPathClassification, tuple[UUID, ...]]:
        key = (entity, dimension)
        if key in self.classification_cache:
            return self.classification_cache[key]
        explicit = self.pick(
            tuple(self.assignments.get((XraySubjectKind.ENTITY, entity, dimension), ())),
            f"classification:entity:{entity}:{dimension.value}",
            XrayDependencyKind.CLASSIFICATION,
            entity,
            XrayReason.MISSING_CLASSIFICATION,
        )
        evidence = set(explicit.evidence_ids)
        assignments: list[XrayClassificationAssignment] = []
        reason: XrayReason | None = explicit.reason
        if explicit.value is not None:
            assert explicit.value.value is not None
            assignments.append(explicit.value.value)
        elif explicit.reason is XrayReason.MISSING_CLASSIFICATION:
            for instrument in sorted(self.entity_instruments.get(entity, ()), key=str):
                identity_rows = tuple(self.instrument_identities.get(instrument, ()))
                if {row.entity_id for row in identity_rows} != {entity}:
                    continue
                identity_ids = tuple(
                    sorted({item for row in identity_rows for item in row.evidence_ids}, key=str)
                )
                candidate = self.pick(
                    tuple(
                        self.assignments.get(
                            (XraySubjectKind.INSTRUMENT, instrument, dimension), ()
                        )
                    ),
                    f"classification:instrument:{instrument}:{dimension.value}",
                    XrayDependencyKind.CLASSIFICATION,
                    instrument,
                    XrayReason.MISSING_CLASSIFICATION,
                )
                if candidate.value is not None:
                    assert candidate.value.value is not None
                    evidence.update(identity_ids)
                    evidence.update(candidate.evidence_ids)
                    assignments.append(candidate.value.value)
                elif candidate.reason not in (None, XrayReason.MISSING_CLASSIFICATION):
                    evidence.update(candidate.evidence_ids)
                    reason = XrayReason.AMBIGUOUS_CLASSIFICATION
            if assignments and reason is not XrayReason.AMBIGUOUS_CLASSIFICATION:
                reason = None
        if len({item.bucket_key for item in assignments}) > 1:
            reason = XrayReason.AMBIGUOUS_CLASSIFICATION
        decision_key = f"classification:{entity}:{dimension.value}"
        if len(evidence) > 256 or len(assignments) > 256:
            # A capacity failure retains no favorable subset of a consensus proof.
            evidence, assignments, reason = set(), [], XrayReason.PROOF_LIMIT
        bucket = assignments[0].bucket_key if assignments and reason is None else None
        evidence_ids = tuple(sorted(evidence, key=str))
        references = self.consume(evidence_ids, decision_key)
        selected_confidence = confidence(
            tuple(item.confidence for item in assignments)
            + tuple(self.evidence[item].confidence for item in evidence_ids)
        )
        decision = XrayClassificationDecision(
            decision_key,
            entity,
            dimension,
            bucket,
            tuple(sorted({item.id for item in assignments}, key=str)),
            evidence_ids,
            references,
            None if bucket is not None else reason or XrayReason.MISSING_CLASSIFICATION,
            selected_confidence,
        )
        self.classification_decisions[decision_key] = decision
        result = (
            XrayPathClassification(
                dimension, bucket, decision_key, decision.reason, selected_confidence
            ),
            evidence_ids,
        )
        self.classification_cache[key] = result
        return result
