"""Capture licensed entity, fund and classification candidates with explicit cutoffs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Uuid, any_, bindparam, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from trading212_application.xray import XrayServiceErrorCode
from trading212_domain import xray as d
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode

from . import xray_catalog_models as cm
from .models import SnapshotPositionModel
from .xray_base import xray_error
from .xray_capture_base import XrayCaptureState, bounded_rows
from .xray_ingestion import XrayIngestion


@dataclass(frozen=True, slots=True)
class XrayCatalogCapture:
    definitions: tuple[d.XrayFundDefinition, ...]
    mappings: tuple[d.XrayFundMapping, ...]
    constituents: tuple[d.XrayConstituentCandidate, ...]
    identities: tuple[d.XrayEntityEvidence, ...]
    relationships: tuple[d.XrayRelationshipVersion, ...]
    classifications: tuple[d.XrayClassificationBatch, ...]


def _uuid_array(values: set[UUID], name: str) -> Any:
    # One typed array bind also supports catalogs beyond PostgreSQL's bind count.
    return bindparam(name, sorted(values, key=str), type_=ARRAY(Uuid()))


def _valid_at(model: Any, state: XrayCaptureState) -> tuple[Any, ...]:
    return (
        model.owner_id == state.owner,
        model.effective_at <= state.snapshot.valuation_at,
        or_(model.valid_until.is_(None), model.valid_until > state.snapshot.valuation_at),
    )


def _catalog_query(model: Any, state: XrayCaptureState) -> Any:
    return (
        select(model)
        .where(
            *_valid_at(model, state),
            model.provider_id
            == any_(
                _uuid_array(
                    {UUID(item) for item in state.policy.provider_selection_policy.provider_order},
                    "xray_catalog_providers",
                )
            ),
            model.first_observed_at <= state.cutoff,
        )
        .order_by(model.id)
    )


@dataclass(frozen=True, slots=True)
class _CatalogScope:
    instruments: set[UUID]
    entities: set[UUID]
    listings: set[UUID]


def _catalog_scope(
    session: Session, state: XrayCaptureState, instruments: set[UUID], entities: set[UUID]
) -> _CatalogScope:
    """Close only applicable structural IDs; no licensed names, ratios or weights."""
    version = cm.EntityEvidenceVersionModel
    eligible_versions = _catalog_query(version, state).with_only_columns(version.id).order_by(None)
    reference = cm.EntityEvidenceReferenceModel
    relation = cm.InstrumentEntityRelationshipModel

    def edge(model: Any, origin_kind: int, origin: Any, target_kind: int, target: Any) -> Any:
        return select(
            literal(origin_kind).label("origin_kind"),
            origin.label("origin"),
            literal(target_kind).label("target_kind"),
            target.label("target"),
        ).where(
            *_valid_at(model, state),
            model.evidence_version_id.in_(eligible_versions),
            origin.is_not(None),
            target.is_not(None),
        )

    # Kinds are instrument=0, entity=1, listing=2. UNION in the recursive CTE
    # deduplicates subjects, so cycles and diamonds terminate without a query
    # for each ancestor. All competing applicable edges remain eligible.
    edges = union_all(
        edge(reference, 0, reference.instrument_id, 1, reference.entity_id).where(
            reference.kind == "instrument_mapping"
        ),
        edge(reference, 0, reference.instrument_id, 2, reference.listing_id).where(
            reference.kind == "instrument_mapping"
        ),
        edge(relation, 0, relation.instrument_id, 1, relation.entity_id).where(
            relation.kind.in_(("share_class_of", "depositary_receipt_of"))
        ),
        edge(relation, 0, relation.instrument_id, 0, relation.underlying_instrument_id).where(
            relation.kind == "depositary_receipt_of"
        ),
        edge(relation, 1, relation.entity_id, 1, relation.parent_entity_id).where(
            relation.kind == "issuer_parent"
        ),
        edge(relation, 2, relation.listing_id, 0, relation.instrument_id).where(
            relation.kind == "listing_of"
        ),
    ).cte("xray_catalog_edges")
    roots = union_all(
        select(
            literal(0).label("kind"),
            func.unnest(_uuid_array(instruments, "xray_catalog_root_instruments")).label("id"),
        ),
        select(
            literal(1).label("kind"),
            func.unnest(_uuid_array(entities, "xray_catalog_root_entities")).label("id"),
        ),
        select(literal(2).label("kind"), SnapshotPositionModel.listing_id.label("id")).where(
            SnapshotPositionModel.snapshot_id == state.snapshot.id
        ),
    ).cte("xray_catalog_roots")
    reached = select(roots.c.kind, roots.c.id).cte("xray_catalog_reached", recursive=True)
    reached = reached.union(
        select(edges.c.target_kind, edges.c.target).join(
            reached,
            (edges.c.origin_kind == reached.c.kind) & (edges.c.origin == reached.c.id),
        )
    )
    # Each of 100k holdings and 100k identity rows can introduce at most two
    # subjects; 10k original positions can also introduce a listing. The later
    # payload reads independently enforce the actual 100k evidence-row limit.
    limit = 420_000
    rows = list(session.execute(select(reached.c.kind, reached.c.id).limit(limit + 1)))
    if len(rows) > limit:
        raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
    return _CatalogScope(
        {row.id for row in rows if row.kind == 0},
        {row.id for row in rows if row.kind == 1},
        {row.id for row in rows if row.kind == 2},
    )


def capture_catalog(
    service: XrayIngestion, session: Session, state: XrayCaptureState, instruments: set[UUID]
) -> XrayCatalogCapture:
    def query(model: Any) -> Any:
        return _catalog_query(model, state)

    def permit(row: Any) -> None:
        service._evidence_permit(session, row, SourceUse.DISPLAY)
        service._evidence_permit(session, row, SourceUse.STORE)

    definitions: dict[UUID, d.XrayFundDefinition] = {}
    mappings: dict[UUID, d.XrayFundMapping] = {}
    candidates: dict[UUID, d.XrayConstituentCandidate] = {}
    reached = set(instruments)
    frontier = set(instruments)
    explicit_entities: set[UUID] = set()
    total_holdings = 0
    # Four traversable edges; retain the terminal level's fund definition so a
    # still-nested fund is correctly reported as depth-limited by analytics.
    for depth in range(5):
        if not frontier:
            break
        rows = bounded_rows(
            session,
            query(cm.FundDefinitionModel).where(
                cm.FundDefinitionModel.instrument_id
                == any_(_uuid_array(frontier, "xray_fund_frontier"))
            ),
            100_000 - len(definitions),
        )
        for row in rows:
            permit(row)
            reference = state.dependency(
                d.XrayDependencyKind.FUND_DEFINITION,
                d.XraySubjectKind.INSTRUMENT,
                row.instrument_id,
                d.XrayReferenceKind.FUND_DEFINITION,
                row.id,
                None,
                target=("fund_definition_id", row.id),
                source=row,
            )
            definitions[row.id] = d.XrayFundDefinition(
                row.instrument_id,
                state.evidence(
                    row, row.id, reference, valid_until=row.valid_until, confidence=row.confidence
                ),
            )
        if depth == 4 or not rows:
            break
        mapped = bounded_rows(
            session,
            query(cm.FundSourceMappingModel).where(
                cm.FundSourceMappingModel.fund_definition_id
                == any_(_uuid_array({row.id for row in rows}, "xray_fund_definitions"))
            ),
            100_000 - len(mappings),
        )
        definition_instruments = {row.id: row.instrument_id for row in rows}
        for row in mapped:
            permit(row)
            instrument = definition_instruments[row.fund_definition_id]
            reference = state.dependency(
                d.XrayDependencyKind.FUND_MAPPING,
                d.XraySubjectKind.INSTRUMENT,
                instrument,
                d.XrayReferenceKind.FUND_MAPPING,
                row.id,
                row.fund_definition_id,
                target=("fund_mapping_id", row.id),
                source=row,
            )
            mappings[row.id] = d.XrayFundMapping(
                row.id,
                instrument,
                state.evidence(
                    row, row.id, reference, valid_until=row.valid_until, confidence=row.confidence
                ),
            )
        if not mapped:
            break
        snapshots = bounded_rows(
            session,
            query(cm.ConstituentSnapshotModel).where(
                cm.ConstituentSnapshotModel.fund_mapping_id
                == any_(_uuid_array({row.id for row in mapped}, "xray_fund_mappings"))
            ),
            256 - len(candidates),
        )
        following: set[UUID] = set()
        for row in snapshots:
            permit(row)
            holdings = bounded_rows(
                session,
                select(cm.ConstituentHoldingModel)
                .where(
                    cm.ConstituentHoldingModel.owner_id == state.owner,
                    cm.ConstituentHoldingModel.snapshot_id == row.id,
                )
                .order_by(cm.ConstituentHoldingModel.ordinal),
                100_000 - total_holdings,
            )
            if len(holdings) != row.row_count:
                raise xray_error(XrayServiceErrorCode.XRAY_UNAVAILABLE)
            total_holdings += len(holdings)
            reference = state.dependency(
                d.XrayDependencyKind.CONSTITUENTS,
                d.XraySubjectKind.FUND_MAPPING,
                row.fund_mapping_id,
                d.XrayReferenceKind.CONSTITUENT_SNAPSHOT,
                row.id,
                row.fund_mapping_id,
                target=("constituent_snapshot_id", row.id),
                source=row,
            )
            typed = tuple(
                d.XrayConstituentHolding(
                    item.id,
                    d.XrayHoldingKind.CASH
                    if item.state == "cash"
                    else d.XrayHoldingKind.UNRESOLVED
                    if item.state == "unresolved"
                    else d.XrayHoldingKind.INSTRUMENT
                    if item.instrument_id is not None
                    else d.XrayHoldingKind.ENTITY,
                    item.instrument_id,
                    None,
                    item.weight,
                    item.entity_id,
                    item.source_key,
                    CurrencyCode(item.currency),
                    item.evidence_key,
                    item.confidence,
                )
                for item in holdings
            )
            candidates[row.id] = d.XrayConstituentCandidate(
                row.id,
                row.fund_mapping_id,
                state.evidence(
                    row,
                    row.id,
                    reference,
                    confidence=row.confidence,
                    gap=row.known_weight is None,
                ),
                typed,
                row.known_weight,
                row.unresolved_weight,
                row.cash_weight,
            )
            following.update(
                item.instrument_id for item in holdings if item.instrument_id is not None
            )
            explicit_entities.update(
                item.entity_id for item in holdings if item.entity_id is not None
            )
        frontier = following - reached
        reached.update(following)

    scope = _catalog_scope(session, state, reached, explicit_entities)
    scoped_instruments = _uuid_array(scope.instruments, "xray_scoped_instruments")
    scoped_entities = _uuid_array(scope.entities, "xray_scoped_entities")
    scoped_listings = _uuid_array(scope.listings, "xray_scoped_listings")
    identity_model = cm.EntityEvidenceReferenceModel
    relationship_model = cm.InstrumentEntityRelationshipModel
    reference_query = select(identity_model).where(
        *_valid_at(identity_model, state),
        identity_model.kind == "instrument_mapping",
        identity_model.instrument_id == any_(scoped_instruments),
    )
    relationship_query = select(relationship_model).where(
        *_valid_at(relationship_model, state),
        or_(
            relationship_model.instrument_id == any_(scoped_instruments),
            (relationship_model.kind == "issuer_parent")
            & (relationship_model.entity_id == any_(scoped_entities)),
            (relationship_model.kind == "listing_of")
            & (relationship_model.listing_id == any_(scoped_listings)),
        ),
    )
    version_model = cm.EntityEvidenceVersionModel
    versions = bounded_rows(
        session,
        query(version_model).where(
            or_(
                reference_query.where(
                    identity_model.evidence_version_id == version_model.id
                ).exists(),
                relationship_query.where(
                    relationship_model.evidence_version_id == version_model.id
                ).exists(),
            )
        ),
        100_000,
    )
    # Parent authorization precedes materializing child confidence/receipt data.
    for version in versions:
        permit(version)
    parents = {version.id: version for version in versions}
    parent_ids = _uuid_array(set(parents), "xray_identity_versions")
    references = bounded_rows(
        session,
        reference_query.where(identity_model.evidence_version_id == any_(parent_ids)).order_by(
            identity_model.evidence_version_id, identity_model.ordinal
        ),
        100_000,
    )
    relation_rows = bounded_rows(
        session,
        relationship_query.where(
            relationship_model.evidence_version_id == any_(parent_ids)
        ).order_by(relationship_model.evidence_version_id, relationship_model.id),
        100_000 - len(references),
    )
    identities: list[d.XrayEntityEvidence] = []
    for row in references:
        version = parents[row.evidence_version_id]
        reference = state.dependency(
            d.XrayDependencyKind.IDENTITY,
            d.XraySubjectKind.INSTRUMENT,
            row.instrument_id,
            d.XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE,
            row.id,
            version.id,
            target=("entity_evidence_version_id", version.id),
            source=version,
        )
        identities.append(
            d.XrayEntityEvidence(
                row.instrument_id,
                row.listing_id,
                row.entity_id,
                state.evidence(
                    version,
                    row.id,
                    reference,
                    effective_at=row.effective_at,
                    valid_until=row.valid_until,
                    confidence=row.confidence,
                ),
            )
        )
    relationships: list[d.XrayRelationshipVersion] = []
    for row in relation_rows:
        version = parents[row.evidence_version_id]
        kind = d.XrayRelationshipKind(row.kind)
        subject_kind, subject = (
            (d.XraySubjectKind.LISTING, row.listing_id)
            if kind is d.XrayRelationshipKind.LISTING_OF
            else (d.XraySubjectKind.ENTITY, row.entity_id)
            if kind is d.XrayRelationshipKind.ISSUER_PARENT
            else (d.XraySubjectKind.INSTRUMENT, row.instrument_id)
        )
        reference = state.dependency(
            d.XrayDependencyKind.RELATIONSHIP,
            subject_kind,
            subject,
            d.XrayReferenceKind.RELATIONSHIP,
            row.id,
            version.id,
            target=("entity_evidence_version_id", version.id),
            source=version,
        )
        relationships.append(
            d.XrayRelationshipVersion(
                row.instrument_id,
                row.underlying_instrument_id,
                row.entity_id,
                kind,
                row.units_per_receipt,
                state.evidence(
                    version,
                    row.id,
                    reference,
                    effective_at=row.effective_at,
                    valid_until=row.valid_until,
                    confidence=row.confidence,
                ),
                row.listing_id,
                row.share_class_id,
                row.parent_entity_id,
            )
        )

    assignment_count = len(identities) + len(relationships)
    taxonomies = {item.taxonomy_id: item for item in state.policy.taxonomy_versions}
    batch_model = cm.ClassificationSnapshotModel
    assignment_model = cm.ClassificationAssignmentModel
    requested_model = cm.ClassificationSnapshotInstrumentModel
    assignment_query = select(assignment_model).where(
        *_valid_at(assignment_model, state),
        or_(
            assignment_model.entity_id == any_(scoped_entities),
            assignment_model.instrument_id == any_(scoped_instruments),
        ),
    )
    batches = bounded_rows(
        session,
        query(batch_model).where(
            batch_model.taxonomy_id.in_(tuple(taxonomies)),
            or_(
                assignment_query.where(assignment_model.snapshot_id == batch_model.id).exists(),
                select(requested_model.id)
                .where(
                    requested_model.owner_id == state.owner,
                    requested_model.snapshot_id == batch_model.id,
                    requested_model.instrument_id == any_(scoped_instruments),
                )
                .exists(),
            ),
        ),
        100_000 - assignment_count,
    )
    for batch in batches:
        permit(batch)
    # Requested membership retains relevant empty/GAP batches, while an unrelated
    # expired batch is never admitted merely because it uses the same taxonomy.
    assignment_rows = bounded_rows(
        session,
        assignment_query.where(
            assignment_model.snapshot_id
            == any_(_uuid_array({batch.id for batch in batches}, "xray_classification_batches"))
        ).order_by(assignment_model.snapshot_id, assignment_model.id),
        100_000 - assignment_count,
    )
    requested_rows = bounded_rows(
        session,
        select(requested_model)
        .where(
            requested_model.owner_id == state.owner,
            requested_model.snapshot_id
            == any_(_uuid_array({batch.id for batch in batches}, "xray_requested_batches")),
            requested_model.instrument_id == any_(scoped_instruments),
        )
        .order_by(requested_model.snapshot_id, requested_model.ordinal),
        100_000,
    )
    requested_by_batch: dict[UUID, set[UUID]] = {}
    for requested_row in requested_rows:
        requested_by_batch.setdefault(requested_row.snapshot_id, set()).add(
            requested_row.instrument_id
        )
    by_batch: dict[UUID, list[cm.ClassificationAssignmentModel]] = {}
    for assignment_row in assignment_rows:
        by_batch.setdefault(assignment_row.snapshot_id, []).append(assignment_row)
    classifications: list[d.XrayClassificationBatch] = []
    target_count = 0
    candidate_count = assignment_count
    for batch in batches:
        reference = state.dependency(
            d.XrayDependencyKind.CLASSIFICATION,
            d.XraySubjectKind.SOURCE_RECORD,
            batch.id,
            d.XrayReferenceKind.CLASSIFICATION_SNAPSHOT,
            batch.id,
            None,
            target=("classification_snapshot_id", batch.id),
            source=batch,
        )
        taxonomy = taxonomies[batch.taxonomy_id]
        assignments = tuple(
            d.XrayClassificationAssignment(
                row.id,
                d.XraySubjectKind.ENTITY
                if row.entity_id is not None
                else d.XraySubjectKind.INSTRUMENT,
                row.entity_id if row.entity_id is not None else row.instrument_id,
                d.XrayDimension(row.dimension),
                taxonomy.taxonomy_id,
                taxonomy.version,
                row.bucket_key,
                row.confidence,
            )
            for row in by_batch.get(batch.id, ())
            if row.state == "available" and row.bucket_key is not None
        )
        returned_rows = by_batch.get(batch.id, [])
        returned_instruments = {row.instrument_id for row in returned_rows}
        targets = {
            (d.XraySubjectKind.ENTITY, row.entity_id)
            if row.entity_id is not None
            else (d.XraySubjectKind.INSTRUMENT, row.instrument_id)
            for row in returned_rows
        }
        targets.update(
            (d.XraySubjectKind.INSTRUMENT, instrument)
            for instrument in requested_by_batch.get(batch.id, set()) - returned_instruments
        )
        target_count += len(targets)
        assigned_subjects = {(row.subject_kind, row.subject_id) for row in assignments}
        candidate_count += len(assignments) + len(targets - assigned_subjects)
        if target_count > 100_000 or candidate_count > 100_000:
            raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
        requested_subjects = tuple(
            d.XrayClassificationSubject(
                subject_kind,
                subject_id,
                taxonomy.dimension,
                taxonomy.taxonomy_id,
                taxonomy.version,
            )
            for subject_kind, subject_id in sorted(
                targets, key=lambda target: (target[0].value, str(target[1]))
            )
        )
        classifications.append(
            d.XrayClassificationBatch(
                state.evidence(
                    batch, batch.id, reference, confidence=batch.confidence, gap=not assignments
                ),
                assignments,
                requested_subjects,
            )
        )
    return XrayCatalogCapture(
        tuple(definitions.values()),
        tuple(mappings.values()),
        tuple(candidates.values()),
        tuple(identities),
        tuple(relationships),
        tuple(classifications),
    )
