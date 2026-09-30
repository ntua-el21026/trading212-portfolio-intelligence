"""Point-authorized saved FX references with an indexed, payload-bounded keyset."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import Session
from trading212_application import sources as app
from trading212_application.queries import CursorValidationError, cursor_binding
from trading212_domain.sources import ObservationState
from trading212_security.principals import AuthorizationError, Principal, Scope

from .source_models import FxObservationModel
from .source_store import digest, error

if TYPE_CHECKING:
    from .source_store import SourceStore

# No rate or source payload is selected by either authorization statement. All
# joins are one identity or latest-current indexed metadata; no source inventory
# is walked. Acquisition predicates validate original and current grants/licenses.
_PERSON = text("""
SELECT p.id,g.scope,g.granted_at,g.expires_at,a.id,c.id
FROM principals p
JOIN principal_scope_grants g ON g.principal_id=p.id
JOIN broker_connections c ON c.owner_id=p.owner_id
JOIN broker_accounts a ON a.connection_id=c.id
WHERE p.owner_id=:owner AND p.issuer=:issuer AND p.subject=:subject
 AND p.status='active' AND c.status='active' AND a.status='active' AND a.id=:account
 AND g.scope IN ('analytics:read','portfolio:read') AND g.granted_at<=:at
 AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at>:at)
ORDER BY g.scope
FOR SHARE OF p,g,c,a
""")
_SOURCE = text(
    "\n"
    "SELECT "
    "s.content_digest,s.first_observed_at,s.expires_at,s.effective_at"
    ",\n"
    " l.id AS original_license,c.id AS "
    "current_license,l.retention_days,c.retention_days,\n"
    " pub.id AS publication_id,pub.acquisition_digest,g.id AS "
    "original_grant,g.content_digest,\n"
    " cg.id AS current_grant,cg.content_digest,cg.expires_at\n"
    "FROM fx_snapshots s\n"
    "JOIN market_data_providers p ON p.owner_id=s.owner_id AND "
    "p.id=s.provider_id\n"
    "JOIN provider_license_versions l ON l.owner_id=s.owner_id AND "
    "l.id=s.license_version_id AND l.provider_id=s.provider_id\n"
    "JOIN LATERAL (\n"
    " SELECT x.* FROM provider_license_versions x\n"
    " WHERE x.owner_id=s.owner_id AND x.provider_id=s.provider_id AND "
    "x.effective_at<=:at\n"
    " ORDER BY x.effective_at DESC,x.version_number DESC,x.id DESC "
    "LIMIT 1\n"
    ") c ON true\n"
    "LEFT JOIN provider_acquisition_publications pub ON "
    "pub.owner_id=s.owner_id AND pub.source_kind='fx' AND "
    "pub.source_id=s.id\n"
    "LEFT JOIN provider_acquisition_attempts attempt ON "
    "attempt.owner_id=pub.owner_id AND attempt.id=pub.attempt_id\n"
    "LEFT JOIN provider_acquisition_requests request ON "
    "request.owner_id=attempt.owner_id AND "
    "request.id=attempt.request_id\n"
    "LEFT JOIN provider_capability_grants g ON "
    "g.owner_id=request.owner_id AND g.id=request.grant_id\n"
    "LEFT JOIN LATERAL (\n"
    " SELECT x.id,x.content_digest,x.expires_at FROM "
    "provider_capability_grants x\n"
    " WHERE x.owner_id=g.owner_id AND x.scope_id=g.scope_id AND "
    "x.effective_at<=:at\n"
    " ORDER BY x.effective_at DESC,x.version_number DESC,x.id DESC "
    "LIMIT 1\n"
    ") cg ON true\n"
    "WHERE s.owner_id=:owner AND s.id=:snapshot AND "
    "p.configuration_state='configured'\n"
    " AND s.first_observed_at<=:cutoff AND s.effective_at<=:cutoff\n"
    " AND s.first_observed_at<=:at AND s.effective_at<=:at AND "
    "l.effective_at<=:at\n"
    " AND l.store_permission='allowed' AND "
    "l.display_permission='allowed'\n"
    " AND c.store_permission='allowed' AND "
    "c.display_permission='allowed'\n"
    " AND l.retention_days IS NOT NULL AND c.retention_days IS NOT "
    "NULL\n"
    " AND "
    "s.expires_at<=s.first_observed_at+make_interval(days=>least(l.re"
    "tention_days,c.retention_days))\n"
    " AND s.expires_at>:at\n"
    " AND NOT EXISTS(SELECT 1 FROM source_retention_work w WHERE "
    "w.owner_id=s.owner_id AND w.fx_snapshot_id=s.id)\n"
    " AND NOT EXISTS(SELECT 1 FROM source_expiry_events e WHERE "
    "e.owner_id=s.owner_id AND e.fx_snapshot_id=s.id)\n"
    " AND NOT "
    "acquisition_source_restricted(s.owner_id,'fx',s.id,:at,'store')\n"
    " AND NOT "
    "acquisition_source_restricted(s.owner_id,'fx',s.id,:at,'display'"
    ")\n"
)
_RESOURCE = "fx-observation-references"
_SCOPES = frozenset((Scope.ANALYTICS_READ, Scope.PORTFOLIO_READ))


def _person(
    store: SourceStore,
    session: Session,
    principal: Principal,
    owner: UUID,
    account: UUID,
    at: datetime,
) -> str:
    for scope in _SCOPES:
        store._authorizer.require_scope(principal, scope, now=at)
    rows = session.execute(
        _PERSON,
        {
            "owner": owner,
            "issuer": principal.issuer,
            "subject": principal.subject,
            "account": account,
            "at": at,
        },
    ).all()
    if (
        len(rows) != 2
        or {row[1] for row in rows} != {x.value for x in _SCOPES}
        or len({row[0] for row in rows}) != 1
    ):
        raise AuthorizationError("access denied")
    return digest(tuple(tuple(row) for row in rows))


def _source(
    session: Session, owner: UUID, snapshot: UUID, cutoff: datetime, at: datetime
) -> tuple[object, ...]:
    row = session.execute(
        _SOURCE,
        {
            "owner": owner,
            "snapshot": snapshot,
            "cutoff": cutoff,
            "at": at,
        },
    ).one_or_none()
    if row is None:
        raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
    return tuple(row)


def reference_page(
    store: SourceStore,
    session: Session,
    principal: Principal,
    owner: UUID,
    snapshot_id: str,
    query: app.FxObservationReferenceQuery,
) -> app.FxObservationReferencePage:
    account, snapshot = UUID(query.account_id), UUID(snapshot_id)
    effective = query.effective_at_lte or query.source_cutoff_at
    # SourceStore._run already holds the canonical sources owner lock. Fresh
    # principal/account/grant checks precede private source metadata and rates.
    person = _person(store, session, principal, owner, account, store._now())
    source = _source(session, owner, snapshot, query.source_cutoff_at, store._now())
    fingerprint = digest(source)
    binding = cursor_binding(
        owner,
        principal.issuer,
        principal.subject,
        person,
        account,
        snapshot,
        source[0],
        fingerprint,
        query.base.value,
        query.quote.value,
        query.source_cutoff_at,
        effective,
        query.limit,
    )
    read_at = store._now()
    model = FxObservationModel
    statement = select(
        model.id, model.session_date, model.effective_at, model.rate, model.state
    ).where(
        model.owner_id == owner,
        model.snapshot_id == snapshot,
        model.base == query.base.value,
        model.quote == query.quote.value,
        model.effective_at <= effective,
    )
    if query.cursor is not None:
        read_at, key = store._cursors.decode(
            query.cursor, resource=_RESOURCE, binding=binding, key_size=2
        )
        try:
            after_at = datetime.fromisoformat(key[0])
            after_id = UUID(key[1])
            if (
                after_at.tzinfo is None
                or after_at.isoformat() != key[0]
                or str(after_id) != key[1]
                or after_at > effective
            ):
                raise ValueError
        except ValueError:
            raise CursorValidationError("invalid cursor") from None
        statement = statement.where(tuple_(model.effective_at, model.id) < (after_at, after_id))
    # ix_fx_observation_reference_page fixes owner/snapshot/pair and scans the
    # effective-time/id suffix backwards. No COUNT, OFFSET, full-ID preload,
    # metadata membership writes, Python post-filter or hidden provider fetch.
    rows = session.execute(
        statement.order_by(model.effective_at.desc(), model.id.desc()).limit(query.limit + 1)
    ).all()
    chosen = rows[: query.limit]
    token = (
        None
        if len(rows) <= query.limit
        else store._cursors.encode(
            resource=_RESOURCE,
            binding=binding,
            read_cutoff=read_at,
            key=(chosen[-1][2].isoformat(), str(chosen[-1][0])),
        )
    )
    # All header fields came from one typed PostgreSQL metadata result. Keeping
    # the SQL metadata tuple intact also binds current acquisition grant changes.
    content_digest, first_observed, expires = source[:3]
    if (
        not isinstance(content_digest, str)
        or not isinstance(first_observed, datetime)
        or not isinstance(expires, datetime)
    ):
        raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
    result = app.FxObservationReferencePage(
        account_id=str(account),
        snapshot_id=str(snapshot),
        content_digest=content_digest,
        base=query.base,
        quote=query.quote,
        source_cutoff_at=query.source_cutoff_at,
        effective_at_lte=effective,
        first_observed_at=first_observed,
        expires_at=expires,
        items=tuple(
            app.FxObservationReference(
                observation_id=str(row[0]),
                session_date=row[1],
                effective_at=row[2],
                rate=row[3],
                state=ObservationState(row[4]),
            )
            for row in chosen
        ),
        next_cursor=token,
        limit=query.limit,
    )
    # Re-read under the actual final clock, including conditional/empty pages.
    if _person(store, session, principal, owner, account, store._now()) != person:
        raise AuthorizationError("access denied")
    if (
        digest(_source(session, owner, snapshot, query.source_cutoff_at, store._now()))
        != fingerprint
    ):
        raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
    return result
