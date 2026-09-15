"""Stream fixed canonical rows into bounded report chunks in the creation transaction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from trading212_application.reports import ReportChunkSink
from trading212_domain import report_v4 as v4
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_manifest import (
    build_report_chunk,
    build_report_manifest,
    encode_report_manifest,
    encode_report_proof,
    encode_report_row,
    encode_report_schema,
    report_document_digest,
)
from trading212_domain.report_profile import renderer_profile
from trading212_domain.report_schema import dataset_tables, table_schema, validate_report_row
from trading212_domain.report_v3 import (
    ReportCaptureContract,
    ReportCaptureSummaryV3,
    ReportDocumentHeaderV3,
    ReportHeaderContract,
    ReportRiskRunBinding,
    ReportScenarioRunBinding,
    ReportSelectionContract,
    ReportSelectionV3,
    selected_report_formats,
)
from trading212_domain.sources import SourceAvailability
from trading212_domain.values import require_utc


class _ProofTable:
    """Bounded incremental state; payload rows are discarded after each sink append."""

    def __init__(self, table: r.ReportTableKey) -> None:
        self.table = table
        self.dataset: r.ExportDataset | None = None
        self.schema = encode_report_schema(table_schema(table))
        self.digest = sha256()
        self.digest.update(len(self.schema).to_bytes(8, "big"))
        self.digest.update(self.schema)
        self.pending: list[r.ReportRow] = []
        self.pending_bytes = 0
        self.ordinal = 0
        self.count = 0
        self.keys: set[str] = set()


class ReportBuilder:
    def __init__(
        self,
        selection: ReportSelectionContract,
        *,
        owner_id: UUID,
        valuation_at: datetime,
        sink: ReportChunkSink,
    ) -> None:
        self.selection, self.owner_id, self.valuation_at, self.sink = (
            selection,
            owner_id,
            valuation_at,
            sink,
        )
        self.descriptors: dict[r.ReportTableKey, r.ReportTableDescriptor] = {}
        self.bindings: list[r.ReportBinding] = []
        self.contexts: dict[str, r.ReportContext | v4.ReportContextV4] = {}
        self.references: dict[str, r.ReportSourceReference] = {}
        self.source_memberships: set[r.ReportSourceMembership] = set()
        self.notes: dict[str, r.ReportNote] = {}
        self.note_memberships: set[r.ReportNoteMembership] = set()
        self.licenses: dict[UUID, r.ReportLicenseReference] = {}
        self.coverage: list[r.ReportCoverageFact] = []
        self.bounds: dict[str, r.ReportBoundFact] = {}
        self.reconciliation: list[r.ReportReconciliationBinding] = []
        self._proof_tables: dict[r.ReportTableKey, _ProofTable] = {}
        self._pending_proof_bytes = 0
        self.byte_length = 0
        self.chunk_count = 0
        self.premium_binding: (
            ReportRiskRunBinding | ReportScenarioRunBinding | v4.ReportProjectionRunBinding | None
        ) = None
        self.copy_expires_at: datetime | None = None
        self._empty_proof_bytes = len(encode_report_proof(r.ReportProof()))
        self._proof_bytes = self._empty_proof_bytes

    def _reserve(self, part: r.ReportProof | v4.ReportProofV4) -> None:
        self._proof_bytes += len(encode_report_proof(part)) - self._empty_proof_bytes + 1
        r.report_limit(self._proof_bytes <= r.MAX_REPORT_MANIFEST_BYTES, "proof_bytes")

    def limit_copy_expiry(self, deadline: datetime) -> None:
        """A new private artifact cannot extend an upstream derived payload's retention."""
        deadline = require_utc(deadline)
        self.copy_expires_at = (
            deadline if self.copy_expires_at is None else min(self.copy_expires_at, deadline)
        )

    @property
    def proof_table_keys(self) -> frozenset[r.ReportTableKey]:
        return frozenset(self._proof_tables)

    def _flush_proof(self, writer: _ProofTable) -> None:
        if not writer.pending:
            return
        chunk = build_report_chunk(writer.table, writer.ordinal, tuple(writer.pending))
        total = self.byte_length + len(chunk.canonical_bytes)
        r.report_limit(total <= r.MAX_REPORT_DOCUMENT_BYTES, "document_bytes")
        self.sink.append(chunk)
        self.byte_length = total
        self.chunk_count += 1
        writer.ordinal += 1
        self._pending_proof_bytes -= writer.pending_bytes
        writer.pending.clear()
        writer.pending_bytes = 0

    def add_proof(self, relation: r.ReportProofRelation) -> None:
        """Stream complete fixed-schema proof rows; the manifest binds their descriptors."""
        table, row = relation.table, relation.row
        self._append_row(table, row)

    def append_dataset_row(self, table: r.ReportTableKey, row: r.ReportRow | None) -> None:
        """Fan one canonical input into bounded selected dataset tables, including empties."""
        selection = self.selection
        if not isinstance(selection, r.ExportSelection) or table not in dataset_tables(
            selection.dataset, selection.field_set
        ):
            fail_validation("Report dataset table is not selected.", field="table")
        if table in self.descriptors:
            fail_validation("Report table was already captured.", field="table")
        writer = self._proof_tables.get(table)
        if writer is None:
            writer = _ProofTable(table)
            writer.dataset = selection.dataset
            self._proof_tables[table] = writer
        elif writer.dataset is not selection.dataset:
            fail_validation("Report table metadata conflicts.", field="table")
        if row is not None:
            self._append_row(table, row, dataset=selection.dataset)

    def _append_row(
        self,
        table: r.ReportTableKey,
        row: r.ReportRow,
        *,
        dataset: r.ExportDataset | None = None,
    ) -> None:
        validate_report_row(table, row)
        if table in self.descriptors:
            fail_validation("Report table was already captured.", field="table")
        writer = self._proof_tables.get(table)
        if writer is None:
            writer = _ProofTable(table)
            self._proof_tables[table] = writer
        if writer.dataset is not dataset:
            fail_validation("Report table metadata conflicts.", field="table")
        if row.key in writer.keys:
            fail_validation("Report proof identity is duplicated.", field="proof")
        payload = encode_report_row(row)
        size = len(payload) + 1
        r.report_limit(size <= r.MAX_REPORT_CHUNK_BYTES - 1024, "row_bytes")
        while self._pending_proof_bytes + size > r.MAX_REPORT_CHUNK_BYTES - 1024:
            self._flush_proof(max(self._proof_tables.values(), key=lambda item: item.pending_bytes))
        writer.count += 1
        r.report_limit(writer.count <= r.MAX_REPORT_DATASET_ROWS, "rows")
        r.report_limit(
            self.byte_length + self._pending_proof_bytes + size <= r.MAX_REPORT_DOCUMENT_BYTES,
            "document_bytes",
        )
        writer.keys.add(row.key)
        writer.digest.update(len(payload).to_bytes(8, "big"))
        writer.digest.update(payload)
        writer.pending.append(row)
        writer.pending_bytes += size
        self._pending_proof_bytes += size

    def complete_proof_tables(self) -> None:
        """Close proof table writers before the facade checks complete table selection."""
        for table in r.ReportTableKey:
            writer = self._proof_tables.get(table)
            if writer is None or table in self.descriptors:
                continue
            self._flush_proof(writer)
            self.descriptors[table] = r.ReportTableDescriptor(
                table=table,
                dataset=writer.dataset,
                schema_digest=sha256(writer.schema).hexdigest(),
                row_count=writer.count,
                content_digest=writer.digest.hexdigest(),
            )

    def add_coverage(self, fact: r.ReportCoverageFact) -> None:
        self._reserve(r.ReportProof(coverage=(fact,)))
        self.coverage.append(fact)

    def add_bound(self, fact: r.ReportBoundFact) -> None:
        previous = self.bounds.get(fact.key)
        if previous is not None:
            if previous != fact:
                fail_validation("Report bound identity conflicts.", field="bound")
            return
        self._reserve(r.ReportProof(bounds=(fact,)))
        self.bounds[fact.key] = fact

    def add_reconciliation(self, fact: r.ReportReconciliationBinding) -> None:
        self._reserve(r.ReportProof(reconciliation=(fact,)))
        self.reconciliation.append(fact)

    def add_context(self, context: r.ReportContext | v4.ReportContextV4) -> None:
        if isinstance(self.selection, v4.ReportSelectionV4):
            if isinstance(context, r.ReportContext):
                context = v4.promote_report_context_v4(context)
            if context.key not in self.contexts:
                self._reserve(v4.ReportProofV4(contexts=(context,)))
        else:
            if not isinstance(context, r.ReportContext):
                fail_validation("Report context profile differs.", field="context")
            context = replace(context, schema_version=r.report_schema_version(self.selection))
            if context.key not in self.contexts:
                self._reserve(r.ReportProof(contexts=(context,)))
        old = self.contexts.setdefault(context.key, context)
        if old != context:
            fail_validation("Report context identity conflicts.", field="context")
        r.report_limit(len(self.contexts) <= 256, "contexts")

    def add_reference(self, reference: r.ReportSourceReference, *, provenance_set_key: str) -> None:
        if reference.key not in self.references:
            self._reserve(r.ReportProof(source_references=(reference,)))
        old = self.references.setdefault(reference.key, reference)
        if old != reference:
            fail_validation("Report source identity conflicts.", field="source")
        membership = r.ReportSourceMembership(
            provenance_set_key=provenance_set_key,
            source_key=reference.key,
        )
        if membership not in self.source_memberships:
            self._reserve(r.ReportProof(source_memberships=(membership,)))
            self.source_memberships.add(membership)
        r.report_limit(len(self.references) <= r.MAX_REPORT_DATASET_ROWS, "sources")
        r.report_limit(
            len(self.source_memberships) <= r.MAX_REPORT_DATASET_ROWS, "source_memberships"
        )

    def add_note(self, note: r.ReportNote, *, note_set_key: str) -> None:
        if note.key not in self.notes:
            self._reserve(r.ReportProof(notes=(note,)))
        old = self.notes.setdefault(note.key, note)
        if old != note:
            fail_validation("Report note identity conflicts.", field="note")
        membership = r.ReportNoteMembership(note_set_key=note_set_key, note_key=note.key)
        if membership not in self.note_memberships:
            self._reserve(r.ReportProof(note_memberships=(membership,)))
            self.note_memberships.add(membership)
        r.report_limit(len(self.notes) <= r.MAX_REPORT_DATASET_ROWS, "notes")

    def add_license(self, license: r.ReportLicenseReference) -> None:
        if license.version_id not in self.licenses:
            self._reserve(r.ReportProof(license_references=(license,)))
        old = self.licenses.setdefault(license.version_id, license)
        if old != license:
            fail_validation("Report license identity conflicts.", field="license")
        r.report_limit(len(self.licenses) <= 256, "licenses")

    def add_binding(self, binding: r.ReportBinding) -> None:
        for old in self.bindings:
            if (old.family, old.role, old.subject_id) == (
                binding.family,
                binding.role,
                binding.subject_id,
            ):
                if old != binding:
                    fail_validation("Report input binding conflicts.", field="binding")
                return
        self.bindings.append(binding)
        r.report_limit(len(self.bindings) <= 256, "bindings")

    def add_table(
        self,
        table: r.ReportTableKey,
        rows: Iterable[r.ReportRow],
        *,
        section: r.ReportSection | None = None,
        dataset: r.ExportDataset | None = None,
        state: SourceAvailability = SourceAvailability.AVAILABLE,
        reason_key: str | None = None,
    ) -> None:
        if table in self.descriptors or table in self._proof_tables:
            fail_validation("Report table was already captured.", field="table")
        schema = encode_report_schema(table_schema(table))
        digest = sha256()
        digest.update(len(schema).to_bytes(8, "big"))
        digest.update(schema)
        pending: list[r.ReportRow] = []
        pending_bytes = 0
        ordinal = 0
        count = 0
        keys: set[str] = set()

        def flush() -> None:
            nonlocal pending_bytes, ordinal
            if not pending:
                return
            chunk = build_report_chunk(table, ordinal, tuple(pending))
            self.byte_length += len(chunk.canonical_bytes)
            r.report_limit(
                self.byte_length + self._pending_proof_bytes <= r.MAX_REPORT_DOCUMENT_BYTES,
                "document_bytes",
            )
            self.sink.append(chunk)
            self.chunk_count += 1
            ordinal += 1
            pending.clear()
            pending_bytes = 0

        for row in rows:
            count += 1
            r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
            validate_report_row(table, row)
            if row.key in keys:
                fail_validation("Report row identity is duplicated.", field="row")
            keys.add(row.key)
            payload = encode_report_row(row)
            if pending_bytes + len(payload) + 1 > r.MAX_REPORT_CHUNK_BYTES - 1024:
                flush()
            r.report_limit(len(payload) <= r.MAX_REPORT_CHUNK_BYTES - 1024, "row_bytes")
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
            pending.append(row)
            pending_bytes += len(payload) + 1
        flush()
        self.descriptors[table] = r.ReportTableDescriptor(
            table=table,
            schema_digest=sha256(schema).hexdigest(),
            row_count=count,
            content_digest=digest.hexdigest(),
            section=section,
            dataset=dataset,
            state=state,
            reason_key=reason_key,
        )

    def finish(self) -> ReportCaptureContract:
        """Return a candidate; only the service may authorize and seal the sink."""
        self.complete_proof_tables()
        proof = r.ReportProof(
            contexts=(),
            source_references=tuple(self.references.values()),
            source_memberships=tuple(self.source_memberships),
            note_memberships=tuple(self.note_memberships),
            license_references=tuple(self.licenses.values()),
            coverage=tuple(self.coverage),
            bounds=tuple(self.bounds.values()),
            notes=tuple(self.notes.values()),
            proof_relations=(),
            reconciliation=tuple(self.reconciliation),
        )
        complete_proof: r.ReportProof | v4.ReportProofV4
        if isinstance(self.selection, v4.ReportSelectionV4):
            from dataclasses import fields

            if any(not isinstance(item, v4.ReportContextV4) for item in self.contexts.values()):
                fail_validation("Report context profile differs.", field="context")
            complete_proof = v4.ReportProofV4(
                contexts=tuple(
                    item for item in self.contexts.values() if isinstance(item, v4.ReportContextV4)
                ),
                **{
                    item.name: getattr(proof, item.name)
                    for item in fields(r.ReportProof)
                    if item.name != "contexts"
                },
            )
        else:
            if any(not isinstance(item, r.ReportContext) for item in self.contexts.values()):
                fail_validation("Report context profile differs.", field="context")
            complete_proof = replace(
                proof,
                contexts=tuple(
                    item for item in self.contexts.values() if isinstance(item, r.ReportContext)
                ),
            )
        proof_bytes = encode_report_proof(complete_proof)
        proof_digest = sha256(proof_bytes).hexdigest()
        tables = tuple(
            self.descriptors[table] for table in r.ReportTableKey if table in self.descriptors
        )
        header: ReportHeaderContract
        if isinstance(self.selection, v4.ReportSelectionV4):
            if not isinstance(self.premium_binding, v4.ReportProjectionRunBinding):
                fail_validation(
                    "The selected projection run binding is missing.", field="premium_binding"
                )
            header = v4.ReportDocumentHeaderV4(
                selection=self.selection,
                owner_id=self.owner_id,
                valuation_at=self.valuation_at,
                context_digest=proof_digest,
                tables=tables,
                document_digest="0" * 64,
                premium_binding=self.premium_binding,
            )
        elif isinstance(self.selection, ReportSelectionV3):
            if not isinstance(
                self.premium_binding, (ReportRiskRunBinding, ReportScenarioRunBinding)
            ):
                fail_validation(
                    "The selected premium run binding is missing.", field="premium_binding"
                )
            header = ReportDocumentHeaderV3(
                selection=self.selection,
                owner_id=self.owner_id,
                valuation_at=self.valuation_at,
                context_digest=proof_digest,
                tables=tables,
                document_digest="0" * 64,
                premium_binding=self.premium_binding,
            )
        else:
            header = r.ReportDocumentHeader(
                document_schema_version=r.report_schema_version(self.selection),
                selection=self.selection,
                owner_id=self.owner_id,
                valuation_at=self.valuation_at,
                context_digest=proof_digest,
                tables=tables,
                document_digest="0" * 64,
            )
        header = replace(header, document_digest=report_document_digest(header))
        bindings = tuple(
            sorted(
                self.bindings,
                key=lambda value: (value.family.value, value.role.value, str(value.subject_id)),
            )
        )
        profile = renderer_profile(selected_report_formats(self.selection))
        capture: ReportCaptureContract
        if isinstance(header, v4.ReportDocumentHeaderV4):
            if not isinstance(complete_proof, v4.ReportProofV4):
                fail_validation("Report proof profile differs.", field="proof")
            capture = v4.ReportCaptureSummaryV4(
                header=header,
                canonical_byte_length=self.byte_length,
                chunk_count=self.chunk_count,
                immutable_bindings=bindings,
                proof=complete_proof,
                proof_digest=proof_digest,
                renderer_profile=profile,
                copy_expires_at=self.copy_expires_at,
            )
        elif isinstance(header, ReportDocumentHeaderV3):
            if not isinstance(complete_proof, r.ReportProof):
                fail_validation("Report proof profile differs.", field="proof")
            capture = ReportCaptureSummaryV3(
                header=header,
                canonical_byte_length=self.byte_length,
                chunk_count=self.chunk_count,
                immutable_bindings=bindings,
                proof=complete_proof,
                proof_digest=proof_digest,
                renderer_profile=profile,
                copy_expires_at=self.copy_expires_at,
            )
        else:
            if not isinstance(complete_proof, r.ReportProof):
                fail_validation("Report proof profile differs.", field="proof")
            capture = r.ReportCaptureSummary(
                header=header,
                canonical_byte_length=self.byte_length,
                chunk_count=self.chunk_count,
                immutable_bindings=bindings,
                proof=complete_proof,
                proof_digest=proof_digest,
                renderer_profile=profile,
                copy_expires_at=self.copy_expires_at,
            )
        total = self.byte_length + len(encode_report_manifest(build_report_manifest(capture)))
        r.report_limit(total <= r.MAX_REPORT_DOCUMENT_BYTES, "document_bytes")
        return replace(capture, canonical_byte_length=total)
