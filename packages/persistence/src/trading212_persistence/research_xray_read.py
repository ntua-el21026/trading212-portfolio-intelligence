"""Three-statement retained X-ray read for already-authorized research transactions.

The caller owns current principal/account/scope checks and the sources -> xray
owner locks. It must call finish_research_xray and recheck its principal before
publication. These functions never select a latest run or recalculate finance.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.errors import DomainError
from trading212_domain.research_facts import ResearchXrayPin
from trading212_domain.xray import XrayReferenceKind, XraySourceDependency
from trading212_domain.xray_codec import (
    decode_xray_component,
    decode_xray_input,
    decode_xray_policy,
    decode_xray_result,
)
from trading212_domain.xray_result import XrayCalculation, XrayPortfolioSummary

from .report_authorization import ReportAuthorization
from .research_source_store import research_error

_MAX_ROWS = 100_000
_MAX_BYTES = 33_554_432
# Literal table/column inventory, matching XrayRunStore's closed physical targets.
_LICENSED = (
    ("fx_snapshot_id", "fx_snapshots", "source"),
    ("entity_evidence_version_id", "entity_evidence_versions", "enrichment"),
    ("classification_snapshot_id", "classification_snapshots", "enrichment"),
    ("fund_definition_id", "fund_definitions", "enrichment"),
    ("fund_mapping_id", "fund_source_mappings", "enrichment"),
    ("constituent_snapshot_id", "constituent_snapshots", "source"),
)
_INTERNAL = (
    ("valuation_run_id", "calculation_runs", "broker_account_id", False),
    ("reconciliation_run_id", "reconciliation_runs", "broker_account_id", False),
    ("broker_source_record_id", "source_records", "broker_account_id", False),
    ("threshold_policy_id", "xray_policy_versions", "account_id", True),
)
_DIRECT = {
    XrayReferenceKind.CALCULATION_RUN: "valuation_run_id",
    XrayReferenceKind.BROKER_SOURCE_RECORD: "broker_source_record_id",
    XrayReferenceKind.RECONCILIATION_RUN: "reconciliation_run_id",
    XrayReferenceKind.OWNER_POLICY: "threshold_policy_id",
    XrayReferenceKind.FX_SNAPSHOT: "fx_snapshot_id",
    XrayReferenceKind.FUND_DEFINITION: "fund_definition_id",
    XrayReferenceKind.FUND_MAPPING: "fund_mapping_id",
    XrayReferenceKind.CONSTITUENT_SNAPSHOT: "constituent_snapshot_id",
    XrayReferenceKind.CLASSIFICATION_SNAPSHOT: "classification_snapshot_id",
    XrayReferenceKind.ENTITY_EVIDENCE_VERSION: "entity_evidence_version_id",
}
_CHILDREN = (
    (
        XrayReferenceKind.SNAPSHOT_POSITION,
        "snapshot_positions",
        "snapshot_id",
        "valuation_run_id",
        False,
    ),
    (XrayReferenceKind.SNAPSHOT_CASH, "snapshot_cash", "snapshot_id", "valuation_run_id", False),
    (XrayReferenceKind.FX_OBSERVATION, "fx_observations", "snapshot_id", "fx_snapshot_id", True),
    (
        XrayReferenceKind.FX_COVERAGE_GAP,
        "source_coverage_gaps",
        "fx_snapshot_id",
        "fx_snapshot_id",
        True,
    ),
    (
        XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE,
        "entity_evidence_references",
        "evidence_version_id",
        "entity_evidence_version_id",
        True,
    ),
    (
        XrayReferenceKind.RELATIONSHIP,
        "instrument_entity_relationships",
        "evidence_version_id",
        "entity_evidence_version_id",
        True,
    ),
    (
        XrayReferenceKind.CLASSIFICATION_ASSIGNMENT,
        "classification_assignments",
        "snapshot_id",
        "classification_snapshot_id",
        True,
    ),
    (
        XrayReferenceKind.CONSTITUENT_HOLDING,
        "constituent_holdings",
        "snapshot_id",
        "constituent_snapshot_id",
        True,
    ),
)


@dataclass(frozen=True, slots=True)
class _Dependency:
    id: UUID
    reference_id: UUID
    target: str
    target_id: UUID
    provider_id: str | None
    license_id: UUID | None
    content_digest: str | None
    payload_bytes: int
    fingerprint: str
    deadline: datetime | None


@dataclass(frozen=True, slots=True)
class _Metadata:
    run_id: UUID
    input_id: UUID
    analytics_id: UUID
    owner_id: UUID
    account_id: UUID
    snapshot_id: UUID
    valuation_run_id: UUID
    policy_id: UUID
    input_digest: str
    result_digest: str
    policy_digest: str
    currency: str
    valuation_at: datetime
    cutoff_at: datetime
    method_version: str
    input_bytes: int
    result_bytes: int
    policy_bytes: int
    summary_bytes: int
    fingerprint: str
    dependencies: tuple[_Dependency, ...]
    deadline: datetime | None


@dataclass(frozen=True, slots=True)
class ResearchXrayRead:
    """Private transaction-local basis; it is not permission to publish by itself."""

    pin: ResearchXrayPin
    result: XrayCalculation
    input_id: UUID
    deadline: datetime | None
    _metadata: _Metadata
    _physical: str


def _parents_sql() -> str:
    parts = []
    for field, table, lifecycle in _LICENSED:
        parts.append(f"""
          SELECT d.id dependency_id, '{field}' target, p.id parent_id,
                 p.provider_id, p.license_version_id, p.content_digest,
                 p.created_at, p.expires_at,
                 NOT EXISTS (SELECT 1 FROM {lifecycle}_expiry_events e
                     WHERE e.owner_id = :owner AND e.{field} = p.id)
                 AND NOT EXISTS (SELECT 1 FROM {lifecycle}_retention_work w
                     WHERE w.owner_id = :owner AND w.{field} = p.id) marker_clear
          FROM deps d JOIN {table} p ON p.id = d.{field} AND p.owner_id = :owner
        """)  # noqa: S608 - fixed registry identifiers; all external values are bound.
    for field, table, account, owned in _INTERNAL:
        owner = "AND p.owner_id = :owner" if owned else ""
        parts.append(f"""
          SELECT d.id dependency_id, '{field}' target, p.id parent_id,
                 NULL::uuid provider_id, NULL::uuid license_version_id,
                 NULL::text content_digest, p.created_at, NULL::timestamptz expires_at,
                 true marker_clear
          FROM deps d JOIN {table} p ON p.id = d.{field}
              AND p.{account} = :account {owner}
        """)  # noqa: S608 - fixed registry identifiers; all external values are bound.
    return " UNION ALL ".join(parts)


def _physical_sql() -> str:
    conditions = [
        f"WHEN '{kind.value}' THEN d.{field} = e.record_id" for kind, field in _DIRECT.items()
    ]
    conditions.append("""WHEN 'portfolio_snapshot' THEN
        e.record_id = r.snapshot_id AND d.valuation_run_id = r.valuation_run_id""")
    for kind, table, parent_column, target, owned in _CHILDREN:
        parent = "r.snapshot_id" if target == "valuation_run_id" else f"d.{target}"
        valuation = (
            "AND d.valuation_run_id = r.valuation_run_id" if target == "valuation_run_id" else ""
        )
        owner = "AND c.owner_id = :owner" if owned else ""
        conditions.append(f"""WHEN '{kind.value}' THEN
            e.parent_record_id = {parent} {valuation}
            AND EXISTS (SELECT 1 FROM {table} c WHERE c.id = e.record_id
                AND c.{parent_column} = {parent} {owner})""")  # noqa: S608 - fixed registry identifiers; all external values are bound.
    return "CASE e.kind " + " ".join(conditions) + " ELSE false END"


def _metadata_sql() -> str:
    targets = [field for field, _, _ in _LICENSED] + [item[0] for item in _INTERNAL]
    columns = ", ".join(f"d.{field}" for field in targets)
    # No canonical payload is returned or decoded by this query. The preliminary
    # count/byte gate precedes parent expansion; the complete metadata gate also
    # prevents a large result set from reaching the Python process.
    return f"""
    WITH root AS MATERIALIZED (
      SELECT r.id run_id, i.id input_id, a.id analytics_id, i.owner_id, i.account_id,
        i.snapshot_id, i.valuation_run_id, i.policy_id, i.input_digest,
        r.content_digest result_digest, p.content_digest policy_digest,
        i.reporting_currency currency, i.valuation_at, i.source_cutoff_at cutoff_at,
        a.method_version, r.sealed_at run_sealed, i.sealed_at input_sealed,
        octet_length(i.canonical_input) input_bytes,
        octet_length(a.canonical_result) result_bytes,
        octet_length(p.canonical_policy) policy_bytes,
        octet_length(r.canonical_summary) summary_bytes,
        (a.kind = 'xray' AND a.input_digest = i.input_digest
          AND a.content_digest = r.content_digest
          AND a.reporting_currency = i.reporting_currency
          AND a.valuation_at = i.valuation_at AND a.source_cutoff_at = i.source_cutoff_at
          AND octet_length(a.canonical_input) = octet_length(i.canonical_input)
          AND s.calculation_run_id = i.valuation_run_id
          AND NOT EXISTS (SELECT 1 FROM xray_retention_events x
            WHERE x.owner_id = :owner AND x.input_id = i.id)) valid
      FROM xray_runs r
      JOIN xray_input_snapshots i ON i.id = r.input_id AND i.owner_id = :owner
        AND i.account_id = :account
      JOIN analytics_runs a ON a.id = r.analytics_run_id AND a.owner_id = :owner
        AND a.broker_account_id = :account
      JOIN portfolio_snapshots s ON s.id = i.snapshot_id AND s.broker_account_id = :account
      JOIN calculation_runs v ON v.id = i.valuation_run_id AND v.broker_account_id = :account
      JOIN xray_policy_versions p ON p.id = i.policy_id AND p.owner_id = :owner
        AND p.account_id = :account
      WHERE r.id = :run AND r.owner_id = :owner
      FOR SHARE OF r, i, a, p
    ), limited AS MATERIALIZED (
      SELECT d.id, d.reference_id, d.provider_id, d.license_version_id, {columns},
        octet_length(d.canonical_reference) payload_bytes
      FROM xray_input_dependencies d JOIN root r ON r.input_id = d.input_id
      WHERE d.owner_id = :owner ORDER BY d.id LIMIT 100001
    ), size AS MATERIALIZED (
      SELECT count(*) count, coalesce(sum(payload_bytes), 0) payload_bytes,
        coalesce(bool_and(payload_bytes > 0), true) payloads_present FROM limited
    ), deps AS MATERIALIZED (
      SELECT d.* FROM limited d CROSS JOIN root r CROSS JOIN size s
      WHERE s.count <= 100000 AND s.payload_bytes + r.input_bytes + r.result_bytes
        + r.policy_bytes + r.summary_bytes <= 33554432
    ), parents AS MATERIALIZED ({_parents_sql()}),
    expected AS MATERIALIZED (
      SELECT * FROM jsonb_to_recordset(CAST(:physical AS jsonb))
        AS x(dependency_id uuid, reference_id uuid, kind text,
             record_id uuid, parent_record_id uuid)
    ), details AS MATERIALIZED (
      SELECT d.id, jsonb_build_object(
        'id', d.id, 'reference_id', d.reference_id, 'target', p.target,
        'target_id', p.parent_id, 'provider_id', d.provider_id,
        'license_id', d.license_version_id, 'content_digest', p.content_digest,
        'created_at', p.created_at, 'expires_at', p.expires_at,
        'payload_bytes', d.payload_bytes,
        'pinned_id', lp.id, 'pinned_effective', lp.effective_at,
        'pinned_store', lp.store_permission, 'pinned_display', lp.display_permission,
        'pinned_days', lp.retention_days,
        'current_id', lc.id, 'current_effective', lc.effective_at,
        'current_store', lc.store_permission, 'current_display', lc.display_permission,
        'current_days', lc.retention_days,
        'valid', p.parent_id IS NOT NULL AND num_nonnulls({columns}) = 1
          AND p.marker_clear
          AND d.provider_id IS NOT DISTINCT FROM p.provider_id
          AND d.license_version_id IS NOT DISTINCT FROM p.license_version_id,
        'physical_valid', NOT :finishing OR (e.reference_id = d.reference_id
          AND {_physical_sql()})
      ) metadata
      FROM deps d CROSS JOIN root r
      LEFT JOIN parents p ON p.dependency_id = d.id
      LEFT JOIN provider_license_versions lp ON lp.id = p.license_version_id
        AND lp.owner_id = :owner AND lp.provider_id = p.provider_id
      LEFT JOIN LATERAL (
        SELECT l.id, l.effective_at, l.store_permission, l.display_permission,
          l.retention_days FROM provider_license_versions l
        WHERE l.owner_id = :owner AND l.provider_id = p.provider_id
          AND l.effective_at <= :now
        ORDER BY l.effective_at DESC, l.version_number DESC, l.id DESC LIMIT 1
      ) lc ON true
      LEFT JOIN expected e ON e.dependency_id = d.id
    ), measured AS MATERIALIZED (
      SELECT coalesce(sum(octet_length(metadata::text)), 0) metadata_bytes FROM details
    ), head AS MATERIALIZED (
      SELECT r.run_id, to_jsonb(r) || jsonb_build_object(
        'dependency_count', s.count, 'dependency_bytes', s.payload_bytes,
        'payloads_present', s.payloads_present, 'metadata_bytes', m.metadata_bytes,
        'expected_count', (SELECT count(*) FROM expected)) metadata,
        s.count <= 100000 AND s.payload_bytes + r.input_bytes + r.result_bytes
          + r.policy_bytes + r.summary_bytes + m.metadata_bytes
          + octet_length(to_jsonb(r)::text) + 1024 <= 33554432 admitted
      FROM root r CROSS JOIN size s CROSS JOIN measured m
    )
    SELECT 0 ordinal, h.run_id identifier, h.metadata ||
      jsonb_build_object('admitted', h.admitted) metadata FROM head h
    UNION ALL
    SELECT 1 ordinal, d.id identifier, d.metadata FROM details d CROSS JOIN head h
      WHERE h.admitted
    ORDER BY ordinal, identifier
    """  # noqa: S608 - fixed registry identifiers; all external values are bound.


_METADATA_SQL = _metadata_sql()
_PAYLOAD_SQL = """
WITH owned AS MATERIALIZED (
  SELECT i.id input_id, r.id run_id, a.id analytics_id, p.id policy_id
  FROM xray_runs r JOIN xray_input_snapshots i ON i.id = r.input_id
  JOIN analytics_runs a ON a.id = r.analytics_run_id
  JOIN xray_policy_versions p ON p.id = i.policy_id
  WHERE r.id = :run AND r.owner_id = :owner AND i.id = :input
    AND i.owner_id = :owner AND i.account_id = :account
    AND a.id = :analytics AND a.owner_id = :owner AND a.broker_account_id = :account
    AND p.owner_id = :owner AND p.account_id = :account
    AND a.kind = 'xray' AND i.input_digest = :input_digest
    AND a.input_digest = :input_digest AND r.content_digest = :result_digest
    AND a.content_digest = :result_digest AND a.canonical_input = i.canonical_input
    AND octet_length(i.canonical_input) = :input_bytes
    AND octet_length(a.canonical_result) = :result_bytes
    AND octet_length(p.canonical_policy) = :policy_bytes
    AND octet_length(r.canonical_summary) = :summary_bytes
), blobs AS (
  SELECT 'input' kind, o.input_id id, a.canonical_input payload FROM owned o
    JOIN analytics_runs a ON a.id = o.analytics_id
  UNION ALL
  SELECT 'result', o.run_id, a.canonical_result FROM owned o
    JOIN analytics_runs a ON a.id = o.analytics_id
  UNION ALL
  SELECT 'policy', o.policy_id, p.canonical_policy FROM owned o
    JOIN xray_policy_versions p ON p.id = o.policy_id
  UNION ALL
  SELECT 'summary', o.run_id, r.canonical_summary FROM owned o
    JOIN xray_runs r ON r.id = o.run_id
  UNION ALL
  SELECT 'dependency', d.id, d.canonical_reference FROM owned o
    JOIN xray_input_dependencies d ON d.input_id = o.input_id AND d.owner_id = :owner
)
SELECT kind, id, payload FROM blobs ORDER BY kind, id LIMIT 100005
"""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
    return value


def _at(value: object) -> datetime:
    if not isinstance(value, str):
        raise research_error()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise research_error()
        return parsed.astimezone(UTC)
    except (ValueError, TypeError):
        raise research_error() from None


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise research_error()
    try:
        result = UUID(value)
    except ValueError:
        raise research_error() from None
    if str(result) != value:
        raise research_error()
    return result


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise research_error()
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise research_error()
    return value


def _fingerprint(value: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _deadline(row: Mapping[str, Any], now: datetime) -> datetime | None:
    if row["provider_id"] is None:
        if row["license_id"] is not None:
            raise research_error()
        return None
    if row["pinned_id"] != row["license_id"] or row["current_id"] is None:
        raise research_error()
    for prefix in ("pinned", "current"):
        if (
            row[f"{prefix}_store"] != "allowed"
            or row[f"{prefix}_display"] != "allowed"
            or _at(row[f"{prefix}_effective"]) > now
            or row[f"{prefix}_days"] is None
        ):
            raise research_error()
    days = min(_integer(row["pinned_days"]), _integer(row["current_days"]))
    if not 1 <= days <= 36500:
        raise research_error()
    physical = _at(row["expires_at"])
    original = _at(row["created_at"]) + timedelta(days=days)
    deadline = min(physical, original)
    # Match the existing research original-source validity rule. A newer copy
    # clock cannot cure a parent retained beyond a now-shorter original license.
    if physical > original or now >= deadline:
        raise research_error()
    return deadline


def _metadata(
    session: Session,
    auth: ReportAuthorization,
    run_id: UUID,
    *,
    now: datetime,
    physical: str = "[]",
    finishing: bool = False,
) -> _Metadata:
    rows = session.execute(
        text(_METADATA_SQL),
        {
            "owner": auth.owner_id,
            "account": auth.account_id,
            "run": run_id,
            "now": _utc(now),
            "physical": physical,
            "finishing": finishing,
        },
    ).mappings()
    first = next(rows, None)
    if first is None:
        raise research_error(app.ResearchErrorCode.NOT_FOUND)
    head = first["metadata"]
    if first["ordinal"] != 0 or not isinstance(head, dict):
        raise research_error()
    if head.get("admitted") is not True:
        raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
    if (
        head.get("valid") is not True
        or head.get("payloads_present") is not True
        or head.get("run_sealed") is None
        or head.get("input_sealed") is None
        or any(
            _integer(head[field]) == 0
            for field in ("input_bytes", "result_bytes", "policy_bytes", "summary_bytes")
        )
    ):
        raise research_error()
    count = _integer(head["dependency_count"])
    if count > _MAX_ROWS or (finishing and head["expected_count"] != count):
        raise research_error()
    dependencies = []
    seen: set[UUID] = set()
    for index, row in enumerate(rows):
        if index >= count or row["ordinal"] != 1:
            raise research_error()
        item = row["metadata"]
        if (
            not isinstance(item, dict)
            or item.get("valid") is not True
            or item.get("physical_valid") is not True
        ):
            raise research_error()
        identifier = _uuid(item["reference_id"])
        if identifier in seen:
            raise research_error()
        seen.add(identifier)
        dependencies.append(
            _Dependency(
                id=_uuid(item["id"]),
                reference_id=identifier,
                target=_string(item["target"]),
                target_id=_uuid(item["target_id"]),
                provider_id=None
                if item["provider_id"] is None
                else str(_uuid(item["provider_id"])),
                license_id=None if item["license_id"] is None else _uuid(item["license_id"]),
                content_digest=None
                if item["content_digest"] is None
                else _string(item["content_digest"]),
                payload_bytes=_integer(item["payload_bytes"]),
                fingerprint=_fingerprint(item),
                deadline=_deadline(item, now),
            )
        )
    if (
        len(dependencies) != count
        or sum(item.payload_bytes for item in dependencies) != head["dependency_bytes"]
    ):
        raise research_error()
    deadlines = [item.deadline for item in dependencies if item.deadline is not None]
    stable = {key: value for key, value in head.items() if key != "expected_count"}
    return _Metadata(
        run_id=_uuid(head["run_id"]),
        input_id=_uuid(head["input_id"]),
        analytics_id=_uuid(head["analytics_id"]),
        owner_id=_uuid(head["owner_id"]),
        account_id=_uuid(head["account_id"]),
        snapshot_id=_uuid(head["snapshot_id"]),
        valuation_run_id=_uuid(head["valuation_run_id"]),
        policy_id=_uuid(head["policy_id"]),
        input_digest=_string(head["input_digest"]),
        result_digest=_string(head["result_digest"]),
        policy_digest=_string(head["policy_digest"]),
        currency=_string(head["currency"]),
        valuation_at=_at(head["valuation_at"]),
        cutoff_at=_at(head["cutoff_at"]),
        method_version=_string(head["method_version"]),
        input_bytes=_integer(head["input_bytes"]),
        result_bytes=_integer(head["result_bytes"]),
        policy_bytes=_integer(head["policy_bytes"]),
        summary_bytes=_integer(head["summary_bytes"]),
        fingerprint=_fingerprint(stable),
        dependencies=tuple(dependencies),
        deadline=min(deadlines) if deadlines else None,
    )


def _payloads(session: Session, metadata: _Metadata) -> dict[tuple[str, UUID], bytes]:
    expected = {
        ("input", metadata.input_id): metadata.input_bytes,
        ("result", metadata.run_id): metadata.result_bytes,
        ("policy", metadata.policy_id): metadata.policy_bytes,
        ("summary", metadata.run_id): metadata.summary_bytes,
        **{("dependency", item.id): item.payload_bytes for item in metadata.dependencies},
    }
    rows = session.execute(
        text(_PAYLOAD_SQL),
        {
            "owner": metadata.owner_id,
            "account": metadata.account_id,
            "run": metadata.run_id,
            "input": metadata.input_id,
            "analytics": metadata.analytics_id,
            "input_digest": metadata.input_digest,
            "result_digest": metadata.result_digest,
            "input_bytes": metadata.input_bytes,
            "result_bytes": metadata.result_bytes,
            "policy_bytes": metadata.policy_bytes,
            "summary_bytes": metadata.summary_bytes,
        },
    ).mappings()
    result: dict[tuple[str, UUID], bytes] = {}
    total = 0
    for row in rows:
        key = (row["kind"], row["id"])
        payload = row["payload"]
        if (
            key not in expected
            or key in result
            or not isinstance(payload, bytes)
            or len(payload) != expected[key]
        ):
            raise research_error()
        total += len(payload)
        if total > _MAX_BYTES:
            raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
        result[key] = payload
    if result.keys() != expected.keys():
        raise research_error()
    return result


def _reference(
    metadata: _Metadata, row: _Dependency, value: XraySourceDependency
) -> dict[str, str | None]:
    if (
        value.id,
        value.owner_id,
        value.account_id,
        value.snapshot_id,
        value.provider_id,
        value.license_version_id,
    ) != (
        row.reference_id,
        metadata.owner_id,
        metadata.account_id,
        metadata.snapshot_id,
        row.provider_id,
        row.license_id,
    ) or (row.content_digest is not None and value.content_digest != row.content_digest):
        raise research_error()
    physical = value.reference
    kind = physical.kind
    if kind in _DIRECT:
        valid = row.target == _DIRECT[kind] and physical.record_id == row.target_id
    elif kind is XrayReferenceKind.PORTFOLIO_SNAPSHOT:
        valid = (
            physical.record_id == metadata.snapshot_id
            and row.target == "valuation_run_id"
            and row.target_id == metadata.valuation_run_id
        )
    else:
        child = next((item for item in _CHILDREN if item[0] is kind), None)
        parent = metadata.snapshot_id if row.target == "valuation_run_id" else row.target_id
        valid = child is not None and row.target == child[3] and physical.parent_record_id == parent
        if row.target == "valuation_run_id":
            valid = valid and row.target_id == metadata.valuation_run_id
    if not valid:
        raise research_error()
    return {
        "dependency_id": str(row.id),
        "reference_id": str(value.id),
        "kind": kind.value,
        "record_id": str(physical.record_id),
        "parent_record_id": None
        if physical.parent_record_id is None
        else str(physical.parent_record_id),
    }


def read_research_xray(
    session: Session,
    auth: ReportAuthorization,
    run_id: UUID,
    *,
    now: datetime,
) -> ResearchXrayRead:
    """Read one saved run after caller authorization, using exactly two statements."""
    metadata = _metadata(session, auth, run_id, now=now)
    blobs = _payloads(session, metadata)
    encoded_input = blobs[("input", metadata.input_id)]
    encoded_result = blobs[("result", metadata.run_id)]
    policy_bytes = blobs[("policy", metadata.policy_id)]
    if (
        sha256(encoded_input).hexdigest() != metadata.input_digest
        or sha256(encoded_result).hexdigest() != metadata.result_digest
        or sha256(policy_bytes).hexdigest() != metadata.policy_digest
    ):
        raise research_error()
    try:
        value = decode_xray_input(encoded_input)
        result = decode_xray_result(encoded_result)
        policy = decode_xray_policy(policy_bytes)
        summary = decode_xray_component(blobs[("summary", metadata.run_id)], XrayPortfolioSummary)
        references = {}
        physical = []
        for row in metadata.dependencies:
            reference = decode_xray_component(blobs[("dependency", row.id)], XraySourceDependency)
            references[reference.id] = reference
            physical.append(_reference(metadata, row, reference))
        context = (
            metadata.owner_id,
            metadata.account_id,
            metadata.snapshot_id,
            metadata.currency,
            metadata.valuation_at,
            metadata.cutoff_at,
        )
        if (
            (
                value.owner_id,
                value.account_id,
                value.snapshot_id,
                value.reporting_currency.value,
                value.valuation_at.value,
                value.source_cutoff_at.value,
            )
            != context
            or (
                result.owner_id,
                result.account_id,
                result.snapshot_id,
                result.reporting_currency.value,
                result.valuation_at.value,
                result.source_cutoff_at.value,
            )
            != context
            or result.input_digest != metadata.input_digest
            or policy.id != metadata.policy_id
            or value.policy != policy
            or result.policy != policy
            or result.policy.method_version != metadata.method_version
            or result.portfolio_summary != summary
            or {item.id: item for item in value.source_dependencies} != references
            or {item.id: item for item in result.source_dependencies} != references
        ):
            raise research_error()
        pin = ResearchXrayPin(
            owner_id=metadata.owner_id,
            account_id=metadata.account_id,
            run_id=run_id,
            snapshot_id=metadata.snapshot_id,
            input_digest=metadata.input_digest,
            result_digest=metadata.result_digest,
            reporting_currency=result.reporting_currency,
            valuation_at=result.valuation_at.value,
            source_cutoff_at=result.source_cutoff_at.value,
            quality_evaluated_at=result.quality_evaluated_at.value,
            policy_id=policy.id,
            policy_version=policy.version,
        )
    except DomainError:
        raise research_error() from None
    encoded_physical = json.dumps(physical, sort_keys=True, separators=(",", ":"))
    if len(encoded_physical.encode()) > _MAX_BYTES:
        raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
    return ResearchXrayRead(
        pin, result, metadata.input_id, metadata.deadline, metadata, encoded_physical
    )


def finish_research_xray(
    session: Session,
    auth: ReportAuthorization,
    basis: ResearchXrayRead,
    *,
    now: datetime,
) -> None:
    """Recheck exact source rights, lifetimes, retained pins and physical membership.

    This is the third statement. The caller still rechecks its current principal
    and finalized transport size before returning a response (including a 304).
    """
    metadata = basis._metadata
    if (
        (auth.owner_id, auth.account_id) != (basis.pin.owner_id, basis.pin.account_id)
        or (
            basis.pin.run_id,
            basis.input_id,
            basis.pin.snapshot_id,
            basis.pin.input_digest,
            basis.pin.result_digest,
            basis.pin.reporting_currency.value,
            basis.pin.valuation_at,
            basis.pin.source_cutoff_at,
            basis.pin.policy_id,
            basis.pin.method_version,
            basis.deadline,
        )
        != (
            metadata.run_id,
            metadata.input_id,
            metadata.snapshot_id,
            metadata.input_digest,
            metadata.result_digest,
            metadata.currency,
            metadata.valuation_at,
            metadata.cutoff_at,
            metadata.policy_id,
            metadata.method_version,
            metadata.deadline,
        )
        or basis.pin.policy_version != basis.result.policy.version
        or basis.pin.quality_evaluated_at != basis.result.quality_evaluated_at.value
    ):
        raise research_error()
    current = _metadata(
        session, auth, basis.pin.run_id, now=now, physical=basis._physical, finishing=True
    )
    if current != basis._metadata:
        raise research_error()
