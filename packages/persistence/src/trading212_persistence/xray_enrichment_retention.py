"""Resume licensed enrichment expiry within the existing source invocation budget."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, select, text
from sqlalchemy.orm import Session, load_only

from . import xray_catalog_models as cm
from .phase2_retention_costs import (
    ENRICHMENT_COMPLETION_ROWS,
    ENRICHMENT_MARKER_ROWS,
    ENRICHMENT_PROGRESS_ROWS,
)
from .phase2_retention_runtime import charge, physical_source_candidates, rotation
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows
from .xray_lifecycle_models import EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel
from .xray_retention import purge_xray_source_copies

_FAMILIES = (
    (cm.EntityEvidenceVersionModel, "entity_evidence_version_id"),
    (cm.ClassificationSnapshotModel, "classification_snapshot_id"),
    (cm.FundSourceMappingModel, "fund_mapping_id"),
    (cm.FundDefinitionModel, "fund_definition_id"),
)


def _payloads(
    session: Session, source: cm.XrayEvidenceFields, budget: SourcePurgeBudget
) -> tuple[bool, int]:
    specifications: tuple[tuple[type, str, tuple[str, ...], bool], ...]
    if isinstance(source, cm.EntityEvidenceVersionModel):
        specifications = (
            (
                cm.InstrumentEntityRelationshipModel,
                "evidence_version_id",
                ("units_per_receipt", "confidence"),
                False,
            ),
            (cm.ShareClassModel, "evidence_version_id", ("class_key", "confidence"), False),
            (
                cm.EntityEvidenceReferenceModel,
                "evidence_version_id",
                ("display_name", "lei", "confidence"),
                False,
            ),
            (cm.EntityEvidenceVersionModel, "id", ("confidence",), False),
        )
    elif isinstance(source, cm.ClassificationSnapshotModel):
        specifications = (
            (
                cm.ClassificationSnapshotAssignmentModel,
                "snapshot_id",
                ("assignment_id", "ordinal"),
                True,
            ),
            (
                cm.ClassificationAssignmentModel,
                "snapshot_id",
                (
                    "instrument_id",
                    "entity_id",
                    "source_key",
                    "dimension",
                    "bucket_key",
                    "effective_at",
                    "valid_until",
                    "confidence",
                    "evidence_key",
                    "state",
                ),
                True,
            ),
            (
                cm.ClassificationSnapshotInstrumentModel,
                "snapshot_id",
                ("instrument_id", "ordinal"),
                True,
            ),
            (cm.ClassificationSnapshotModel, "id", ("confidence",), False),
        )
    elif isinstance(source, cm.FundSourceMappingModel):
        specifications = (
            (
                cm.FundSourceMappingModel,
                "id",
                ("provider_fund_key", "evidence_key", "confidence"),
                False,
            ),
        )
    else:
        specifications = (
            (cm.FundDefinitionModel, "id", ("fund_type", "evidence_key", "confidence"), False),
        )
    removed = 0
    for model, parent, columns, delete_rows in specifications:
        table = cast(Table, model.__table__)
        result = purge_payload_rows(
            session,
            table,
            (table.c.owner_id == source.owner_id) & (table.c[parent] == source.id),
            payload_columns=columns,
            delete_rows=delete_rows,
            budget=budget,
        )
        removed += result.removed_rows
        if not result.complete:
            return False, removed
    return True, removed


def _expire_enrichment_source(
    session: Session,
    source: cm.XrayEvidenceFields,
    reference: str,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    if not charge(budget):
        return False
    work = session.scalar(
        select(EnrichmentRetentionWorkModel)
        .where(
            EnrichmentRetentionWorkModel.owner_id == source.owner_id,
            getattr(EnrichmentRetentionWorkModel, reference) == source.id,
        )
        .limit(1)
    )
    if work is None:
        if not charge(budget, ENRICHMENT_MARKER_ROWS):
            return False
        work = EnrichmentRetentionWorkModel(
            owner_id=source.owner_id,
            **{reference: source.id},
            started_at=at,
            content_digest=source.content_digest,
            phase="copies",
            removed_row_count=0,
            completed_at=None,
            created_at=at,
        )
        session.add(work)
        session.flush()
    elif work.phase == "complete":
        return False
    if work.started_at > at:
        return False
    if work.phase == "copies":
        from .alert_retention import purge_alert_source_copies
        from .report_retention import purge_report_source_copies

        kind = {
            "entity_evidence_version_id": "entity_evidence",
            "classification_snapshot_id": "classification",
            "fund_definition_id": "fund_definition",
            "fund_mapping_id": "fund_mapping",
        }[reference]
        if not purge_alert_source_copies(
            session, owner=source.owner_id, kind=kind, source_id=source.id, at=at, budget=budget
        ):
            return False
        if not purge_report_source_copies(
            session, owner=source.owner_id, kind=kind, source_id=source.id, at=at, budget=budget
        ):
            return False
        # Exact X-ray inputs drain their own risk/scenario dependants. An all-owner
        # premium sweep here could repeatedly consume this source's work budget.
        if not purge_xray_source_copies(session, source, at=at, budget=budget):
            return False
        if not charge(budget, ENRICHMENT_PROGRESS_ROWS):
            return False
        work.phase = "payloads"
        session.flush()
    if not charge(budget, ENRICHMENT_PROGRESS_ROWS):
        return False
    complete, removed = _payloads(session, source, budget)
    work.removed_row_count += removed
    session.flush()
    if not complete or not charge(budget, ENRICHMENT_COMPLETION_ROWS):
        return False
    session.add(
        EnrichmentExpiryEventModel(
            owner_id=source.owner_id,
            **{reference: source.id},
            expired_at=at,
            content_digest=source.content_digest,
            removed_row_count=work.removed_row_count,
            created_at=at,
        )
    )
    session.flush()
    work.phase = "complete"
    work.completed_at = at
    session.flush()
    return True


def expire_enrichment_payloads(
    session: Session, *, at: datetime, limit: int, budget: SourcePurgeBudget
) -> int:
    completed = 0
    busy_owners: set[UUID] = set()
    kinds = {
        "entity_evidence_version_id": "entity_evidence",
        "classification_snapshot_id": "classification",
        "fund_definition_id": "fund_definition",
        "fund_mapping_id": "fund_mapping",
    }
    for index in rotation(session, "enrichment", len(_FAMILIES), budget):
        model, reference = _FAMILIES[index]
        for candidate in physical_source_candidates(
            session,
            cast(Table, model.__table__),
            cast(Table, EnrichmentRetentionWorkModel.__table__),
            reference,
            kinds[reference],
            at,
            budget,
        ):
            if completed >= limit or budget.rows_removed == 0:
                return completed
            if candidate.owner_id in busy_owners or (
                not candidate.pending
                and (candidate.expires_at is None or candidate.expires_at > at)
            ):
                continue
            if not all(
                session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"{lock}:{candidate.owner_id}"},
                )
                is True
                for lock in ("sources", "xray", "historical")
            ):
                busy_owners.add(candidate.owner_id)
                continue
            if not candidate.pending:
                if not charge(budget):
                    return completed
                if (
                    session.scalar(
                        select(EnrichmentExpiryEventModel.id)
                        .where(
                            EnrichmentExpiryEventModel.owner_id == candidate.owner_id,
                            getattr(EnrichmentExpiryEventModel, reference) == candidate.id,
                        )
                        .limit(1)
                    )
                    is not None
                ):
                    continue
            if not charge(budget):
                return completed
            source = session.scalar(
                select(model)
                .options(
                    load_only(
                        model.id,
                        model.owner_id,
                        model.expires_at,
                        model.content_digest,
                        raiseload=True,
                    )
                )
                .where(model.id == candidate.id, model.owner_id == candidate.owner_id)
                .with_for_update(skip_locked=True)
            )
            if source is not None and _expire_enrichment_source(
                session, source, reference, at, budget
            ):
                completed += 1
    return completed
