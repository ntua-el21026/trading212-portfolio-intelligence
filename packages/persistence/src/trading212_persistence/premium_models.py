"""Shared bounded premium run authority and the existing fixed-task outbox pattern."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import UTCDateTime


class PremiumOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))


def scoped() -> UniqueConstraint:
    return UniqueConstraint("owner_id", "account_id", "id")


def parent(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "account_id", column],
        [f"{table}.owner_id", f"{table}.account_id", f"{table}.id"],
        ondelete="RESTRICT",
        name=f"fk_premium_{table}_{column}",
    )


def digest_constraint(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ~ '^[0-9a-f]{{64}}$'", name=f"{column}_format")


def failure_constraint() -> CheckConstraint:
    return CheckConstraint(
        "failure_code IS NULL OR failure_code IN ("
        "'publication_unavailable','consumer_unavailable','lease_expired','invalid_message',"
        "'input_unavailable','input_changed','access_denied','calculation_failed',"
        "'storage_unavailable','attempts_exhausted','limit_exceeded','source_restricted')",
        name="failure_allowed",
    )


class PremiumCapacityModel(Base):
    __tablename__ = "premium_owner_capacity"
    __table_args__ = (
        CheckConstraint(
            "reserved_bytes >= 0 AND retained_bytes >= 0 AND reserved_bytes + ret"
            "ained_bytes <= 268435456",
            name="bytes_bound",
        ),
        CheckConstraint(
            "active_jobs BETWEEN 0 AND 2 AND definition_versions BETWEEN 0 AND 512",
            name="count_bound",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    retained_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    active_jobs: Mapped[int] = mapped_column(Integer, default=0)
    definition_versions: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class PremiumRunModel(PremiumOwned):
    __tablename__ = "premium_runs"
    __table_args__ = (
        scoped(),
        parent("command_id", "application_command_identities"),
        UniqueConstraint("command_id"),
        digest_constraint("input_digest"),
        CheckConstraint("kind IN ('risk','scenario','projection')", name="kind_allowed"),
        CheckConstraint("expires_at > created_at", name="expiry_order"),
        CheckConstraint(
            "reserved_bytes BETWEEN 0 AND 33554432 AND retained_bytes BETWEEN 0 AND 33554432",
            name="byte_bound",
        ),
        Index(
            "ix_premium_runs_owner_account_created", "owner_id", "account_id", "created_at", "id"
        ),
        Index("ix_premium_runs_expiry", "expires_at", "id"),
    )
    kind: Mapped[str] = mapped_column(String(20))
    command_id: Mapped[UUID] = mapped_column()
    actor_principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("principals.id", ondelete="RESTRICT")
    )
    input_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    method_version: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(40))
    numerical_profile: Mapped[str] = mapped_column(String(60))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger)
    retained_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class PremiumRunLicenseModel(PremiumOwned):
    """Immutable authority references, retained as audit metadata after payload expiry."""

    __tablename__ = "premium_run_licenses"
    __table_args__ = (
        scoped(),
        parent("run_id", "premium_runs"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_premium_run_license_owner_provider",
        ),
        UniqueConstraint("run_id", "license_version_id"),
        Index("ix_premium_run_licenses_provider", "owner_id", "provider_id", "run_id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()


class PremiumJobModel(PremiumOwned):
    __tablename__ = "premium_jobs"
    __table_args__ = (
        scoped(),
        failure_constraint(),
        parent("run_id", "premium_runs"),
        UniqueConstraint("run_id"),
        CheckConstraint(
            "state IN ('queued','running','succeeded','failed','expired','cancelled')",
            name="state_allowed",
        ),
        CheckConstraint("consumer_attempts BETWEEN 0 AND 4", name="attempts_bound"),
        CheckConstraint(
            "(state='running' AND lease_token IS NOT NULL AND lease_expires_at IS"
            " NOT NULL AND heartbeat_at IS NOT NULL AND consumer_id IS NOT NULL A"
            "ND deadline_at IS NOT NULL) OR (state<>'running' AND lease_token IS "
            "NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND consu"
            "mer_id IS NULL AND deadline_at IS NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "deadline_at IS NULL OR heartbeat_at <= deadline_at", name="deadline_order"
        ),
        CheckConstraint(
            "(state IN ('succeeded','failed','expired','cancelled')) = (completed_at IS NOT NULL)",
            name="completion_state",
        ),
        Index(
            "ix_premium_single_running",
            "state",
            unique=True,
            postgresql_where=text("state = 'running'"),
        ),
        Index("ix_premium_jobs_state_lease", "state", "lease_expires_at", "id"),
        Index("ix_premium_jobs_owner_state", "owner_id", "state", "id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(20))
    consumer_attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consumer_id: Mapped[str | None] = mapped_column(String(120))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PremiumOutboxModel(PremiumOwned):
    __tablename__ = "premium_dispatch_outbox"
    __table_args__ = (
        scoped(),
        failure_constraint(),
        parent("job_id", "premium_jobs"),
        UniqueConstraint("job_id"),
        CheckConstraint(
            "task_name IN ('risk.calculate.v1','scenarios.calculate.v1','projecti"
            "ons.calculate.v1')",
            name="fixed_tasks",
        ),
        CheckConstraint(
            "state IN ('pending','claimed','published','completed','dead_letter')",
            name="state_allowed",
        ),
        CheckConstraint("publication_attempts BETWEEN 0 AND 8", name="attempts_bound"),
        CheckConstraint(
            "(state='claimed' AND claim_token IS NOT NULL AND claim_expires_at IS"
            " NOT NULL AND dispatcher_id IS NOT NULL) OR (state<>'claimed' AND cl"
            "aim_token IS NULL AND claim_expires_at IS NULL AND dispatcher_id IS "
            "NULL)",
            name="claim_state",
        ),
        Index("ix_premium_outbox_available", "state", "available_at", "id"),
    )
    job_id: Mapped[UUID] = mapped_column()
    task_name: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(20))
    publication_attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    claim_token: Mapped[UUID | None] = mapped_column()
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dispatcher_id: Mapped[str | None] = mapped_column(String(120))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str | None] = mapped_column(String(40))


class PremiumAttemptModel(PremiumOwned):
    __tablename__ = "premium_job_attempts"
    __table_args__ = (
        scoped(),
        failure_constraint(),
        parent("job_id", "premium_jobs"),
        UniqueConstraint("job_id", "sequence"),
        CheckConstraint("kind IN ('publication','consumer')", name="kind_allowed"),
        CheckConstraint(
            "event IN ('claimed','published','succeeded','failed','expired','cancelled')",
            name="event_allowed",
        ),
        CheckConstraint(
            "sequence BETWEEN 1 AND 100 AND attempt_number BETWEEN 0 AND 8", name="count_bound"
        ),
    )
    job_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(20))
    attempt_number: Mapped[int] = mapped_column(Integer)
    claim_token: Mapped[UUID | None] = mapped_column()
    failure_code: Mapped[str | None] = mapped_column(String(40))


class PremiumRetentionModel(PremiumOwned):
    __tablename__ = "premium_retention_events"
    __table_args__ = (
        scoped(),
        parent("run_id", "premium_runs"),
        UniqueConstraint("run_id"),
        CheckConstraint(
            "reason IN ('source_restricted','run_expired','owner_erasure')", name="reason_allowed"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at", name="completed_order"
        ),
        Index("ix_premium_retention_pending", "completed_at", "owner_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    reason: Mapped[str] = mapped_column(String(30))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PremiumAuditModel(PremiumOwned):
    __tablename__ = "premium_audit_events"
    __table_args__ = (
        scoped(),
        parent("command_id", "application_command_identities"),
        UniqueConstraint("command_id", "kind"),
        CheckConstraint("kind IN ('created','cancelled')", name="kind_allowed"),
    )
    command_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))


PREMIUM_MODELS = (
    PremiumCapacityModel,
    PremiumRunModel,
    PremiumRunLicenseModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumAttemptModel,
    PremiumRetentionModel,
    PremiumAuditModel,
)
