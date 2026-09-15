"""Readable provenance and one inert attachment containing the canonical manifest."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from typing import Any, Protocol

from reportlab.pdfbase.pdfdoc import (  # type: ignore[import-untyped]
    PDFArray,
    PDFDictionary,
    PDFName,
    PDFStream,
    PDFString,
    PDFZCompress,
)
from trading212_application.reports import ReportRenderError, ReportRenderGuard
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v3 import ReportManifestContract
from trading212_domain.reports import ReportCell, ReportFailureCode
from trading212_domain.values import decimal_string

from .common import METRIC_COLUMNS, display_cell, metric_metadata
from .text import label

MANIFEST_FILENAME = "report-manifest.json"


def display_contextual_cell(cell: ReportCell, row_context: str | None = None) -> str:
    """Keep an explicit context beside its value, including nondecimal scalars."""
    value = display_cell(cell)
    if cell.context_key is not None and cell.context_key != row_context:
        return f"{value} [context: {cell.context_key}]"
    return value


class ManifestLayout(Protocol):
    def text(
        self, value: str, *, bold: bool = False, size: float = 9.5, indent: float = 0
    ) -> None: ...

    def heading(self, title: str, *, key: str, major: bool = False) -> None: ...


def attach_manifest(canvas: Any, manifest: ReportManifestContract, guard: ReportRenderGuard) -> str:
    """Use only fixed PDF objects; no file reads, annotations, URLs or actions.

    ReportLab 5.0.1 exposes these PDFDictionary/PDFStream/Reference primitives but
    no Canvas attachment API. The filename names an embedded stream only. Its
    fixed MIME name escapes the slash that ReportLab's PDFName leaves unchanged.
    """
    guard.check()
    payload = encode_report_manifest(manifest)
    document = canvas._doc
    if getattr(document.Catalog, "Names", None) is not None:
        raise ReportRenderError(ReportFailureCode.INPUT_CHANGED)
    stream = PDFStream(
        PDFDictionary(
            {
                "Type": PDFName("EmbeddedFile"),
                "Subtype": "/application#2Fjson",
                "Params": PDFDictionary({"Size": len(payload)}),
            }
        ),
        content=payload,
        filters=[PDFZCompress],
    )
    file_specification = PDFDictionary(
        {
            "Type": PDFName("Filespec"),
            "F": PDFString(MANIFEST_FILENAME),
            "Desc": PDFString("Complete canonical report manifest (UTF-8 JSON)"),
            "EF": PDFDictionary({"F": document.Reference(stream)}),
        }
    )
    document.Catalog.Names = PDFDictionary(
        {
            "EmbeddedFiles": PDFDictionary(
                {
                    "Names": PDFArray(
                        [PDFString(MANIFEST_FILENAME), document.Reference(file_specification)]
                    )
                }
            )
        }
    )
    guard.check()
    return sha256(payload).hexdigest()


def _identity(layout: ManifestLayout, manifest: ReportManifestContract, digest: str) -> None:
    layout.heading("Sources, methods and quality", key="provenance", major=True)
    layout.text(
        "This appendix identifies the exact inputs, methods, source rights and quality behind "
        "the report. Context and set identifiers connect each record to the entries below. "
        "The complete canonical manifest is also embedded as an inert JSON attachment."
    )
    layout.text(f"Attachment: {MANIFEST_FILENAME} (application/json)", bold=True)
    layout.text(f"Attachment SHA-256: {digest}", size=8)
    layout.text(f"Document SHA-256: {manifest.document.document_digest}", size=8)
    layout.text(f"Context SHA-256: {manifest.document.context_digest}", size=8)
    layout.text(
        f"Method: {manifest.method} / {manifest.method_version}; "
        f"document schema: {manifest.document.document_schema_version}; "
        f"text escaping: {manifest.escaping_version}"
    )
    layout.heading("Immutable input identities", key="manifest-inputs")
    if not manifest.bindings:
        layout.text("No immutable input bindings are recorded.")
    for binding in manifest.bindings:
        layout.text(f"{label(binding.family.value)} / {label(binding.role.value)}", bold=True)
        layout.text(f"ID: {binding.subject_id}; SHA-256: {binding.content_digest}", size=8)
        if binding.parent_id is not None:
            layout.text(f"Parent ID: {binding.parent_id}", size=8)
        if binding.method_key is not None or binding.method_version is not None:
            layout.text(f"Method: {binding.method_key}; version: {binding.method_version}")
    layout.heading("Canonical table inventory", key="manifest-tables")
    for table in manifest.document.tables:
        scope = table.section or table.dataset
        layout.text(
            f"{table.table.value} | scope: {scope.value if scope else 'proof'} | "
            f"state: {table.state.value} | rows: {table.row_count}",
            bold=True,
            size=8,
        )
        if table.reason_key is not None:
            layout.text(f"Reason: {table.reason_key}", size=8)
        layout.text(f"Content SHA-256: {table.content_digest}", size=8)
        layout.text(f"Schema SHA-256: {table.schema_digest}", size=8)


def _contexts(layout: ManifestLayout, manifest: ReportManifestContract) -> None:
    layout.heading("Methods and quality by context", key="manifest-contexts")
    if not manifest.contexts:
        layout.text("No result contexts are recorded.")
    for context in manifest.contexts:
        layout.text(f"{context.key} | {label(context.family.value)}", bold=True)
        layout.text(
            f"Method: {context.method_key} / {context.method_version}; "
            f"quality: {context.quality.value}; schema: {context.schema_version}"
        )
        layout.text(
            f"Valuation: {context.valuation_at.isoformat()}; "
            f"source cutoff: {context.source_cutoff_at.isoformat()}",
            size=8,
        )
        layout.text(
            "Source time: "
            + (context.source_at.isoformat() if context.source_at else "not recorded"),
            size=8,
        )
        layout.text(
            f"Sources: {context.provenance_set_key}; coverage: {context.coverage_set_key}; "
            f"notes: {context.note_set_key}",
            size=8,
        )
        layout.text(f"Reconciliation: {context.reconciliation_key or 'not recorded'}", size=8)
    layout.heading("Coverage and numerical bounds", key="manifest-coverage")
    if not manifest.coverage:
        layout.text("No coverage facts are recorded.")
    contexts = {context.key: context for context in manifest.contexts}
    for fact in manifest.coverage:
        layout.text(
            f"{fact.set_key} | {fact.family.value} | {fact.metric_key}: "
            f"{display_contextual_cell(fact.value)}"
        )
        metadata = metric_metadata(fact.value, contexts.get(fact.value.context_key or ""))
        details = "; ".join(
            f"{label(key)}: {value}"
            for key, value in zip(METRIC_COLUMNS, metadata, strict=True)
            if value
        )
        if details:
            layout.text(details, size=8)
    if not manifest.bounds:
        layout.text("No additional numerical bounds are recorded.")
    for bound in manifest.bounds:
        layout.text(f"{bound.key} | {bound.family.value} | {bound.kind.value}", bold=True)
        quantum = decimal_string(bound.quantum) if bound.quantum is not None else "not recorded"
        layout.text(
            f"Quantum: {quantum}; "
            f"rounding: {bound.rounding or 'not recorded'}; "
            f"positive below quantum: {str(bound.positive_below_quantum).lower()}"
        )


def _notes(layout: ManifestLayout, manifest: ReportManifestContract) -> None:
    memberships: dict[str, list[str]] = defaultdict(list)
    for member in manifest.note_memberships:
        memberships[member.note_key].append(member.note_set_key)
    layout.heading("Warnings, assumptions and missing values", key="manifest-notes")
    if not manifest.notes:
        layout.text("No notes are recorded.")
    for note in manifest.notes:
        layout.text(f"{note.key} | {label(note.kind.value)} | {note.family.value}", bold=True)
        layout.text(
            f"Code: {note.code}; kind: {note.kind.value}; "
            f"sets: {', '.join(memberships[note.key]) or 'none'}",
            size=8,
        )
        layout.text(note.text)
        if note.related_provenance_set_key is not None:
            layout.text(f"Related sources: {note.related_provenance_set_key}", size=8)
    layout.heading("Reconciliation", key="manifest-reconciliation")
    if not manifest.reconciliation:
        layout.text("No reconciliation bindings are recorded; no reconciled state is inferred.")
    for binding in manifest.reconciliation:
        layout.text(f"{binding.key} | {'absent' if binding.absent else 'recorded'}", bold=True)
        if not binding.absent:
            layout.text(f"Run ID: {binding.run_id}; SHA-256: {binding.content_digest}", size=8)


def _sources(layout: ManifestLayout, manifest: ReportManifestContract) -> None:
    memberships: dict[str, list[str]] = defaultdict(list)
    for member in manifest.source_memberships:
        memberships[member.source_key].append(member.provenance_set_key)
    layout.heading("Source register", key="manifest-sources")
    if not manifest.source_references:
        layout.text("No source references are recorded.")
    for source in manifest.source_references:
        layout.text(f"{source.key} | {label(source.kind.value)}", bold=True)
        layout.text(f"ID: {source.subject_id}; SHA-256: {source.content_digest}", size=8)
        layout.text(f"Source sets: {', '.join(memberships[source.key]) or 'none'}", size=8)
        for name, value in (
            ("Parent ID", source.parent_id),
            ("Provider ID", source.provider_id),
            ("License version ID", source.license_version_id),
            ("Mapping version ID", source.mapping_version_id),
        ):
            if value is not None:
                layout.text(f"{name}: {value}", size=8)
        layout.text(
            "Source time: "
            + (source.source_at.isoformat() if source.source_at else "not recorded")
            + "; first observed: "
            + (
                source.first_observed_at.isoformat() if source.first_observed_at else "not recorded"
            ),
            size=8,
        )
    layout.heading("Source licenses and attribution", key="manifest-licenses")
    layout.text(
        "Permissions below are pinned capture facts. They do not grant redistribution rights; "
        "the service rechecks current authorization and expiry before private downloads."
    )
    if not manifest.license_references:
        layout.text("No external source licenses are recorded.")
    for license in manifest.license_references:
        layout.text(f"License version: {license.version_id}", bold=True)
        layout.text(
            f"Provider ID: {license.provider_id}; SHA-256: {license.license_digest}", size=8
        )
        layout.text(license.attribution)
        layout.text(
            f"Store: {license.pinned_store.value}; display: {license.pinned_display.value}; "
            f"report: {license.pinned_report.value}; export: {license.pinned_export.value}"
        )
        layout.text(
            f"Valid from: {license.valid_from.isoformat()}; expires: "
            + (license.expires_at.isoformat() if license.expires_at else "not recorded"),
            size=8,
        )


def render_manifest_appendix(
    layout: ManifestLayout, manifest: ReportManifestContract, digest: str
) -> None:
    _identity(layout, manifest, digest)
    _contexts(layout, manifest)
    _notes(layout, manifest)
    _sources(layout, manifest)
    if manifest.proof_relations:
        layout.heading("Additional canonical evidence", key="manifest-proof")
        contexts = {context.key: context for context in manifest.contexts}
        for relation in manifest.proof_relations:
            row = relation.row
            layout.text(f"{relation.table.value} | {row.key}", bold=True)
            layout.text(f"Default row context: {row.context_key}", size=8)
            for column, cell in zip(table_schema(relation.table).columns, row.cells, strict=True):
                layout.text(
                    f"{label(column.key)}: {display_contextual_cell(cell, row.context_key)}",
                    size=8,
                )
                metadata = metric_metadata(cell, contexts[cell.context_key or row.context_key])
                for key, value in zip(METRIC_COLUMNS, metadata, strict=True):
                    if value:
                        layout.text(f"{label(key)}: {value}", size=8, indent=10)
    layout.heading("Rendering and reproducibility", key="manifest-rendering")
    profile = manifest.renderer_profile
    layout.text(
        f"Profile: {profile.profile_version}; template: {profile.template_version}; "
        f"locale: {profile.locale}; timezone: {profile.timezone}"
    )
    layout.text(
        f"Chart order: {profile.chart_order_version}; accessibility: "
        f"{profile.accessibility_profile_version}"
    )
    for renderer in profile.renderer_versions:
        layout.text(f"{renderer.format.value}: {renderer.name} {renderer.version}")
    for font in profile.fonts:
        layout.text(f"Font: {font.name} {font.version}", bold=True)
        layout.text(f"Content SHA-256: {font.content_digest}", size=8)
        layout.text(f"License SHA-256: {font.license_digest}", size=8)
