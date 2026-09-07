"""Idempotent synthetic target fixtures through the authorized production commands."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker
from trading212_application import targets as app
from trading212_domain import build_synthetic_identity
from trading212_domain import targets as domain
from trading212_domain.values import CurrencyCode
from trading212_persistence import PostgresTargetService
from trading212_security.principals import Principal, Scope


async def seed_target_scenarios(
    sessions: sessionmaker[Session], *, app_environment: str, at: datetime
) -> dict[str, str]:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("synthetic target seed is restricted to local/test environments")
    identity = build_synthetic_identity()
    principal = Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=frozenset({Scope.PORTFOLIO_READ, Scope.TARGETS_READ, Scope.TARGETS_WRITE}),
        authenticated_at=at - timedelta(minutes=1),
        expires_at=at + timedelta(hours=1),
    )
    service = PostgresTargetService(
        sessions=sessions,
        cursor_signing_key=hashlib.sha256(b"synthetic-target-seed-cursors/v1").digest(),
        clock=lambda: at,
    )
    content = domain.TargetContent(
        nodes=(
            domain.TargetNode(
                "growth", None, domain.TargetNodeKind.GROUP, "Growth", 0, Decimal("0.9")
            ),
            domain.TargetNode(
                "global-equity",
                "growth",
                domain.TargetNodeKind.HOLDING,
                "Synthetic Global Equity",
                1,
                Decimal("1"),
                domain.TargetHoldingMapping(
                    state=domain.TargetMappingState.RESOLVED,
                    instrument_id=identity.instrument.id,
                    preferred_listing_id=identity.listing.id,
                ),
            ),
            domain.TargetNode(
                "cash", None, domain.TargetNodeKind.CASH, "EUR cash", 2, Decimal("0.1")
            ),
        ),
        constraints=(
            domain.TargetConstraint(
                key="reserve",
                kind=domain.TargetConstraintKind.CASH_RESERVE,
                amount=Decimal("100"),
                currency=CurrencyCode("EUR"),
            ),
        ),
    )
    results: dict[str, str] = {}
    for name, account in (("account", str(identity.account.id)), ("template", None)):
        prefix = f"synthetic-target-seed-v1:{name}"
        portfolio = await service.create_virtual_portfolio(
            principal,
            app.CreateVirtualPortfolioCommand(
                name="Synthetic growth Pie" if account else "Synthetic growth template",
                reporting_currency=CurrencyCode("EUR"),
                account_id=account,
                description="Synthetic local target: 90% growth and 10% cash. No broker changes.",
            ),
            idempotency_key=f"{prefix}:create",
            correlation_id=prefix,
        )
        version = await service.create_target_version(
            principal,
            portfolio.id,
            app.CreateTargetVersionCommand(effective_at=at, content=content),
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
            raise RuntimeError("synthetic target validation did not complete successfully")
        published = await service.publish_target_version(
            principal,
            version.id,
            app.PublishTargetCommand(validation.id),
            if_match=validation.etag,
            idempotency_key=f"{prefix}:publish",
            correlation_id=prefix,
        )
        results[f"{name}_portfolio_id"] = portfolio.id
        results[f"{name}_version_id"] = published.id
    return results
