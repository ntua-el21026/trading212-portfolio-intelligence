"""Extract immutable scenario facts from the complete saved X-ray proof, without recalculation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Literal
from uuid import UUID

from .errors import DomainError, fail_validation
from .scenario import MAX_SCENARIO_BYTES, MAX_SCENARIO_COMPONENTS, ScenarioReason
from .scenario_result import (
    ScenarioClassificationFact,
    ScenarioCurrencyFact,
    ScenarioMoneyMetric,
    ScenarioSubjectFact,
    ScenarioTerminalExposure,
)
from .scenario_validation import scenario_bound, unique
from .values import CurrencyCode
from .xray import (
    CashRoot,
    PositionRoot,
    XrayClassificationAssignment,
    XrayClassificationBatch,
    XrayDimension,
    XrayEvidence,
    XrayHoldingKind,
    XrayInput,
    XrayReason,
    XraySourceState,
    XraySubjectKind,
)
from .xray_codec import encode_xray_component, encode_xray_input, encode_xray_result
from .xray_result import XrayCalculation, XrayClassificationDecision, XrayTerminalPath


def _reason(reason: XrayReason | None, *, classification: bool = False) -> ScenarioReason:
    if classification:
        return (
            ScenarioReason.AMBIGUOUS_CLASSIFICATION
            if reason is XrayReason.AMBIGUOUS_CLASSIFICATION
            else ScenarioReason.MISSING_CLASSIFICATION
        )
    return (
        ScenarioReason.AMBIGUOUS_IDENTITY
        if reason is XrayReason.AMBIGUOUS_IDENTITY
        else ScenarioReason.MISSING_IDENTITY
    )


@dataclass(frozen=True, slots=True)
class _Classification:
    decision: XrayClassificationDecision | None
    taxonomy_id: UUID | None
    taxonomy_version: str | None
    reason: ScenarioReason | None
    upstream_reason: XrayReason | None


class _Proof:
    def __init__(self, source: XrayInput, result: XrayCalculation) -> None:
        self.source, self.result = source, result
        self.roots: dict[str, PositionRoot | CashRoot] = {
            item.root.key: item.root for item in source.positions
        }
        self.roots.update({item.root.key: item.root for item in source.cash})
        if len(self.roots) != len(source.positions) + len(source.cash):
            fail_validation("Scenario X-ray root identities are duplicated.")
        self.decisions = {item.key: item for item in result.classification_decisions}
        if len(self.decisions) != len(result.classification_decisions):
            fail_validation("Scenario X-ray classification identities are duplicated.")
        self.assignments: dict[
            UUID, tuple[XrayClassificationAssignment, XrayClassificationBatch]
        ] = {}
        self.evidence: dict[UUID, XrayEvidence] = {}
        for evidence in (
            *(item.evidence for item in source.fund_definitions),
            *(item.evidence for item in source.fund_mappings),
            *(item.evidence for item in source.constituent_candidates),
            *(item.evidence for item in source.entity_evidence),
            *(item.evidence for item in source.relationship_versions),
            *(item.evidence for item in source.classification_batches),
        ):
            existing = self.evidence.setdefault(evidence.id, evidence)
            if existing != evidence:
                fail_validation("Scenario X-ray evidence identity conflicts.")
        for batch in source.classification_batches:
            for assignment in batch.assignments:
                if assignment.id in self.assignments:
                    fail_validation("Scenario X-ray assignment identity conflicts.")
                self.assignments[assignment.id] = (assignment, batch)
        self.candidates = {item.id: item for item in source.constituent_candidates}
        self.holdings = {
            (candidate.id, holding.id): holding
            for candidate in source.constituent_candidates
            for holding in candidate.holdings
        }
        self.dependencies = {item.id: item for item in source.source_dependencies}
        self.taxonomies = {item.dimension: item for item in source.policy.taxonomy_versions}
        self.cache: dict[tuple[str, XrayDimension], _Classification] = {}
        for item in self.evidence.values():
            if item.source_reference_id not in self.dependencies:
                fail_validation("Scenario X-ray evidence source is not captured.")

    def references(self, references: tuple[UUID, ...]) -> None:
        unique(references, "source_reference_ids")
        if any(item not in self.dependencies for item in references):
            fail_validation("Scenario X-ray source reference is not captured.")

    def classification(self, path: XrayTerminalPath, dimension: XrayDimension) -> _Classification:
        choices = [item for item in path.classifications if item.dimension is dimension]
        if len(choices) > 1:
            fail_validation("Scenario X-ray path classification is duplicated.")
        if not choices:
            return _Classification(None, None, None, ScenarioReason.MISSING_CLASSIFICATION, None)
        selected = choices[0]
        if selected.decision_key is None:
            if selected.bucket_key is not None:
                fail_validation("Selected scenario classification has no decision.")
            return _Classification(
                None, None, None, _reason(selected.reason, classification=True), selected.reason
            )
        decision = self.decisions.get(selected.decision_key)
        if decision is None or (
            decision.dimension != dimension
            or decision.entity_id != path.entity_id
            or decision.bucket_key != selected.bucket_key
            or decision.reason != selected.reason
        ):
            fail_validation("Scenario X-ray classification decision membership differs.")
        cache_key = (decision.key, dimension)
        if cache_key in self.cache:
            return self.cache[cache_key]
        self.references(decision.source_reference_ids)
        if any(item not in self.evidence for item in decision.evidence_ids):
            fail_validation("Scenario selected classification evidence is not captured.")
        if set(decision.source_reference_ids) != {
            self.evidence[item].source_reference_id for item in decision.evidence_ids
        }:
            fail_validation("Scenario selected classification source membership differs.")
        witnesses = []
        for identity in decision.assignment_ids:
            pair = self.assignments.get(identity)
            if pair is None:
                fail_validation("Scenario selected classification assignment is not captured.")
            assignment, batch = pair
            if (
                assignment.dimension != dimension
                or batch.evidence.id not in decision.evidence_ids
                or (
                    assignment.subject_kind is XraySubjectKind.ENTITY
                    and assignment.subject_id != decision.entity_id
                )
                or assignment.subject_kind
                not in (XraySubjectKind.ENTITY, XraySubjectKind.INSTRUMENT)
            ):
                fail_validation("Scenario selected classification assignment membership differs.")
            # The saved decision retains instrument-consensus identity chains.
            # Re-running that selection here could replace immutable membership with current facts.
            witnesses.append((assignment, batch.evidence))
        taxonomy = self.taxonomies.get(dimension)
        mismatch = taxonomy is None or any(
            assignment.taxonomy_id != taxonomy.taxonomy_id
            or assignment.taxonomy_version != taxonomy.version
            for assignment, _ in witnesses
        )
        reason = (
            _reason(decision.reason, classification=True) if decision.bucket_key is None else None
        )
        if mismatch:
            reason = ScenarioReason.INCOMPATIBLE_TAXONOMY
        elif decision.bucket_key is not None:
            if not witnesses or any(
                assignment.bucket_key != decision.bucket_key for assignment, _ in witnesses
            ):
                fail_validation("Scenario selected classification bucket witnesses differ.")
            if any(
                evidence.state is not XraySourceState.AVAILABLE
                or evidence.effective_at > self.source.valuation_at
                or evidence.first_known_at > self.source.source_cutoff_at
                or (
                    evidence.valid_until is not None
                    and evidence.valid_until <= self.source.valuation_at
                )
                for _, evidence in witnesses
            ):
                fail_validation(
                    "Scenario selected classification evidence is unavailable at its pins."
                )
        result = _Classification(
            decision,
            None if taxonomy is None else taxonomy.taxonomy_id,
            None if taxonomy is None else taxonomy.version,
            reason,
            selected.reason,
        )
        self.cache[cache_key] = result
        return result

    def classification_fact(
        self, path: XrayTerminalPath, dimension: Literal["sector", "region"]
    ) -> ScenarioClassificationFact:
        fact = (
            self.classification(path, XrayDimension(dimension)) if not path.explicit_cash else None
        )
        decision = None if fact is None else fact.decision
        return ScenarioClassificationFact(
            dimension=dimension,
            state="not_applicable"
            if fact is None
            else "known"
            if fact.reason is None
            else "unknown",
            taxonomy_id=None if fact is None else fact.taxonomy_id,
            taxonomy_version=None if fact is None else fact.taxonomy_version,
            bucket_key=decision.bucket_key
            if decision is not None and fact is not None and fact.reason is None
            else None,
            decision_key=None if decision is None else decision.key,
            assignment_ids=() if decision is None else decision.assignment_ids,
            evidence_ids=() if decision is None else decision.evidence_ids,
            source_reference_ids=() if decision is None else decision.source_reference_ids,
            reason=None if fact is None else fact.reason,
            upstream_reason=None if fact is None else fact.upstream_reason,
            confidence=None if decision is None else decision.confidence,
        )

    def currency(
        self, path: XrayTerminalPath, root: PositionRoot | CashRoot
    ) -> ScenarioCurrencyFact:
        value = ScenarioCurrencyFact(
            state="unknown",
            currency=None,
            basis="unknown",
            decision_key=None,
            taxonomy_id=None,
            taxonomy_version=None,
            cash_id=None,
            candidate_id=None,
            holding_id=None,
            assignment_ids=(),
            evidence_ids=(),
            source_reference_ids=path.source_reference_ids,
            reason=ScenarioReason.MISSING_ECONOMIC_CURRENCY,
            upstream_reason=path.unresolved_reason,
        )
        if path.explicit_cash:
            if isinstance(root, CashRoot) and not path.fund_edges:
                return replace(
                    value,
                    state="known",
                    currency=root.original_currency,
                    basis="snapshot_cash",
                    cash_id=root.snapshot_cash_id,
                    reason=None,
                    upstream_reason=None,
                )
            if not path.fund_edges:
                return value
            edge = path.fund_edges[-1]
            candidate = self.candidates.get(edge.candidate_id)
            if candidate is None or candidate.fund_mapping_id != edge.mapping_id:
                fail_validation("Scenario constituent cash candidate is not captured.")
            value = replace(value, candidate_id=candidate.id, holding_id=edge.holding_id)
            if edge.holding_id is None:
                return value
            holding = self.holdings.get((candidate.id, edge.holding_id))
            if holding is None or holding.kind is not XrayHoldingKind.CASH:
                fail_validation("Scenario constituent cash holding membership differs.")
            if holding.source_currency is None:
                return value
            return replace(
                value,
                state="known",
                currency=holding.source_currency,
                basis="constituent_cash",
                reason=None,
                upstream_reason=None,
            )
        fact = self.classification(path, XrayDimension.CURRENCY)
        decision = fact.decision
        value = replace(
            value,
            taxonomy_id=fact.taxonomy_id,
            taxonomy_version=fact.taxonomy_version,
            upstream_reason=fact.upstream_reason,
        )
        if decision is not None:
            value = replace(
                value,
                decision_key=decision.key,
                assignment_ids=decision.assignment_ids,
                evidence_ids=decision.evidence_ids,
                source_reference_ids=decision.source_reference_ids,
            )
        if fact.reason is None and decision is not None and decision.bucket_key is not None:
            try:
                currency = CurrencyCode(decision.bucket_key)
            except DomainError:
                return replace(value, reason=ScenarioReason.UNSUPPORTED_ECONOMIC_CURRENCY)
            return replace(
                value,
                state="known",
                currency=currency,
                basis="economic_classification",
                reason=None,
            )
        if fact.reason is ScenarioReason.INCOMPATIBLE_TAXONOMY:
            return replace(value, reason=fact.reason)
        return value


def _subject(
    path: XrayTerminalPath, dimension: Literal["instrument", "entity"]
) -> ScenarioSubjectFact:
    identity = path.instrument_id if dimension == "instrument" else path.entity_id
    state: Literal["known", "unknown", "not_applicable"] = (
        "not_applicable" if path.explicit_cash else "known" if identity is not None else "unknown"
    )
    return ScenarioSubjectFact(
        dimension=dimension,
        state=state,
        subject_id=identity if state == "known" else None,
        reason=_reason(path.unresolved_reason) if state == "unknown" else None,
        upstream_reason=path.unresolved_reason if state == "unknown" else None,
        identity_decision_ids=path.identity_decision_ids,
        source_reference_ids=path.source_reference_ids,
    )


def extract_scenario_exposures(
    source: XrayInput, result: XrayCalculation
) -> tuple[ScenarioTerminalExposure, ...]:
    """One original published terminal value per original path, with full identity membership."""
    if type(source) is not XrayInput or type(result) is not XrayCalculation:
        fail_validation("Complete saved X-ray input and result are required.")
    scenario_bound(len(result.terminal_paths) <= MAX_SCENARIO_COMPONENTS, "terminal_paths")
    source_bytes, result_bytes = encode_xray_input(source), encode_xray_result(result)
    scenario_bound(len(source_bytes) + len(result_bytes) <= MAX_SCENARIO_BYTES, "xray.proof_bytes")
    if (
        result.input_digest != sha256(source_bytes).hexdigest()
        or result.owner_id != source.owner_id
        or result.account_id != source.account_id
        or result.snapshot_id != source.snapshot_id
        or result.reporting_currency != source.reporting_currency
        or encode_xray_component(result.policy) != encode_xray_component(source.policy)
        or result.valuation_at != source.valuation_at
        or result.source_cutoff_at != source.source_cutoff_at
    ):
        fail_validation("Scenario saved X-ray identities differ.")
    unique(tuple(item.key for item in result.terminal_paths), "terminal_paths")
    proof = _Proof(source, result)
    exposures = []
    for path in sorted(result.terminal_paths, key=lambda item: item.key):
        root = proof.roots.get(path.root_key)
        if root is None:
            fail_validation("Scenario terminal root is not captured.")
        proof.references(path.source_reference_ids)
        constituent_identity_ids = {
            edge.holding_id
            for edge in path.fund_edges
            if edge.holding_id is not None
            and (holding := proof.holdings.get((edge.candidate_id, edge.holding_id))) is not None
            and holding.entity_id is not None
        }
        if any(
            item not in proof.evidence and item not in constituent_identity_ids
            for item in path.identity_decision_ids
        ):
            fail_validation("Scenario terminal identity evidence is not captured.")
        metric = path.reporting_value
        exposure = ScenarioTerminalExposure(
            path_key=path.key,
            root_key=path.root_key,
            root_kind="position" if isinstance(root, PositionRoot) else "cash",
            position_id=root.position_id if isinstance(root, PositionRoot) else None,
            snapshot_cash_id=root.snapshot_cash_id if isinstance(root, CashRoot) else None,
            root_instrument_id=root.instrument_id if isinstance(root, PositionRoot) else None,
            explicit_cash=path.explicit_cash,
            instrument=_subject(path, "instrument"),
            entity=_subject(path, "entity"),
            sector=proof.classification_fact(path, "sector"),
            region=proof.classification_fact(path, "region"),
            economic_currency=proof.currency(path, root),
            pre_value=ScenarioMoneyMetric(
                value=metric.value,
                quality=metric.quality,
                reason=ScenarioReason.MISSING_VALUE if metric.value is None else None,
                confidence=metric.confidence,
                source_reference_ids=metric.source_reference_ids,
            ),
            quality=path.quality,
            confidence=path.confidence,
            upstream_reason=metric.reason or path.unresolved_reason,
            source_reference_ids=path.source_reference_ids,
        )
        exposures.append(exposure)
    return tuple(exposures)
