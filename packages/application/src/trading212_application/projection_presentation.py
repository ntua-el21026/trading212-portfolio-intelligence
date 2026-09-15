"""Pure saved projection presentation after current source authorization.

The store supplies verified, complete retained records and original source clocks.
This module neither loads data nor grants access, parses cursors, signs them, or
reruns sampled paths. Page selection and cursor finalization are separate so the
store retains its authorization and resource-bound cursor responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal, NoReturn
from uuid import UUID

from trading212_analytics._premium_numeric import arithmetic, q18
from trading212_analytics.projection_summary import nearest_rank
from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.projection import PROJECTION_PERCENTILES
from trading212_domain.projection_result import (
    ProjectionCalculation,
    ProjectionGoalResult,
    ProjectionHistogram,
    ProjectionPoint,
    ProjectionQuantiles,
    ProjectionVariantResult,
)
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import source_integer
from trading212_domain.values import CurrencyCode, Money, require_utc

from . import projection_views as v
from .projection import ProjectionErrorCode, ProjectionServiceError
from .projection_capture import ProjectionCapturePlan, projection_capture_digest
from .risk import PremiumJobState

PROJECTION_PREVIEW_LIMIT = 16
PROJECTION_CURSOR_BYTES = 2048
_QUALITY_ORDER = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.UNRECONCILED: 3,
    QualityState.PARTIAL: 4,
    QualityState.FAILED: 5,
}
type ProjectionWarning = Literal[
    "model_assumptions",
    "sampling_uncertainty",
    "model_uncertainty",
    "modeled_tax_drag",
    "numerical_zero_pivots",
    "source_stale",
    "source_partial",
    "source_unreconciled",
    "source_failed",
    "funding_failed",
    "unpaid_positive_below_quantum",
]
_WARNINGS = frozenset(
    (
        "model_assumptions",
        "sampling_uncertainty",
        "model_uncertainty",
        "modeled_tax_drag",
        "numerical_zero_pivots",
        "source_stale",
        "source_partial",
        "source_unreconciled",
        "source_failed",
        "funding_failed",
        "unpaid_positive_below_quantum",
    )
)


def _unavailable() -> NoReturn:
    raise ProjectionServiceError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)


def _bound() -> NoReturn:
    raise ProjectionServiceError(ProjectionErrorCode.INPUT_BOUND_EXCEEDED)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionRetainedEvidence:
    """Full retained evidence metadata; its identity is not authorization."""

    role: Literal["observed_snapshot", "calibration"]
    subject_id: UUID
    content_digest: str
    quality: QualityState
    source_reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if (
            self.role not in ("observed_snapshot", "calibration")
            or type(self.subject_id) is not UUID
            or type(self.content_digest) is not str
            or len(self.content_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.content_digest)
            or type(self.quality) is not QualityState
            or type(self.source_reference_ids) is not tuple
            or any(type(item) is not UUID for item in self.source_reference_ids)
            or self.source_reference_ids != tuple(sorted(set(self.source_reference_ids)))
        ):
            fail_validation("Canonical retained projection evidence is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class RetainedProjectionPresentation:
    """Complete authorized succeeded result with original immutable source clocks."""

    account_id: UUID
    run_id: UUID
    result_id: UUID
    capture_digest: str
    saved_result_digest: str
    capture: ProjectionCapturePlan
    calculation: ProjectionCalculation
    calculated_at: datetime
    source_cutoff_at: datetime | None
    quality: QualityState
    source_evidence: tuple[ProjectionRetainedEvidence, ...]
    warnings: tuple[ProjectionWarning, ...] = ()

    def __post_init__(self) -> None:
        if (
            any(type(item) is not UUID for item in (self.account_id, self.run_id, self.result_id))
            or type(self.capture) is not ProjectionCapturePlan
            or type(self.calculation) is not ProjectionCalculation
            or type(self.quality) is not QualityState
            or type(self.source_evidence) is not tuple
            or any(type(item) is not ProjectionRetainedEvidence for item in self.source_evidence)
            or type(self.warnings) is not tuple
            or any(type(item) is not str or item not in _WARNINGS for item in self.warnings)
            or len(set(self.warnings)) != len(self.warnings)
        ):
            fail_validation("Complete typed retained projection presentation is required.")
        object.__setattr__(self, "calculated_at", require_utc(self.calculated_at))
        if self.source_cutoff_at is not None:
            object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
            if self.source_cutoff_at > self.calculated_at:
                _unavailable()
        if (
            self.account_id != self.capture.selection.account_id
            or self.capture_digest != projection_capture_digest(self.capture)
            or self.calculation.inputs != self.capture.inputs
            or self.calculation.input_digest != self.capture.numerical_input_digest
            or self.saved_result_digest
            != sha256(projection_canonical_bytes(self.calculation)).hexdigest()
        ):
            _unavailable()
        expected = {
            ("calibration", UUID(pin.subject_id)): pin.content_digest
            for pin in self.capture.inputs.assumptions.calibration_pins
        }
        if self.capture.snapshot is not None:
            expected[("observed_snapshot", self.capture.snapshot.snapshot_id)] = (
                self.capture.snapshot.content_digest
            )
        actual = {
            (item.role, item.subject_id): item.content_digest for item in self.source_evidence
        }
        if actual != expected or len(actual) != len(self.source_evidence):
            _unavailable()


def _preview[Item](items: tuple[Item, ...]) -> v.ProjectionPreview[Item]:
    return v.ProjectionPreview(
        items=items[:PROJECTION_PREVIEW_LIMIT],
        omitted_count=max(0, len(items) - PROJECTION_PREVIEW_LIMIT),
    )


def _context(saved: RetainedProjectionPresentation) -> v.ProjectionResultContextView:
    capture, result = saved.capture, saved.calculation
    evidence = tuple(sorted(saved.source_evidence, key=lambda item: (item.role, item.subject_id)))
    quality = max(
        (QualityState.ESTIMATED, saved.quality, *(item.quality for item in evidence)),
        key=_QUALITY_ORDER.__getitem__,
    )
    warnings = set(saved.warnings) | {
        "model_assumptions",
        "sampling_uncertainty",
        "model_uncertainty",
    }
    if capture.inputs.assumptions.annual_tax_drag:
        warnings.add("modeled_tax_drag")
    if result.numerical_zero_pivots:
        warnings.add("numerical_zero_pivots")
    for item in evidence:
        if item.quality in (
            QualityState.STALE,
            QualityState.PARTIAL,
            QualityState.UNRECONCILED,
            QualityState.FAILED,
        ):
            warnings.add(f"source_{item.quality.value}")
    terminals = tuple(path.points[-1] for variant in result.variants for path in variant.paths)
    if any(point.funding_failed for point in terminals):
        warnings.add("funding_failed")
    if any(point.unpaid_positive_below_quantum for point in terminals):
        warnings.add("unpaid_positive_below_quantum")
    return v.ProjectionResultContextView(
        account_id=saved.account_id,
        run_id=saved.run_id,
        result_id=saved.result_id,
        capture_digest=saved.capture_digest,
        numerical_input_digest=result.input_digest,
        saved_result_digest=saved.saved_result_digest,
        assumption_version_digest=capture.assumption_version.content_digest,
        goal_version_digest=None
        if capture.goal_version is None
        else capture.goal_version.content_digest,
        selection=capture.selection,
        assumptions=capture.inputs.assumptions,
        anchor_date=capture.calendar.anchor_date,
        terminal_date=capture.calendar.terminal_date,
        snapshot_valuation_at=None if capture.snapshot is None else capture.snapshot.valuation_at,
        source_cutoff_at=saved.source_cutoff_at,
        calculated_at=saved.calculated_at,
        reporting_currency=capture.inputs.assumptions.reporting_currency,
        quality=quality,
        source_evidence=_preview(
            tuple(
                v.ProjectionEvidenceView(
                    role=item.role,
                    subject_id=item.subject_id,
                    content_digest=item.content_digest,
                    quality=item.quality,
                    source_reference_ids=_preview(item.source_reference_ids),
                )
                for item in evidence
            )
        ),
        warnings=_preview(tuple(sorted(warnings))),
        numerical_zero_pivots=result.numerical_zero_pivots,
        method=result.method,
        method_version=result.method_version,
        schema_version=capture.schema_version,
        numeric_profile=result.numeric_profile,
        sampler=result.sampler,
        calendar_rule=capture.calendar.rule,
    )


def _quantiles(value: ProjectionQuantiles, currency: CurrencyCode) -> v.ProjectionQuantilesView:
    return v.ProjectionQuantilesView(
        probabilities=value.probabilities,
        values=tuple(Money(item, currency) for item in value.values),
    )


def _amount_summary(
    values: tuple[tuple[int, Decimal], ...], currency: CurrencyCode
) -> v.ProjectionAmountSummaryView:
    # Sum and division run in the frozen context, independently of the host context.
    with arithmetic():
        mean = q18(sum((amount for _, amount in values), Decimal(0)) / len(values))
    return v.ProjectionAmountSummaryView(
        mean=Money(mean, currency),
        quantiles=v.ProjectionQuantilesView(
            probabilities=PROJECTION_PERCENTILES,
            values=tuple(Money(nearest_rank(values, p), currency) for p in PROJECTION_PERCENTILES),
        ),
    )


def _cash_flows(
    value: ProjectionVariantResult, currency: CurrencyCode
) -> v.ProjectionCashFlowSummaryView:
    terminal = tuple((path.index, path.points[-1]) for path in value.paths)

    def amounts(name: str) -> v.ProjectionAmountSummaryView:
        return _amount_summary(
            tuple((index, getattr(point, name)) for index, point in terminal), currency
        )

    return v.ProjectionCashFlowSummaryView(
        contributions=amounts("contributions"),
        withdrawals_requested=amounts("withdrawals_requested"),
        withdrawals_funded=amounts("withdrawals_funded"),
        unpaid_withdrawals=amounts("unpaid_withdrawals"),
        investment_effect=amounts("investment_effect"),
        fees=amounts("fees"),
        tax_drag=amounts("tax_drag"),
        funding_failed_paths=sum(point.funding_failed for _, point in terminal),
        unpaid_positive_below_quantum_paths=sum(
            point.unpaid_positive_below_quantum for _, point in terminal
        ),
    )


def _histogram(value: ProjectionHistogram, currency: CurrencyCode) -> v.ProjectionHistogramView:
    return v.ProjectionHistogramView(
        observed_minimum=Money(value.observed_minimum, currency),
        observed_maximum=Money(value.observed_maximum, currency),
        boundary_rule=value.boundary_rule,
        bins=tuple(
            v.ProjectionHistogramBinView(
                lower=Money(item.lower, currency),
                upper=Money(item.upper, currency),
                upper_inclusive=item.upper_inclusive,
                count=item.count,
            )
            for item in value.bins
        ),
    )


def _goal(value: ProjectionGoalResult, currency: CurrencyCode) -> v.ProjectionGoalEstimateView:
    return v.ProjectionGoalEstimateView(
        goal_version_id=UUID(value.goal_version_id),
        basis=value.basis,
        target=Money(value.target, currency),
        paths=value.paths,
        successes=value.successes,
        probability=value.probability,
        interval_low=value.interval_low,
        interval_high=value.interval_high,
        probability_objective=value.probability_objective,
        objective_met=value.objective_met,
        mean_shortfall=Money(value.mean_shortfall, currency),
        shortfalls=_quantiles(value.shortfalls, currency),
        funding_failed_paths=value.funding_failed_paths,
        method=value.method,
        interval_method=value.interval_method,
    )


def _summaries(saved: RetainedProjectionPresentation) -> tuple[v.ProjectionVariantSummaryView, ...]:
    currency = saved.capture.inputs.assumptions.reporting_currency
    return tuple(
        v.ProjectionVariantSummaryView(
            variant=value.variant,
            distributions=tuple(
                v.ProjectionDistributionView(
                    month=item.month,
                    on=saved.capture.calendar.boundaries[item.month],
                    nominal_mean=Money(item.nominal_mean, currency),
                    real_mean=Money(item.real_mean, currency),
                    nominal=_quantiles(item.nominal, currency),
                    real=_quantiles(item.real, currency),
                    funding_failed_paths=item.funding_failed_paths,
                )
                for item in value.distributions
            ),
            nominal_histogram=_histogram(value.nominal_histogram, currency),
            real_histogram=_histogram(value.real_histogram, currency),
            cash_flows=_cash_flows(value, currency),
            goal=None if value.goal is None else _goal(value.goal, currency),
        )
        for value in saved.calculation.variants
    )


def _point(value: ProjectionPoint, currency: CurrencyCode) -> v.ProjectionPointView:
    return v.ProjectionPointView(
        month=value.month,
        nominal=Money(value.nominal, currency),
        real=Money(value.real, currency),
        assets=tuple(
            v.ProjectionAssetValueView(key=item.key, value=Money(item.value, currency))
            for item in value.assets
        ),
        contributions=Money(value.contributions, currency),
        withdrawals_requested=Money(value.withdrawals_requested, currency),
        withdrawals_funded=Money(value.withdrawals_funded, currency),
        unpaid_withdrawals=Money(value.unpaid_withdrawals, currency),
        investment_effect=Money(value.investment_effect, currency),
        fees=Money(value.fees, currency),
        tax_drag=Money(value.tax_drag, currency),
        wealth_residual=Money(value.wealth_residual, currency),
        allocation_residual=Money(value.allocation_residual, currency),
        withdrawal_residual=Money(value.withdrawal_residual, currency),
        funding_failed=value.funding_failed,
        unpaid_positive_below_quantum=value.unpaid_positive_below_quantum,
    )


def _row(saved: RetainedProjectionPresentation, ordinal: int) -> v.ProjectionPointRow:
    point_count = len(saved.capture.inputs.retained_months)
    variant_index, within_variant = divmod(ordinal, saved.capture.inputs.paths * point_count)
    path_index, point_index = divmod(within_variant, point_count)
    variant = saved.calculation.variants[variant_index]
    path = variant.paths[path_index]
    point = path.points[point_index]
    return v.ProjectionPointRow(
        ordinal=ordinal,
        variant=variant.variant,
        path_index=path.index,
        point_index=point_index,
        path_point_count=point_count,
        first_unpaid_month=path.first_unpaid_month,
        on=saved.capture.calendar.boundaries[point.month],
        point=_point(point, path.reporting_currency),
    )


type _PublicPage = v.ProjectionResultPage | v.GoalAnalysisView


def projection_public_bytes(value: _PublicPage) -> bytes:
    if type(value) not in (v.ProjectionResultPage, v.GoalAnalysisView):
        fail_validation("A fixed projection public view is required.")
    return canonical_json(value).encode("utf-8")


def _signed[Page: _PublicPage](page: Page) -> Page:
    content = {
        item.name: getattr(page, item.name)
        for item in fields(page)
        if item.name != "content_digest"
    }
    digest = sha256(
        b"t212pi.projection.public.v1\0" + canonical_json(content).encode("utf-8")
    ).hexdigest()
    return replace(page, content_digest=digest)


def validate_projection_response_bytes(payload: bytes) -> None:
    """Transport calls this on its complete serialized envelope immediately before sending."""
    if type(payload) is not bytes:
        fail_validation("The complete serialized projection envelope must be bytes.")
    if len(payload) > v.PROJECTION_PUBLIC_RESPONSE_BYTES:
        _bound()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPageSelection:
    """Internal selection, never a public page before cursor finalization."""

    context: v.ProjectionResultContextView
    variants: tuple[v.ProjectionVariantSummaryView, ...]
    items: tuple[v.ProjectionPointRow, ...]
    point_limit: int
    total: int
    start_ordinal: int
    next_ordinal: int | None


def _page(selection: ProjectionPageSelection, cursor: str | None) -> v.ProjectionResultPage:
    return v.ProjectionResultPage(
        context=selection.context,
        variants=selection.variants,
        content_digest="0" * 64,
        points=v.ProjectionPointPage(
            items=selection.items,
            point_limit=selection.point_limit,
            next_cursor=cursor,
            total=selection.total,
            start_ordinal=selection.start_ordinal,
        ),
    )


def select_projection_page(
    saved: RetainedProjectionPresentation, *, offset: int = 0, limit: int = 25
) -> ProjectionPageSelection:
    source_integer(limit, "point_limit", 1, 100)
    total = (
        len(saved.calculation.variants)
        * saved.capture.inputs.paths
        * len(saved.capture.inputs.retained_months)
    )
    source_integer(offset, "point_offset", 0, total - 1)
    selection = ProjectionPageSelection(
        context=_context(saved),
        variants=_summaries(saved),
        items=(),
        point_limit=limit,
        total=total,
        start_ordinal=offset,
        next_ordinal=offset,
    )
    # The store uses unpadded URL-safe ASCII cursors, which require no JSON
    # escaping. Reserve the entire accepted cursor length before adding rows.
    reserve = "x" * PROJECTION_CURSOR_BYTES
    if len(projection_public_bytes(_page(selection, None))) > v.PROJECTION_PUBLIC_PAGE_BYTES:
        _bound()
    for ordinal in range(offset, min(total, offset + limit)):
        following = ordinal + 1 if ordinal + 1 < total else None
        candidate = replace(
            selection, items=(*selection.items, _row(saved, ordinal)), next_ordinal=following
        )
        if (
            len(
                projection_public_bytes(
                    _page(candidate, reserve if following is not None else None)
                )
            )
            > v.PROJECTION_PUBLIC_PAGE_BYTES
        ):
            if not selection.items:
                _bound()
            break
        selection = candidate
    return selection


def finalize_projection_page(
    selection: ProjectionPageSelection, *, next_cursor: str | None
) -> v.ProjectionResultPage:
    if (selection.next_ordinal is None) != (next_cursor is None):
        fail_validation("A projection continuation cursor is required exactly when rows remain.")
    if next_cursor is not None and (
        type(next_cursor) is not str
        or not 1 <= len(next_cursor) <= PROJECTION_CURSOR_BYTES
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in next_cursor
        )
    ):
        fail_validation("A bounded signed ASCII projection cursor is required.")
    source_integer(selection.point_limit, "point_limit", 1, 100)
    source_integer(selection.total, "point_total", 1, 3 * 4096 * 121)
    source_integer(selection.start_ordinal, "point_offset", 0, selection.total - 1)
    end = selection.start_ordinal + len(selection.items)
    if (
        not selection.items
        or len(selection.items) > selection.point_limit
        or end > selection.total
        or tuple(row.ordinal for row in selection.items)
        != tuple(range(selection.start_ordinal, end))
        or selection.next_ordinal != (end if end < selection.total else None)
    ):
        fail_validation("Projection selection must make contiguous whole-row progress.")
    page = _signed(_page(selection, next_cursor))
    if len(projection_public_bytes(page)) > v.PROJECTION_PUBLIC_PAGE_BYTES:
        _bound()
    return page


def project_goal_analysis(saved: RetainedProjectionPresentation) -> v.GoalAnalysisView:
    """Copy all saved goal variants; terminal quantiles use the pinned goal basis."""
    variants: list[v.GoalVariantAnalysisView] = []
    currency = saved.capture.inputs.assumptions.reporting_currency
    for value in saved.calculation.variants:
        if value.goal is not None:
            terminal = value.distributions[-1]
            variants.append(
                v.GoalVariantAnalysisView(
                    variant=value.variant,
                    terminal=_quantiles(
                        terminal.nominal if value.goal.basis == "nominal" else terminal.real,
                        currency,
                    ),
                    estimate=_goal(value.goal, currency),
                )
            )
    goal_id = saved.capture.selection.goal_version_id
    page = _signed(
        v.GoalAnalysisView(
            account_id=saved.account_id,
            run_id=saved.run_id,
            goal_version_id=goal_id,
            state=PremiumJobState.SUCCEEDED,
            result_availability="available",
            availability="available" if goal_id is not None else "unavailable",
            reason=None if goal_id is not None else "no_goal_pinned",
            context=_context(saved) if goal_id is not None else None,
            variants=tuple(variants),
            content_digest="0" * 64,
        )
    )
    if len(projection_public_bytes(page)) > v.PROJECTION_PUBLIC_PAGE_BYTES:
        _bound()
    return page


def unavailable_goal_analysis(run: v.ProjectionOperationalRunView) -> v.GoalAnalysisView:
    """Operational states require no financial decode, including expired succeeded jobs."""
    if run.goal_version_id is None:
        reason: Literal[
            "no_goal_pinned", "run_pending", "run_failed", "run_expired", "run_cancelled"
        ] = "no_goal_pinned"
    elif run.result_availability == "expired" or run.state is PremiumJobState.EXPIRED:
        reason = "run_expired"
    elif run.state in (PremiumJobState.QUEUED, PremiumJobState.RUNNING):
        reason = "run_pending"
    elif run.state is PremiumJobState.CANCELLED:
        reason = "run_cancelled"
    elif run.state is PremiumJobState.FAILED:
        reason = "run_failed"
    else:
        _unavailable()
    page = _signed(
        v.GoalAnalysisView(
            account_id=run.account_id,
            run_id=run.id,
            goal_version_id=run.goal_version_id,
            state=run.state,
            result_availability=run.result_availability,
            availability="unavailable",
            reason=reason,
            context=None,
            variants=(),
            content_digest="0" * 64,
        )
    )
    if len(projection_public_bytes(page)) > v.PROJECTION_PUBLIC_PAGE_BYTES:
        _bound()
    return page
