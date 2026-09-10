"""Exact, typed copies of saved planning operands and their original provenance."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast
from uuid import UUID

from trading212_application import reports as app
from trading212_domain import planning as d
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.planning_serialization import planning_input_digest
from trading212_domain.report_schema import table_schema
from trading212_domain.values import CurrencyCode

from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_row


def _proof(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    values: Mapping[str, ReportValue],
    *,
    currency: CurrencyCode | None = None,
    quality: QualityState | None = None,
) -> None:
    builder.add_proof(
        r.ReportProofRelation(
            table=table,
            row=capture_row(
                builder,
                context,
                table,
                key=key,
                values=values,
                currency=currency or builder.selection.reporting_currency,
                quality=quality,
            ),
        )
    )


def capture_planning_sources(
    builder: ReportBuilder,
    context: r.ReportContext,
    sources: Iterable[d.PlanningSource],
    *,
    key: str,
) -> None:
    kinds = {
        "portfolio_snapshot": r.ReportSourceKind.PORTFOLIO_SNAPSHOT,
        "calculation_run": r.ReportSourceKind.CALCULATION,
        "target_version": r.ReportSourceKind.TARGET_VERSION,
        "provider_observation": r.ReportSourceKind.BROKER_SOURCE_RECORD,
        "provider_fx_observation": r.ReportSourceKind.BROKER_SOURCE_RECORD,
    }
    for source in sources:
        if source.kind not in kinds:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        identity = f"{key}.source.{source.kind}.{source.id}"
        builder.add_reference(
            r.ReportSourceReference(
                key=identity,
                kind=kinds[source.kind],
                subject_id=UUID(source.id),
                content_digest=source.content_digest,
                source_at=source.effective_at,
                first_observed_at=source.first_observed_at,
            ),
            provenance_set_key=context.provenance_set_key,
        )
        _proof(
            builder,
            context,
            r.ReportTableKey.PLAN_SOURCE_DETAILS,
            identity,
            {
                "context_key": context.key,
                "kind": source.kind,
                "id": source.id,
                "version": source.version,
                "content_digest": source.content_digest,
                "effective_at": source.effective_at,
                "first_observed_at": source.first_observed_at,
            },
        )


def capture_plan_input(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.PlanningInput,
    *,
    request_id: UUID,
    input_digest: str,
) -> None:
    """No valuation is recomputed; the complete saved input digest is checked first."""
    if planning_input_digest(value) != input_digest:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    valuation, options = value.valuation, value.options
    _proof(
        builder,
        context,
        r.ReportTableKey.PLAN_INPUT_HEADER,
        "plan.input",
        {
            "request_id": request_id,
            "input_digest": input_digest,
            "virtual_portfolio_id": value.virtual_portfolio_id,
            "target_version_id": value.target_version_id,
            "target_content_digest": value.target_content_digest,
            "target_effective_at": value.target_effective_at,
            "target_published_at": value.target_published_at,
            "method_version": value.method_version,
            "schema_version": value.schema_version,
            "currency_policy_version": value.currency_policy_version,
        },
    )
    _proof(
        builder,
        context,
        r.ReportTableKey.PLAN_VALUATION,
        "plan.input.valuation",
        {
            "snapshot_id": valuation.snapshot_id,
            "account_id": valuation.account_id,
            "reporting_currency": valuation.reporting_currency.value,
            "valuation_at": valuation.valuation_at,
            "source_cutoff_at": valuation.source_cutoff_at,
            "content_digest": valuation.content_digest,
            "portfolio_total": valuation.portfolio_total,
            "quality": valuation.quality,
            "coverage_complete": valuation.coverage_complete,
            "reconciled": valuation.reconciled,
        },
        quality=valuation.quality,
    )
    groups: tuple[
        tuple[str, tuple[d.ValuationPosition | d.ValuationCash, ...], r.ReportTableKey], ...
    ] = (
        ("position", valuation.positions, r.ReportTableKey.PLAN_VALUATION_POSITIONS),
        ("cash", valuation.cash_components, r.ReportTableKey.PLAN_VALUATION_CASH),
    )
    for kind, components, table in groups:
        for ordinal, component in enumerate(components):
            key = f"plan.input.{kind}.{ordinal}"
            fx_key = f"{key}.fx" if component.fx is not None else None
            values: dict[str, ReportValue] = {
                "ordinal": ordinal,
                "value": component.value,
                "quality": component.quality,
                "fx_key": fx_key,
            }
            if isinstance(component, d.ValuationPosition):
                values.update(
                    listing_id=component.listing_id, instrument_id=component.instrument_id
                )
            _proof(builder, context, table, key, values, quality=component.quality)
            if (fx := component.fx) is not None:
                assert fx_key is not None
                _proof(
                    builder,
                    context,
                    r.ReportTableKey.PLAN_FX,
                    fx_key,
                    {
                        "key": fx_key,
                        "source_kind": fx.source.kind,
                        "source_id": fx.source.id,
                        "base": fx.base.value,
                        "quote": fx.quote.value,
                        "rate": fx.rate,
                    },
                    quality=component.quality,
                )
    _proof(
        builder,
        context,
        r.ReportTableKey.PLAN_OPTIONS,
        "plan.input.options",
        {
            "contribution": options.contribution,
            "mode": options.mode,
            "coverage_policy": options.coverage_policy,
            "eligibility_explicit": options.eligible_holding_ids is not None,
            "cash_reserve": options.cash_reserve,
            "monetary_quantum": options.monetary_quantum,
        },
        currency=options.contribution.currency,
    )
    for kind, members in (
        ("eligible", options.eligible_holding_ids or ()),
        ("excluded", options.excluded_holding_ids),
        ("restricted_group", options.restricted_group_ids),
        ("missing_input", valuation.missing_inputs),
    ):
        for ordinal, member in enumerate(members):
            _proof(
                builder,
                context,
                r.ReportTableKey.PLAN_INPUT_MEMBERS,
                f"plan.input.{kind}.{ordinal}",
                {"relation_kind": kind, "ordinal": ordinal, "member_key": member},
            )
    for table, records in (
        (r.ReportTableKey.PLAN_LISTING_PREFERENCES, options.listing_preferences),
        (r.ReportTableKey.PLAN_HOLDING_CONSTRAINTS, options.holding_constraints),
        (r.ReportTableKey.PLAN_ALLOCATION_CONSTRAINTS, options.allocation_constraints),
        (r.ReportTableKey.PLAN_NODE_IDENTITIES, value.node_identities),
        (r.ReportTableKey.PLAN_CATALOG_INSTRUMENTS, value.catalog.instruments),
        (r.ReportTableKey.PLAN_CATALOG_LISTINGS, value.catalog.listings),
    ):
        for ordinal, record in enumerate(records):
            currency = record.currency if isinstance(record, d.PlanningConstraint) else None
            _proof(
                builder,
                context,
                table,
                f"plan.input.{table.value}.{ordinal}",
                {
                    column.key: cast(
                        ReportValue, raw.value if isinstance(raw, CurrencyCode) else raw
                    )
                    for column in table_schema(table).columns
                    for raw in (getattr(record, column.key),)
                },
                currency=currency or options.contribution.currency,
            )
    capture_planning_sources(builder, context, valuation.sources, key="plan.input")
