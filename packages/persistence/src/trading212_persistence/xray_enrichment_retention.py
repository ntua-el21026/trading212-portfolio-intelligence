"""Resume licensed enrichment expiry within the existing source invocation budget."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, select, text
from sqlalchemy.orm import Session

from . import xray_catalog_models as cm
from .premium_retention_costs import ENRICHMENT_MARKER_EPOCH_ROWS
from .premium_retention_runtime import charge, finish_sweep, open_sweep
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


def expire_enrichment_payloads(
    session: Session, *, at: datetime, limit: int, budget: SourcePurgeBudget
) -> int:
    completed = 0
    busy_owners: set[UUID] = set()
    for model, reference in _FAMILIES:
        kind = {
            "entity_evidence_version_id": "entity_evidence",
            "classification_snapshot_id": "classification",
            "fund_definition_id": "fund_definition",
            "fund_mapping_id": "fund_mapping",
        }[reference]
        sweep = open_sweep(session, kind, None, at, budget)
        if sweep is None:
            return completed
        while completed < limit and budget.metadata_limit >= 12:
            # Keyset actual source rows before expiry/completion predicates. Every
            # healthy or completed candidate consumes one physical inspection.
            query = select(model.id, model.owner_id, model.expires_at)
            if sweep.after_id is not None:
                query = query.where(model.id > sweep.after_id)
            charge(budget, 1)
            candidate = session.execute(query.order_by(model.id).limit(1)).first()
            if candidate is None:
                finish_sweep(session, sweep, budget)
                break
            charge(budget, 1)
            sweep.after_id = candidate.id
            session.flush()
            if candidate.expires_at > at or candidate.owner_id in busy_owners:
                continue
            charge(budget, 1)
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
            # Share the maintenance lock order without stalling other families.
            if not all(
                session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"{lock}:{candidate.owner_id}"},
                )
                is True
                for lock in ("sources", "xray")
            ):
                # Defer this owner across families without spending the pass on its backlog.
                busy_owners.add(candidate.owner_id)
                continue
            charge(budget, 1)
            source = session.scalar(
                select(model)
                .where(model.id == candidate.id, model.owner_id == candidate.owner_id)
                .with_for_update(skip_locked=True)
            )
            if source is None:
                continue
            if not budget.inspect(rows=1):
                return completed
            work = session.scalar(
                select(EnrichmentRetentionWorkModel)
                .where(
                    EnrichmentRetentionWorkModel.owner_id == source.owner_id,
                    getattr(EnrichmentRetentionWorkModel, reference) == source.id,
                )
                .limit(1)
            )
            if work is None:
                if not budget.inspect(rows=8 + ENRICHMENT_MARKER_EPOCH_ROWS):
                    return completed
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
            if work.phase == "copies":
                from .risk_retention import expire_risk_payloads
                from .scenario_retention import expire_scenario_payloads

                if not expire_risk_payloads(session, at=at, owner=source.owner_id, budget=budget):
                    continue
                if not expire_scenario_payloads(
                    session, at=at, owner=source.owner_id, budget=budget
                ):
                    continue
                from .alert_retention import purge_alert_source_copies
                from .report_retention import purge_report_source_copies

                kind = {
                    "entity_evidence_version_id": "entity_evidence",
                    "classification_snapshot_id": "classification",
                    "fund_definition_id": "fund_definition",
                    "fund_mapping_id": "fund_mapping",
                }[reference]
                if not purge_alert_source_copies(
                    session,
                    owner=source.owner_id,
                    kind=kind,
                    source_id=source.id,
                    at=at,
                    budget=budget,
                ):
                    continue
                if not purge_report_source_copies(
                    session,
                    owner=source.owner_id,
                    kind=kind,
                    source_id=source.id,
                    at=at,
                    budget=budget,
                ):
                    continue
                if not purge_xray_source_copies(session, source, at=at, budget=budget):
                    continue
                # The old SQL transition additionally traverses X-ray copies;
                # its transitive physical closure is tracked separately in ADR0032.
                if not budget.inspect(rows=3):
                    return completed
                work.phase = "payloads"
                session.flush()
            if work.phase == "payloads":
                if not budget.inspect(rows=3):
                    return completed
                complete, removed = _payloads(session, source, budget)
                work.removed_row_count += removed
                session.flush()
                if not complete:
                    continue
                if not budget.inspect(rows=12 + ENRICHMENT_MARKER_EPOCH_ROWS):
                    return completed
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
                completed += 1
    return completed
