"""Batched current owner/account authority before decoding saved preference payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from trading212_application import owner_layouts as app
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

_AUTHORITY = text(
    "\n"
    "WITH identity AS MATERIALIZED (\n"
    " SELECT id FROM principals WHERE owner_id=:owner AND "
    "issuer=:issuer AND subject=:subject\n"
    " AND status='active' AND NOT EXISTS(SELECT 1 FROM "
    "owner_layout_erasure e WHERE e.owner_id=:owner) FOR SHARE\n"
    "), grants AS MATERIALIZED (\n"
    " SELECT g.scope FROM principal_scope_grants g JOIN identity p ON "
    "p.id=g.principal_id\n"
    " WHERE g.granted_at<=:at AND g.revoked_at IS NULL AND "
    "(g.expires_at IS NULL OR g.expires_at>:at)\n"
    " FOR SHARE OF g\n"
    ")\n"
    "SELECT p.id, ARRAY(SELECT scope FROM grants) AS scopes FROM "
    "identity p\n"
)

# The bounded JSON argument contains only locally built, typed identity records; it is
# never accepted from the public API and never becomes SQL identifiers or a query DSL.
_REFERENCES = text(
    "\n"
    "WITH refs AS MATERIALIZED (\n"
    " SELECT * FROM jsonb_to_recordset(CAST(:refs AS jsonb)) AS r(\n"
    "  key text, account_id uuid, risk_run_id uuid, scenario_run_id "
    "uuid, projection_run_id uuid,\n"
    "  xray_run_id uuid, snapshot_id uuid, capture_id uuid, entity_id "
    "uuid, selection_kind text, route text,\n"
    "  start_date date,end_date date,source_cutoff_at "
    "timestamptz,reporting_currency text,knowledge text)\n"
    "), accounts AS MATERIALIZED (\n"
    " SELECT a.id FROM broker_accounts a JOIN broker_connections c ON "
    "c.id=a.connection_id\n"
    " WHERE a.id IN (SELECT account_id FROM refs) AND "
    "c.owner_id=:owner\n"
    " AND a.status='active' AND c.status='active' FOR SHARE OF a,c\n"
    ")\n"
    "SELECT r.key,\n"
    " (r.account_id IS NULL OR (:portfolio AND EXISTS(SELECT 1 FROM "
    "accounts a WHERE a.id=r.account_id))) account_ok,\n"
    " ((r.risk_run_id IS NULL OR EXISTS(SELECT 1 FROM risk_runs x "
    "WHERE x.id=r.risk_run_id AND x.owner_id=:owner AND "
    "x.account_id=r.account_id))\n"
    " AND (r.scenario_run_id IS NULL OR EXISTS(SELECT 1 FROM "
    "scenario_runs x WHERE x.id=r.scenario_run_id AND "
    "x.owner_id=:owner AND x.account_id=r.account_id))\n"
    " AND (r.projection_run_id IS NULL OR EXISTS(SELECT 1 FROM "
    "projection_runs x WHERE x.id=r.projection_run_id AND "
    "x.owner_id=:owner AND x.account_id=r.account_id))\n"
    " AND (r.xray_run_id IS NULL OR EXISTS(SELECT 1 FROM xray_runs x "
    "JOIN xray_input_snapshots i ON i.id=x.input_id AND "
    "i.owner_id=x.owner_id\n"
    "  WHERE x.id=r.xray_run_id AND x.owner_id=:owner AND "
    "i.account_id=r.account_id AND x.sealed_at IS NOT NULL\n"
    "  AND (r.selection_kind<>'saved_run' OR "
    "(i.snapshot_id=r.snapshot_id AND "
    "i.source_cutoff_at=r.source_cutoff_at AND "
    "i.reporting_currency=r.reporting_currency))))\n"
    " AND (r.capture_id IS NULL OR EXISTS(SELECT 1 FROM "
    "historical_input_snapshots h WHERE h.id=r.capture_id AND "
    "h.owner_id=:owner AND h.broker_account_id=r.account_id AND "
    "h.sealed\n"
    "  AND h.period_start=r.start_date AND h.period_end=r.end_date "
    "AND h.source_cutoff_at=r.source_cutoff_at\n"
    "  AND h.reporting_currency=r.reporting_currency AND "
    "h.knowledge_policy=r.knowledge))\n"
    " AND (r.entity_id IS NULL OR EXISTS(SELECT 1 FROM "
    "economic_entities e WHERE e.id=r.entity_id AND "
    "e.owner_id=:owner))) selection_ok\n"
    "FROM refs r\n"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class LayoutAuthority:
    owner_id: UUID
    principal_id: UUID
    portfolio_read: bool


def authorize_layout_owner(
    session: Session, principal: Principal, *, write: bool, now: datetime
) -> LayoutAuthority:
    at = require_utc(now)
    scopes = app.LAYOUT_WRITE_SCOPES if write else app.LAYOUT_READ_SCOPES
    for scope in scopes:
        Authorizer().require_scope(principal, scope, now=at)
    try:
        owner = UUID(principal.owner_id)
    except ValueError:
        raise AuthorizationError("access denied") from None
    row = session.execute(
        _AUTHORITY,
        {"owner": owner, "issuer": principal.issuer, "subject": principal.subject, "at": at},
    ).one_or_none()
    if row is None or not {scope.value for scope in scopes}.issubset(row.scopes):
        raise AuthorizationError("access denied")
    return LayoutAuthority(
        owner_id=owner,
        principal_id=row.id,
        portfolio_read=Scope.PORTFOLIO_READ in principal.scopes
        and Scope.PORTFOLIO_READ.value in row.scopes,
    )


def authorize_layout_references(
    session: Session, authority: LayoutAuthority, refs: tuple[dict[str, Any], ...]
) -> dict[str, str | None]:
    if len(refs) > 32 * 24:
        raise app.OwnerLayoutServiceError(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
    if not refs:
        return {}
    result: dict[str, str | None] = {}
    for row in session.execute(
        _REFERENCES,
        {
            "refs": json.dumps(refs, separators=(",", ":")),
            "owner": authority.owner_id,
            "portfolio": authority.portfolio_read,
        },
    ):
        reason = (
            "account_unavailable"
            if not row.account_ok
            else "selection_unavailable"
            if not row.selection_ok
            else None
        )
        # A version's account failure has precedence over a narrower pointer failure.
        prior = result.get(row.key)
        result[row.key] = (
            "account_unavailable" if "account_unavailable" in (prior, reason) else prior or reason
        )
    if set(result) != {ref["key"] for ref in refs}:
        raise AuthorizationError("access denied")
    return result


def require_layout_references(
    session: Session, authority: LayoutAuthority, refs: tuple[dict[str, Any], ...]
) -> None:
    if any(
        reason is not None
        for reason in authorize_layout_references(session, authority, refs).values()
    ):
        raise app.OwnerLayoutServiceError(app.OwnerLayoutErrorCode.ACCESS_DENIED)
