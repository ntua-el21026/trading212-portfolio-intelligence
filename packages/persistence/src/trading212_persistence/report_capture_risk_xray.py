"""Retain the selected X-ray terminal paths as bounded premium report proof."""

from collections.abc import Iterable

from trading212_domain import reports as r
from trading212_domain import xray as d
from trading212_domain.errors import fail_validation
from trading212_domain.xray_result import XrayCalculation

from .report_builder import ReportBuilder
from .report_capture_xray import _row


def capture_risk_xray_paths(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.XrayInput,
    result: XrayCalculation,
) -> None:
    """Copy exact root/issuer/weight facts for every retained path, without lookups."""
    roots: dict[str, d.PositionRoot | d.CashRoot] = {
        item.root.key: item.root for item in value.positions
    }
    roots.update({item.root.key: item.root for item in value.cash})
    r.report_limit(len(result.terminal_paths) <= r.MAX_REPORT_DATASET_ROWS, "rows")
    if any(path.root_key not in roots for path in result.terminal_paths):
        fail_validation("Risk X-ray path root is absent.", field="risk_run_id")

    def rows() -> Iterable[r.ReportRow]:
        for ordinal, path in enumerate(result.terminal_paths):
            root = roots[path.root_key]
            company = next(
                metric.normalized_known_weight
                for metric in path.dimension_weights
                if metric.dimension is d.XrayDimension.COMPANY
            )
            # Display the pinned identity itself: a latest entity-name lookup would
            # add data outside the selected immutable calculation.
            name = (
                str(path.entity_id)
                if path.entity_id is not None
                else str(path.instrument_id)
                if path.instrument_id is not None
                else "Cash"
                if path.explicit_cash
                else "Unresolved exposure"
            )
            yield _row(
                builder,
                context,
                r.ReportTableKey.RISK_XRAY_PATHS_V1,
                f"{context.key}.terminal_path.{ordinal}",
                path,
                extra={
                    "root_kind": "position" if isinstance(root, d.PositionRoot) else "cash",
                    "position_id": root.position_id if isinstance(root, d.PositionRoot) else None,
                    "name": name,
                    "normalized_known_weight": company,
                },
            )

    builder.add_table(r.ReportTableKey.RISK_XRAY_PATHS_V1, rows())
