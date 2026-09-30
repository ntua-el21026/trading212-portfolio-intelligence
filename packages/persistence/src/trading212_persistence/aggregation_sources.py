"""Fixed metadata-only source authority for complete retained aggregate dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from trading212_application import aggregation as app
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceUse
from trading212_domain.values import require_utc

from .aggregation_authorization import AggregateAuthorization

# The query returns no price/rate/source payload. Both requested identity sets are
# exact and bounded; a missing, foreign, expired or restricted row fails cardinality.
_SOURCE_SQL = text(
    "\n"
    "WITH wanted_fx AS MATERIALIZED (\n"
    " SELECT DISTINCT unnest(CAST(:fx_ids AS uuid[])) AS id\n"
    "), wanted_evidence AS MATERIALIZED (\n"
    " SELECT DISTINCT unnest(CAST(:evidence_ids AS uuid[])) AS id\n"
    ")\n"
    "SELECT 'fx' AS "
    "kind,s.id,s.content_digest,s.provider_id,s.license_version_id,\n"
    " c.id AS current_license_id,\n"
    " least(s.expires_at,s.first_observed_at+make_interval(days=>leas"
    "t(l.retention_days,c.retention_days))) AS deadline,\n"
    " s.first_observed_at AS original_at,l.effective_at AS "
    "pinned_at,c.effective_at AS current_at\n"
    "FROM wanted_fx w JOIN fx_snapshots s ON s.id=w.id AND "
    "s.owner_id=:owner\n"
    "JOIN market_data_providers p ON p.id=s.provider_id AND "
    "p.owner_id=s.owner_id\n"
    "JOIN provider_license_versions l ON l.id=s.license_version_id "
    "AND l.owner_id=s.owner_id AND l.provider_id=s.provider_id\n"
    "JOIN LATERAL (\n"
    " SELECT x.* FROM provider_license_versions x\n"
    " WHERE x.owner_id=s.owner_id AND x.provider_id=s.provider_id AND "
    "x.effective_at<=:at\n"
    " ORDER BY x.effective_at DESC,x.version_number DESC,x.id DESC "
    "LIMIT 1\n"
    ") c ON true\n"
    "WHERE p.configuration_state='configured' AND "
    "l.effective_at<=:at\n"
    " AND l.store_permission='allowed' AND "
    "l.display_permission='allowed'\n"
    " AND c.store_permission='allowed' AND "
    "c.display_permission='allowed'\n"
    " AND (CAST(:copy_use AS text) IS NULL OR (:copy_use='report' AND "
    "l.report_permission='allowed' AND c.report_permission='allowed') "
    "OR (:copy_use='export' AND l.export_permission='allowed' AND "
    "c.export_permission='allowed'))\n"
    " AND l.retention_days IS NOT NULL AND c.retention_days IS NOT "
    "NULL\n"
    " AND "
    "s.expires_at<=s.first_observed_at+make_interval(days=>least(l.re"
    "tention_days,c.retention_days))\n"
    " AND s.expires_at>:at\n"
    " AND NOT EXISTS(SELECT 1 FROM source_expiry_events e WHERE "
    "e.owner_id=s.owner_id AND e.fx_snapshot_id=s.id)\n"
    " AND NOT EXISTS(SELECT 1 FROM source_retention_work e WHERE "
    "e.owner_id=s.owner_id AND e.fx_snapshot_id=s.id)\n"
    " AND NOT "
    "acquisition_source_restricted(s.owner_id,'fx',s.id,:at,'store')\n"
    " AND NOT "
    "acquisition_source_restricted(s.owner_id,'fx',s.id,:at,'display'"
    ")\n"
    " AND (CAST(:copy_use AS text) IS NULL OR NOT "
    "acquisition_source_restricted(s.owner_id,'fx',s.id,:at,:copy_use"
    "))\n"
    "UNION ALL\n"
    "SELECT "
    "'coverage_parent',h.id,h.content_digest,NULL::uuid,NULL::uuid,NU"
    "LL::uuid,\n"
    " NULL::timestamptz,h.first_observed_at,NULL::timestamptz,NULL::t"
    "imestamptz\n"
    "FROM wanted_evidence w JOIN historical_evidence_sets h ON "
    "h.id=w.id AND h.owner_id=:owner\n"
    "WHERE h.broker_account_id=ANY(CAST(:accounts AS uuid[])) AND "
    "h.sealed\n"
    " AND octet_length(h.canonical_evidence)>0 AND "
    "h.first_observed_at<=:cutoff\n"
    "ORDER BY kind,id\n"
)


@dataclass(frozen=True, slots=True)
class AggregateSourceAuthority:
    fx_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    source_cutoff_at: datetime
    fingerprint: str
    deadline: datetime | None
    required_copy_use: SourceUse | None = None

    def finish(
        self,
        session: Session,
        auth: AggregateAuthorization,
        *,
        now: datetime,
        expires_at: datetime | None = None,
    ) -> None:
        current = authorize_aggregate_sources(
            session,
            auth,
            fx_ids=self.fx_ids,
            evidence_ids=self.evidence_ids,
            cutoff=self.source_cutoff_at,
            now=now,
            required_copy_use=self.required_copy_use,
        )
        if (
            current.fingerprint != self.fingerprint
            or current.deadline != self.deadline
            or (
                expires_at is not None
                and (
                    expires_at <= now
                    or (current.deadline is not None and expires_at > current.deadline)
                )
            )
        ):
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)


def authorize_aggregate_sources(
    session: Session,
    auth: AggregateAuthorization,
    *,
    fx_ids: tuple[UUID, ...],
    evidence_ids: tuple[UUID, ...],
    cutoff: datetime,
    now: datetime,
    required_copy_use: SourceUse | None = None,
) -> AggregateSourceAuthority:
    require_utc(now)
    if required_copy_use is not None and required_copy_use not in (
        SourceUse.REPORT,
        SourceUse.EXPORT,
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    require_utc(cutoff)
    if (
        len(fx_ids) > 256
        or len(evidence_ids) > 10000
        or len(set(fx_ids)) != len(fx_ids)
        or len(set(evidence_ids)) != len(evidence_ids)
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    rows = session.execute(
        _SOURCE_SQL,
        {
            "owner": auth.owner_id,
            "at": now,
            "cutoff": cutoff,
            "fx_ids": list(fx_ids),
            "evidence_ids": list(evidence_ids),
            "accounts": list(auth.account_ids),
            "copy_use": None if required_copy_use is None else required_copy_use.value,
        },
    ).all()
    if {(row[0], row[1]) for row in rows} != {
        *(("fx", x) for x in fx_ids),
        *(("coverage_parent", x) for x in evidence_ids),
    } or len(rows) != len(fx_ids) + len(evidence_ids):
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    dates = tuple(row[6] for row in rows if row[6] is not None)
    return AggregateSourceAuthority(
        tuple(sorted(fx_ids)),
        tuple(sorted(evidence_ids)),
        cutoff,
        sha256(canonical_json(tuple(tuple(row) for row in rows)).encode()).hexdigest(),
        min(dates) if dates else None,
        required_copy_use,
    )
