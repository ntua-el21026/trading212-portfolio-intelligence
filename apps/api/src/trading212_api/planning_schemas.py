"""Exact input conversion and strict output projection for the planning API."""

from __future__ import annotations

from decimal import Decimal

from fastapi import Request, Response
from trading212_api_contracts import planning as wire
from trading212_application.planning import CreateContributionPlanCommand
from trading212_domain import planning as domain
from trading212_domain.serialization import canonical_json, to_primitive
from trading212_domain.targets import TargetConstraintKind
from trading212_domain.values import CurrencyCode, Money

from .target_routes import _error, target_response


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def planning_command(value: wire.CreateContributionPlanRequest) -> CreateContributionPlanCommand:
    return CreateContributionPlanCommand(
        account_id=value.account_id,
        virtual_portfolio_id=value.virtual_portfolio_id,
        target_version_id=value.target_version_id,
        snapshot_id=value.snapshot_id,
        options=domain.PlanningOptions(
            contribution=Money(
                Decimal(value.contribution.amount), CurrencyCode(value.contribution.currency)
            ),
            mode=domain.PlanningMode(value.mode),
            coverage_policy=domain.CoveragePolicy(value.coverage_policy),
            eligible_holding_ids=tuple(value.eligible_holding_ids)
            if value.eligible_holding_ids is not None
            else None,
            excluded_holding_ids=tuple(value.excluded_holding_ids),
            restricted_group_ids=tuple(value.restricted_group_ids),
            listing_preferences=tuple(
                domain.PlanningListingPreference(item.holding_id, item.listing_id)
                for item in value.listing_preferences
            ),
            allocation_constraints=tuple(
                domain.PlanningConstraint(
                    key=item.key,
                    kind=TargetConstraintKind(item.kind),
                    node_id=item.node_id,
                    amount=_decimal(item.amount),
                    currency=CurrencyCode(item.currency) if item.currency else None,
                    weight=_decimal(item.weight),
                    enabled=item.enabled,
                    count=item.count,
                    coefficient=_decimal(item.coefficient),
                )
                for item in value.allocation_constraints
            ),
            holding_constraints=tuple(
                domain.PlanningHoldingConstraint(
                    holding_id=item.holding_id,
                    minimum_amount=Decimal(item.minimum_amount),
                    value_increment=Decimal(item.value_increment),
                    maximum_post_weight=_decimal(item.maximum_post_weight),
                )
                for item in value.holding_constraints
            ),
            cash_reserve=_decimal(value.cash_reserve),
            monetary_quantum=_decimal(value.monetary_quantum),
        ),
    )


def planning_response[T: wire.PlanningSchema](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    conditional: bool = False,
    etag: str | None = None,
) -> Response:
    import hashlib

    try:
        payload = wire.canonical_planning_payload(to_primitive(value), schema)
        # Validate before computing a conditional validator; malformed results cannot 304.
        checked = schema.model_validate(payload).model_dump(mode="json")
    except (KeyError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The planning operation could not complete.")
    if conditional:
        etag = '"' + hashlib.sha256(canonical_json(checked).encode()).hexdigest() + '"'
    return target_response(
        request, checked, schema, etag=etag, status_code=status_code, conditional=conditional
    )
