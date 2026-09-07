"""Explicit conversions from validated target wire inputs to domain values."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from trading212_api_contracts import targets as wire
from trading212_domain import targets as domain
from trading212_domain.values import CurrencyCode


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _holding(value: wire.TargetHoldingMapping | None) -> domain.TargetHoldingMapping | None:
    if value is None:
        return None
    identifier = value.requested_identifier
    return domain.TargetHoldingMapping(
        state=domain.TargetMappingState(value.state),
        instrument_id=_uuid(value.instrument_id),
        listing_id=_uuid(value.listing_id),
        preferred_listing_id=_uuid(value.preferred_listing_id),
        requested_identifier=(
            domain.TargetIdentifier(
                kind=domain.TargetIdentifierKind(identifier.kind),
                value=identifier.value,
                provider=identifier.provider,
            )
            if identifier is not None
            else None
        ),
        reason=value.reason,
    )


def target_content(value: wire.TargetContent) -> domain.TargetContent:
    return domain.TargetContent(
        nodes=tuple(
            domain.TargetNode(
                key=node.key,
                parent_key=node.parent_key,
                kind=domain.TargetNodeKind(node.kind),
                name=node.name,
                order=node.order,
                weight=Decimal(node.weight),
                holding=_holding(node.holding),
            )
            for node in value.nodes
        ),
        constraints=tuple(
            domain.TargetConstraint(
                key=item.key,
                kind=domain.TargetConstraintKind(item.kind),
                node_key=item.node_key,
                amount=_decimal(item.amount),
                currency=CurrencyCode(item.currency) if item.currency else None,
                weight=_decimal(item.weight),
                enabled=item.enabled,
                count=item.count,
                coefficient=_decimal(item.coefficient),
            )
            for item in value.constraints
        ),
        exclusions=tuple(
            domain.TargetExclusion(
                key=item.key,
                node_key=item.node_key,
                instrument_id=_uuid(item.instrument_id),
                listing_id=_uuid(item.listing_id),
                reason=item.reason,
            )
            for item in value.exclusions
        ),
    )
