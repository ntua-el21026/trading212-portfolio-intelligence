"""Publish small account-scoped historical group targets through canonical commands."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker
from trading212_application import targets as app
from trading212_domain import targets as domain
from trading212_domain.values import CurrencyCode
from trading212_persistence import PostgresTargetService
from trading212_security.principals import Principal

from .historical_fixture import SyntheticHistoryScenario


async def seed_historical_target(
    sessions: sessionmaker[Session],
    principal: Principal,
    scenario: SyntheticHistoryScenario,
    at: datetime,
) -> str:
    """Retain one stable EUR/USD 60/40 target; repeated commands replay their first result."""
    instruments = {str(item.listing.trading_currency): item for item in scenario.instruments}
    if set(instruments) != {"EUR", "USD"} or len(scenario.instruments) != 2:
        raise ValueError("Historical target fixtures require exactly one EUR and one USD holding.")
    service = PostgresTargetService(
        sessions=sessions,
        cursor_signing_key=hashlib.sha256(b"synthetic-historical-target-cursors-v1").digest(),
        clock=lambda: at,
    )
    nodes: list[domain.TargetNode] = []
    for order, (currency, weight) in enumerate((("EUR", "0.6"), ("USD", "0.4"))):
        item = instruments[currency]
        group_key = currency.lower()
        nodes.extend(
            (
                domain.TargetNode(
                    key=group_key,
                    parent_key=None,
                    kind=domain.TargetNodeKind.GROUP,
                    name=f"{currency} holdings",
                    order=order * 2,
                    weight=Decimal(weight),
                ),
                domain.TargetNode(
                    key=f"{group_key}-holding",
                    parent_key=group_key,
                    kind=domain.TargetNodeKind.HOLDING,
                    name=f"Synthetic {currency} historical holding",
                    order=order * 2 + 1,
                    weight=Decimal("1"),
                    holding=domain.TargetHoldingMapping(
                        state=domain.TargetMappingState.RESOLVED,
                        instrument_id=item.instrument.id,
                        listing_id=item.listing.id,
                        preferred_listing_id=item.listing.id,
                    ),
                ),
            )
        )
    prefix = f"historical-target-seed-v1:{scenario.variant}"
    portfolio = await service.create_virtual_portfolio(
        principal,
        app.CreateVirtualPortfolioCommand(
            name=f"Synthetic {scenario.variant} historical groups",
            reporting_currency=CurrencyCode("EUR"),
            account_id=str(scenario.account.id),
            description="Synthetic 60% EUR and 40% USD historical grouping comparison.",
        ),
        idempotency_key=f"{prefix}:create",
        correlation_id=prefix,
    )
    version = await service.create_target_version(
        principal,
        portfolio.id,
        app.CreateTargetVersionCommand(
            effective_at=at, content=domain.TargetContent(nodes=tuple(nodes))
        ),
        if_match=portfolio.etag,
        idempotency_key=f"{prefix}:draft",
        correlation_id=prefix,
    )
    validation = await service.validate_target_version(
        principal,
        version.id,
        app.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=f"{prefix}:validate",
        correlation_id=prefix,
    )
    if not validation.valid:
        raise RuntimeError("The synthetic historical target did not validate.")
    published = await service.publish_target_version(
        principal,
        version.id,
        app.PublishTargetCommand(validation.id),
        if_match=validation.etag,
        idempotency_key=f"{prefix}:publish",
        correlation_id=prefix,
    )
    return published.id
