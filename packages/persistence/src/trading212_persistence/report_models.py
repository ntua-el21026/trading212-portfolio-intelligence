"""Owner-scoped report capture, private artifacts and bounded durable delivery.

Canonical payload columns are deferred: metadata queries cannot accidentally read
licensed document or artifact bytes before their current authorization checks.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import UTCDateTime

REPORT_STATES = "'queued','running','succeeded','failed','expired','cancelled'"
REPORT_TYPES = (
    "'monthly','quarterly','annual','portfolio_summary','target_drift',"
    "'contribution_plan','performance_benchmark','dividend_income',"
    "'portfolio_xray','quality_reconciliation'"
)
REPORT_SCOPES = (
    "'portfolio:read','activity:read','analytics:read','portfolio:refresh',"
    "'configuration:read','targets:read','targets:write','plans:write',"
    "'reports:read','reports:write'"
)
ALL_DELEGATION_SCOPES = (
    REPORT_SCOPES + ",'alerts:read','alerts:write','risk:write','scenarios:write',"
    "'projections:write','goals:write','research:read','research:write',"
    "'preferences:read','preferences:write','aggregate:read','aggregate:write'"
)

REPORT_FAILURES = (
    "'invalid_input','input_unavailable','input_changed','access_denied',"
    "'source_restricted','limit_exceeded','render_failed','storage_unavailable',"
    "'publication_unavailable','lease_expired','attempts_exhausted'"
)


class PrincipalScopeGrantModel(Base):
    __tablename__ = "principal_scope_grants"
    __table_args__ = (
        CheckConstraint(f"scope IN ({ALL_DELEGATION_SCOPES})", name="scope_allowed"),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="expiry_order"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="revoke_order"),
    )
    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("principals.id", ondelete="RESTRICT"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReportOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


def _owned(table: str) -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id")


def _parent(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{target}.owner_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


class ReportDefinitionModel(ReportOwned):
    __tablename__ = "report_definitions"
    __table_args__ = (
        _owned("report_definitions"),
        UniqueConstraint("owner_id", "content_digest", name="uq_report_definitions_digest"),
        CheckConstraint(f"report_type IN ({REPORT_TYPES})", name="type_allowed"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("cardinality(sections) BETWEEN 1 AND 14", name="section_bound"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    report_type: Mapped[str] = mapped_column(String(40))
    period_rule: Mapped[str] = mapped_column(String(30))
    sections: Mapped[list[str]] = mapped_column(ARRAY(String(30)))
    template_version: Mapped[str] = mapped_column(String(40))
    reporting_currency: Mapped[str] = mapped_column(String(3))
    revision: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(64))


class ReportInputSnapshotModel(ReportOwned):
    __tablename__ = "report_input_snapshots"
    __table_args__ = (
        _owned("report_input_snapshots"),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_report_inputs_account_id"),
        CheckConstraint("kind IN ('report','export')", name="kind_allowed"),
        CheckConstraint(
            "contract_version IN (1,2) AND (kind='report' OR contract_version=1)",
            name="contract_version_allowed",
        ),
        UniqueConstraint(
            "owner_id", "account_id", "id", "contract_version", name="uq_report_inputs_contract"
        ),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("document_digest ~ '^[0-9a-f]{64}$'", name="document_digest_format"),
        CheckConstraint("canonical_byte_length BETWEEN 0 AND 33554432", name="byte_bound"),
        CheckConstraint("chunk_count BETWEEN 0 AND 100000", name="chunk_bound"),
        CheckConstraint("pin_count BETWEEN 1 AND 256", name="pin_bound"),
        CheckConstraint("source_count BETWEEN 0 AND 100000", name="source_bound"),
        CheckConstraint(
            "end_date >= start_date AND end_date-start_date <= 3660", name="period_bound"
        ),
        CheckConstraint("expires_at > created_at", name="expiry_order"),
        CheckConstraint("octet_length(canonical_manifest) <= 2097152", name="manifest_bound"),
        CheckConstraint("octet_length(canonical_context) <= 2097152", name="context_bound"),
        CheckConstraint(
            (
                "(purged_at IS NULL) = (canonical_manifest IS NOT NULL AND canonical_co"
                "ntext IS NOT NULL)"
            ),
            name="payload_state",
        ),
        Index("ix_report_inputs_owner_expiry", "owner_id", "expires_at", "id"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(10))
    contract_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    input_digest: Mapped[str] = mapped_column(String(64))
    document_digest: Mapped[str] = mapped_column(String(64))
    canonical_byte_length: Mapped[int] = mapped_column(BigInteger)
    chunk_count: Mapped[int] = mapped_column(Integer)
    pin_count: Mapped[int] = mapped_column(Integer)
    source_count: Mapped[int] = mapped_column(Integer)
    canonical_manifest: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    canonical_context: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    sealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReportInputChunkModel(ReportOwned):
    __tablename__ = "report_input_chunks"
    __table_args__ = (
        _owned("report_input_chunks"),
        _parent("report_input_chunks", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", "table_key", "ordinal", name="uq_report_chunks_table_ordinal"),
        CheckConstraint("ordinal >= 0 AND row_count BETWEEN 0 AND 100000", name="row_bound"),
        CheckConstraint("byte_length BETWEEN 1 AND 1048576", name="byte_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        Index("ix_report_chunks_input_id", "owner_id", "input_id", "id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    table_key: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    byte_length: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReportInputPinModel(ReportOwned):
    __tablename__ = "report_input_pins"
    __table_args__ = (
        _owned("report_input_pins"),
        _parent("report_input_pins", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", "kind", "subject_id", name="uq_report_pins_subject"),
        CheckConstraint("ordinal BETWEEN 0 AND 255", name="ordinal_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_report_pins_input", "owner_id", "input_id", "ordinal"),
    )
    input_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[UUID] = mapped_column()
    parent_id: Mapped[UUID | None] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


class ReportInputDependencyModel(ReportOwned):
    __tablename__ = "report_input_dependencies"
    __table_args__ = (
        _owned("report_input_dependencies"),
        _parent("report_input_dependencies", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", "source_key", name="uq_report_dependencies_source"),
        _parent("report_input_dependencies", "license_version_id", "provider_license_versions"),
        _parent("report_input_dependencies", "provider_id", "market_data_providers"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_report_dependencies_provider_license",
            ondelete="RESTRICT",
        ),
        _parent("report_input_dependencies", "price_snapshot_id", "price_snapshots"),
        _parent("report_input_dependencies", "fx_snapshot_id", "fx_snapshots"),
        _parent("report_input_dependencies", "benchmark_snapshot_id", "benchmark_snapshots"),
        _parent(
            "report_input_dependencies",
            "corporate_action_snapshot_id",
            "corporate_action_snapshots",
        ),
        _parent(
            "report_input_dependencies", "classification_snapshot_id", "classification_snapshots"
        ),
        _parent("report_input_dependencies", "constituent_snapshot_id", "constituent_snapshots"),
        _parent(
            "report_input_dependencies", "entity_evidence_version_id", "entity_evidence_versions"
        ),
        _parent("report_input_dependencies", "fund_definition_id", "fund_definitions"),
        _parent("report_input_dependencies", "fund_mapping_id", "fund_source_mappings"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "num_nonnulls(price_snapshot_id,fx_snapshot_id,benchmark_snapshot_id,"
            "corporate_action_snapshot_id,classification_snapshot_id,constituent_snapshot_id,"
            "entity_evidence_version_id,fund_definition_id,fund_mapping_id) = 1",
            name="physical_parent_xor",
        ),
        CheckConstraint(
            "COALESCE((kind='price' AND source_id=price_snapshot_id) OR "
            "(kind='fx' AND source_id=fx_snapshot_id) OR "
            "(kind='benchmark' AND source_id=benchmark_snapshot_id) OR "
            "(kind='corporate_action' AND source_id=corporate_action_snapshot_id) OR "
            "(kind='classification' AND source_id=classification_snapshot_id) OR "
            "(kind='constituent' AND source_id=constituent_snapshot_id) OR "
            "(kind='entity_evidence' AND source_id=entity_evidence_version_id) OR "
            "(kind='fund_definition' AND source_id=fund_definition_id) OR "
            "(kind='fund_mapping' AND source_id=fund_mapping_id),false)",
            name="source_kind",
        ),
        Index("ix_report_dependencies_input", "owner_id", "input_id", "id"),
        Index("ix_report_dependencies_license", "owner_id", "license_version_id", "input_id"),
        Index("ix_report_dependencies_source", "owner_id", "kind", "source_id", "input_id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    source_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[UUID] = mapped_column()
    parent_id: Mapped[UUID | None] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    price_snapshot_id: Mapped[UUID | None] = mapped_column()
    fx_snapshot_id: Mapped[UUID | None] = mapped_column()
    benchmark_snapshot_id: Mapped[UUID | None] = mapped_column()
    corporate_action_snapshot_id: Mapped[UUID | None] = mapped_column()
    classification_snapshot_id: Mapped[UUID | None] = mapped_column()
    constituent_snapshot_id: Mapped[UUID | None] = mapped_column()
    entity_evidence_version_id: Mapped[UUID | None] = mapped_column()
    fund_definition_id: Mapped[UUID | None] = mapped_column()
    fund_mapping_id: Mapped[UUID | None] = mapped_column()


class ReportInputPremiumDependencyModel(ReportOwned):
    """Immutable normalized lineage from a premium report to its retained run."""

    __tablename__ = "report_input_premium_dependencies"
    __table_args__ = (
        _owned("report_input_premium_dependencies"),
        UniqueConstraint("input_id", name="uq_report_premium_input"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "input_id"],
            [
                "report_input_snapshots.owner_id",
                "report_input_snapshots.account_id",
                "report_input_snapshots.id",
            ],
            ondelete="RESTRICT",
            name="fk_report_premium_input",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            ondelete="RESTRICT",
            name="fk_report_premium_run",
        ),
        CheckConstraint("kind='risk'", name="kind_allowed"),
        CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$' AND result_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        Index("ix_report_premium_run", "owner_id", "run_id", "input_id"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    input_id: Mapped[UUID] = mapped_column()
    run_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    input_digest: Mapped[str] = mapped_column(String(64))
    result_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ReportInputLicenseModel(ReportOwned):
    __tablename__ = "report_input_licenses"
    __table_args__ = (
        _owned("report_input_licenses"),
        _parent("report_input_licenses", "input_id", "report_input_snapshots"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_report_input_licenses_provider_license",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("input_id", "license_version_id", name="uq_report_input_license"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_report_licenses_input", "owner_id", "input_id", "id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


class ReportJobBase(ReportOwned):
    __abstract__ = True
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    principal_id: Mapped[UUID] = mapped_column()
    input_id: Mapped[UUID] = mapped_column()
    command_digest: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    authorization_policy: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(20))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str | None] = mapped_column(String(40))
    consumer_attempts: Mapped[int] = mapped_column(Integer)
    fence: Mapped[int] = mapped_column(BigInteger)
    lease_id: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consumer_id: Mapped[str | None] = mapped_column(String(120))
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    manifest_digest: Mapped[str | None] = mapped_column(String(64))


def _job_constraints(
    table: str,
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        UniqueConstraint("owner_id", "account_id", "id", name=f"uq_{table}_account_id"),
        UniqueConstraint("input_id", name=f"uq_{table}_input"),
        _parent(table, "principal_id", "principals"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "input_id"],
            [
                "report_input_snapshots.owner_id",
                "report_input_snapshots.account_id",
                "report_input_snapshots.id",
            ],
            name=f"fk_{table}_input_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"state IN ({REPORT_STATES})", name="state_allowed"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({REPORT_FAILURES})", name="failure_allowed"
        ),
        CheckConstraint("consumer_attempts BETWEEN 0 AND 4 AND fence >= 0", name="attempt_bound"),
        CheckConstraint(
            "expires_at > requested_at AND expires_at <= requested_at + interval '30 days'",
            name="expiry_bound",
        ),
        CheckConstraint(
            "command_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint("authorization_policy='report_delegation_v1'", name="policy_allowed"),
        CheckConstraint(
            (
                "(state='running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT "
                "NULL AND consumer_id IS NOT NULL)"
            ),
            name="lease_state",
        ),
        CheckConstraint(
            (
                "state<>'succeeded' OR (completed_at IS NOT NULL AND manifest_digest IS"
                " NOT NULL AND failure_code IS NULL)"
            ),
            name="success_state",
        ),
        Index(f"ix_{table}_owner_account_created", "owner_id", "account_id", "requested_at", "id"),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
        Index(f"ix_{table}_input", "owner_id", "input_id", "id"),
    )


class ReportJobModel(ReportJobBase):
    __tablename__ = "report_jobs"
    __table_args__ = (
        *_job_constraints("report_jobs"),
        CheckConstraint("contract_version IN (1,2)", name="contract_version_allowed"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "input_id", "contract_version"],
            [
                "report_input_snapshots.owner_id",
                "report_input_snapshots.account_id",
                "report_input_snapshots.id",
                "report_input_snapshots.contract_version",
            ],
            name="fk_report_jobs_input_contract",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_report_jobs_contract_created",
            "owner_id",
            "account_id",
            "contract_version",
            "requested_at",
            "id",
        ),
        _parent("report_jobs", "definition_id", "report_definitions"),
        CheckConstraint(f"report_type IN ({REPORT_TYPES})", name="type_allowed"),
        CheckConstraint(
            (
                "cardinality(formats) BETWEEN 1 AND 4 AND formats <@ ARRAY['pdf','csv',"
                "'json','xlsx']::varchar[]"
            ),
            name="format_bound",
        ),
    )
    contract_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    definition_id: Mapped[UUID] = mapped_column()
    report_type: Mapped[str] = mapped_column(String(40))
    formats: Mapped[list[str]] = mapped_column(ARRAY(String(10)))


class ExportJobModel(ReportJobBase):
    __tablename__ = "export_jobs"
    __table_args__ = (
        *_job_constraints("export_jobs"),
        CheckConstraint(
            (
                "dataset IN ('positions','activity','dividends','targets','plans','perf"
                "ormance','xray','alerts')"
            ),
            name="dataset_allowed",
        ),
        CheckConstraint("field_set IN ('standard','audit')", name="field_set_allowed"),
        CheckConstraint("format IN ('csv','json','xlsx')", name="format_allowed"),
    )
    dataset: Mapped[str] = mapped_column(String(30))
    field_set: Mapped[str] = mapped_column(String(10))
    format: Mapped[str] = mapped_column(String(10))


class ApplicationCommandIdentityModel(ReportOwned):
    __tablename__ = "application_command_identities"
    __table_args__ = (
        _owned("application_command_identities"),
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_application_command_scoped_identity"
        ),
        ForeignKeyConstraint(
            ["owner_id", "premium_actor_id"],
            ["principals.owner_id", "principals.id"],
            ondelete="RESTRICT",
            name="fk_application_command_premium_actor",
        ),
        UniqueConstraint(
            "owner_id", "command", "idempotency_key", name="uq_application_command_owner_key"
        ),
        _parent("application_command_identities", "report_job_id", "report_jobs"),
        _parent("application_command_identities", "export_job_id", "export_jobs"),
        CheckConstraint(
            "command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1',"
            "'risk.definition.create.v1',"
            "'risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.d"
            "efinition.create.v1','scenario.version.create.v1','scenario.run.create.v1','sc"
            "enario.run.cancel.v1')",
            name="command_allowed",
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,180}$'", name="key_format"),
        CheckConstraint("command_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "(command IN ('reports.generate.v1','reports.generate.v2') AND "
            "report_job_id IS NOT NULL AND "
            "export_job_id IS NULL AND premium_resource_id IS NULL AND premium"
            "_actor_id IS NULL AND premium_correlation_id IS NULL) OR "
            "(command='exports.generate.v1' AND export_job_id IS NOT NULL AND "
            "report_job_id IS NULL AND premium_resource_id IS NULL AND premium"
            "_actor_id IS NULL AND premium_correlation_id IS NULL) OR "
            "(command IN ('risk.definition.create.v1','risk.version.create.v1'"
            ",'risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','sc"
            "enario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1') A"
            "ND report_job_id IS "
            "NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NUL"
            "L AND premium_actor_id IS NOT NULL AND premium_correlation_id IS "
            "NOT NULL)",
            name="parent_kind",
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    command: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    command_digest: Mapped[str] = mapped_column(String(64))
    report_job_id: Mapped[UUID | None] = mapped_column()
    export_job_id: Mapped[UUID | None] = mapped_column()
    premium_resource_id: Mapped[UUID | None] = mapped_column()
    premium_actor_id: Mapped[UUID | None] = mapped_column()
    premium_correlation_id: Mapped[str | None] = mapped_column(String(120))


class ReportManifestBase(ReportOwned):
    __abstract__ = True
    job_id: Mapped[UUID] = mapped_column()
    input_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    publication_fence: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


def _manifest_constraints(
    table: str, jobs: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        _parent(table, "input_id", "report_input_snapshots"),
        UniqueConstraint("job_id", name=f"uq_{table}_job"),
        CheckConstraint("byte_length BETWEEN 1 AND 2097152", name="byte_bound"),
        CheckConstraint("publication_fence > 0", name="fence_positive"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
    )


class ReportManifestModel(ReportManifestBase):
    __tablename__ = "report_manifests"
    __table_args__ = _manifest_constraints("report_manifests", "report_jobs")


class ExportManifestModel(ReportManifestBase):
    __tablename__ = "export_manifests"
    __table_args__ = _manifest_constraints("export_manifests", "export_jobs")


class ReportArtifactBase(ReportOwned):
    __abstract__ = True
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    job_id: Mapped[UUID] = mapped_column()
    manifest_id: Mapped[UUID] = mapped_column()
    format: Mapped[str] = mapped_column(String(10))
    mime_type: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(160))
    content_digest: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    publication_fence: Mapped[int] = mapped_column(BigInteger)
    contents: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


def _artifact_constraints(
    table: str, jobs: str, manifests: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        _parent(table, "manifest_id", manifests),
        UniqueConstraint("job_id", "format", name=f"uq_{table}_job_format"),
        CheckConstraint("format IN ('pdf','csv','json','xlsx')", name="format_allowed"),
        CheckConstraint("byte_length BETWEEN 1 AND 10485760", name="byte_bound"),
        CheckConstraint("publication_fence > 0", name="fence_positive"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "contents IS NULL OR octet_length(contents)=byte_length", name="content_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (contents IS NOT NULL)", name="payload_state"),
        CheckConstraint("expires_at > created_at", name="expiry_order"),
        CheckConstraint("filename ~ '^[A-Za-z0-9._-]{1,160}$'", name="filename_safe"),
        Index(f"ix_{table}_expiry", "owner_id", "expires_at", "id"),
    )


class ReportArtifactModel(ReportArtifactBase):
    __tablename__ = "report_artifacts"
    __table_args__ = _artifact_constraints("report_artifacts", "report_jobs", "report_manifests")


class ExportArtifactModel(ReportArtifactBase):
    __tablename__ = "export_artifacts"
    __table_args__ = _artifact_constraints("export_artifacts", "export_jobs", "export_manifests")


class ArtifactDownloadGrantModel(ReportOwned):
    __tablename__ = "artifact_download_grants"
    __table_args__ = (
        _owned("artifact_download_grants"),
        _parent("artifact_download_grants", "report_artifact_id", "report_artifacts"),
        _parent("artifact_download_grants", "export_artifact_id", "export_artifacts"),
        CheckConstraint(
            "num_nonnulls(report_artifact_id,export_artifact_id)=1", name="artifact_xor"
        ),
        CheckConstraint("token_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "expires_at > issued_at AND expires_at <= issued_at + interval '5 minutes'",
            name="expiry_bound",
        ),
        UniqueConstraint("token_digest", name="uq_artifact_grants_digest"),
        Index("ix_artifact_grants_report", "owner_id", "report_artifact_id", "expires_at", "id"),
        Index("ix_artifact_grants_export", "owner_id", "export_artifact_id", "expires_at", "id"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    report_artifact_id: Mapped[UUID | None] = mapped_column()
    export_artifact_id: Mapped[UUID | None] = mapped_column()
    token_digest: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReportDispatchBase(ReportOwned):
    __abstract__ = True
    job_id: Mapped[UUID] = mapped_column()
    task_name: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    publication_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    claim_token: Mapped[UUID | None] = mapped_column()
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dispatcher_id: Mapped[str | None] = mapped_column(String(120))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


def _dispatch_constraints(
    table: str, jobs: str, task: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        UniqueConstraint("job_id", "task_name", "schema_version", name=f"uq_{table}_job_task"),
        CheckConstraint(f"task_name='{task}' AND schema_version='1.0.0'", name="task_fixed"),
        CheckConstraint(
            "state IN ('pending','claimed','published','dead_letter')", name="state_allowed"
        ),
        CheckConstraint("publication_attempts BETWEEN 0 AND 8", name="attempt_bound"),
        CheckConstraint(
            (
                "(state='claimed') = (claim_token IS NOT NULL AND claim_expires_at IS N"
                "OT NULL AND dispatcher_id IS NOT NULL)"
            ),
            name="claim_state",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({REPORT_FAILURES})", name="failure_allowed"
        ),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
    )


class ReportDispatchOutboxModel(ReportDispatchBase):
    __tablename__ = "report_dispatch_outbox"
    __table_args__ = _dispatch_constraints(
        "report_dispatch_outbox", "report_jobs", "reports.generate.v1"
    )


class ExportDispatchOutboxModel(ReportDispatchBase):
    __tablename__ = "export_dispatch_outbox"
    __table_args__ = _dispatch_constraints(
        "export_dispatch_outbox", "export_jobs", "exports.generate.v1"
    )


class ReportAttemptModel(ReportOwned):
    __tablename__ = "report_job_attempts"
    __table_args__ = (
        _owned("report_job_attempts"),
        _parent("report_job_attempts", "report_job_id", "report_jobs"),
        _parent("report_job_attempts", "export_job_id", "export_jobs"),
        CheckConstraint("num_nonnulls(report_job_id,export_job_id)=1", name="job_xor"),
        CheckConstraint("phase IN ('dispatch','consumer')", name="phase_allowed"),
        CheckConstraint("attempt BETWEEN 1 AND 8 AND fence >= 0", name="attempt_bound"),
        CheckConstraint(
            "outcome IN ('claimed','published','succeeded','retry','failed','expired')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({REPORT_FAILURES})", name="failure_allowed"
        ),
        Index("ix_report_attempts_report", "owner_id", "report_job_id", "created_at"),
        Index("ix_report_attempts_export", "owner_id", "export_job_id", "created_at"),
    )
    report_job_id: Mapped[UUID | None] = mapped_column()
    export_job_id: Mapped[UUID | None] = mapped_column()
    phase: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer)
    fence: Mapped[int] = mapped_column(BigInteger)
    outcome: Mapped[str] = mapped_column(String(20))
    failure_code: Mapped[str | None] = mapped_column(String(40))


class ReportRetentionWorkModel(ReportOwned):
    __tablename__ = "report_retention_work"
    __table_args__ = (
        _owned("report_retention_work"),
        _parent("report_retention_work", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", name="uq_report_retention_input"),
        CheckConstraint("reason IN ('ttl','source','owner')", name="reason_allowed"),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="time_order"),
        Index("ix_report_retention_pending", "owner_id", "completed_at", "input_id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    reason: Mapped[str] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


REPORT_MODELS = (
    PrincipalScopeGrantModel,
    ReportDefinitionModel,
    ReportInputSnapshotModel,
    ReportInputChunkModel,
    ReportInputPinModel,
    ReportInputDependencyModel,
    ReportInputLicenseModel,
    ReportJobModel,
    ExportJobModel,
    ApplicationCommandIdentityModel,
    ReportManifestModel,
    ExportManifestModel,
    ReportArtifactModel,
    ExportArtifactModel,
    ArtifactDownloadGrantModel,
    ReportDispatchOutboxModel,
    ExportDispatchOutboxModel,
    ReportAttemptModel,
    ReportRetentionWorkModel,
)
