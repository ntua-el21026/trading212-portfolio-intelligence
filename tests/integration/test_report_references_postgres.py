"""Streamed report metadata must resolve before a durable job can dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from dataclasses import replace

import pytest
from sqlalchemy import func, select
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.report_manifest import decode_report_chunk
from trading212_domain.sources import SourceAvailability
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)

from tests.integration.test_report_postgres import ReportCase, generate
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def test_unresolved_streamed_cell_proof_rolls_back_before_dispatch(
    report_case: ReportCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        original = ReportBuilder.add_table
        mutation = ""
        intercepted = 0

        def changed(row: r.ReportRow) -> r.ReportRow:
            nonlocal intercepted
            intercepted += 1
            if mutation == "row_context":
                return replace(row, context_key="foreign.context")
            cells = list(row.cells)
            metric = cells[3]
            assert metric.kind is r.CellKind.DECIMAL and metric.value is not None
            if mutation == "reason":
                cells[3] = replace(
                    metric,
                    value=None,
                    state=r.CellState.UNAVAILABLE,
                    reason_key="absent.unavailable.reason",
                )
            elif mutation == "bound":
                cells[3] = replace(metric, bound_key="absent.bound")
            elif mutation == "coverage":
                cells[3] = replace(metric, coverage_key="absent.coverage")
            elif mutation == "provenance_set":
                cells[3] = replace(metric, provenance_set_key="absent.sources")
            elif mutation == "note_set":
                cells[3] = replace(metric, note_set_key="absent.notes")
            elif mutation == "cell_context":
                cells[3] = replace(metric, context_key="foreign.context")
            else:
                raise AssertionError("Unknown test mutation")
            return replace(row, cells=tuple(cells))

        def add_table(
            builder: ReportBuilder,
            table: r.ReportTableKey,
            rows: Iterable[r.ReportRow],
            *,
            section: r.ReportSection | None = None,
            dataset: r.ExportDataset | None = None,
            state: SourceAvailability = SourceAvailability.AVAILABLE,
            reason_key: str | None = None,
        ) -> None:
            def projected() -> Iterator[r.ReportRow]:
                for row in rows:
                    if table is not r.ReportTableKey.SNAPSHOT_TOTALS:
                        yield row
                    elif mutation == "context_limit":
                        for ordinal in range(257):
                            yield replace(
                                row,
                                key=f"snapshot.totals.{ordinal}",
                                context_key=f"context.{ordinal}",
                                cells=tuple(replace(cell, context_key=None) for cell in row.cells),
                            )
                    else:
                        yield changed(row)

            original(
                builder,
                table,
                projected(),
                section=section,
                dataset=dataset,
                state=state,
                reason_key=reason_key,
            )

        def durable_counts() -> tuple[int | None, ...]:
            with report_case.base.sessions() as session:
                return tuple(
                    session.scalar(select(func.count()).select_from(model))
                    for model in (
                        ReportInputSnapshotModel,
                        ReportInputChunkModel,
                        ReportJobModel,
                        ReportDispatchOutboxModel,
                        ApplicationCommandIdentityModel,
                    )
                )

        before = durable_counts()
        with monkeypatch.context() as patch:
            patch.setattr(ReportBuilder, "add_table", add_table)
            for mutation in (
                "reason",
                "bound",
                "coverage",
                "provenance_set",
                "note_set",
                "cell_context",
                "row_context",
                "context_limit",
            ):
                with pytest.raises(app.ReportServiceError) as failure:
                    await generate(report_case, key=f"invalid-cell-proof:{mutation}")
                assert failure.value.code is (
                    app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
                    if mutation == "context_limit"
                    else app.ReportServiceErrorCode.VALIDATION_FAILED
                ), mutation
                assert durable_counts() == before, mutation
        assert intercepted == 7

        # A real row with inherited metadata still resolves through its actual context.
        valid = await generate(report_case, key="inherited-cell-proof")
        assert valid.state is r.ReportJobState.QUEUED
        with report_case.base.sessions() as session:
            job = session.get(ReportJobModel, valid.job_id)
            assert job is not None
            payload = session.scalar(
                select(ReportInputChunkModel.payload).where(
                    ReportInputChunkModel.input_id == job.input_id,
                    ReportInputChunkModel.table_key == r.ReportTableKey.SNAPSHOT_TOTALS.value,
                )
            )
            assert payload is not None
            row = decode_report_chunk(payload).rows[0]
            assert row.context_key == "context.snapshot"
            assert row.cells[3].context_key is None
            assert row.cells[3].provenance_set_key is None
            assert row.cells[3].note_set_key is None

    asyncio.run(run())
