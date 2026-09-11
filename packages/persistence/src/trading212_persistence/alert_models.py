"""Normalized immutable alert evidence and fixed-purpose durable execution."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Sequence,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import UTCDateTime

ALERT_ADMISSION_SEQUENCE = Sequence(
    "alert_admission_attempt_sequence", metadata=Base.metadata, data_type=BigInteger()
)

ALERT_STATES = "'queued','running','succeeded','failed','expired','cancelled'"
ALERT_LIFECYCLES = "'draft','active','paused','archived'"
ALERT_FAILURES = (
    "'missing_input','missing_fx','currency_mismatch','unsupported','ambiguous"
    "_source','unknown_identity','unknown_denominator','incomplete_coverage','"
    "material_quality','inconclusive_lower_bound','not_configured','no_observa"
    "tions','source_restricted','source_expired','input_bound_exceeded','compu"
    "tation_failed','filtered_out','rule_paused','rule_archived','rule_superse"
    "ded','lease_expired','attempts_exhausted','publication_unavailable','stor"
    "age_unavailable','access_denied'"
)


class AlertOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


class AlertAccountOwned(AlertOwned):
    __abstract__ = True
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))


def _owned(table: str) -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id")


def _account(table: str) -> UniqueConstraint:
    return UniqueConstraint("owner_id", "account_id", "id", name=f"uq_{table}_account_id")


def _parent(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{target}.owner_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


def _account_parent(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "account_id", column],
        [f"{target}.owner_id", f"{target}.account_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


class AlertRuleModel(AlertAccountOwned):
    __tablename__ = "alert_rules"
    __table_args__ = (
        _owned("alert_rules"),
        _account("alert_rules"),
        _parent("alert_rules", "principal_id", "principals"),
        ForeignKeyConstraint(
            ["owner_id", "id", "latest_version_id"],
            [
                "alert_rule_versions.owner_id",
                "alert_rule_versions.rule_id",
                "alert_rule_versions.id",
            ],
            name="fk_alert_rules_latest_version_id",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "id", "active_version_id"],
            [
                "alert_rule_versions.owner_id",
                "alert_rule_versions.rule_id",
                "alert_rule_versions.id",
            ],
            name="fk_alert_rules_active_version_id",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="name_bound"),
        CheckConstraint(f"lifecycle IN ({ALERT_LIFECYCLES})", name="lifecycle_allowed"),
        CheckConstraint("revision >= 1 AND lifecycle_sequence >= 1", name="revision_bound"),
        CheckConstraint(
            "lifecycle NOT IN ('active','paused') OR active_version_id IS NOT NULL",
            name="active_version_required",
        ),
        CheckConstraint(
            "last_admission_sequence IS NULL OR last_admission_sequence > 0",
            name="admission_sequence_positive",
        ),
        Index(
            "ix_alert_rules_due",
            "lifecycle",
            text("last_admission_sequence ASC NULLS FIRST"),
            "next_scheduled_for",
            "id",
        ),
        Index("ix_alert_rules_owner_account", "owner_id", "account_id", "created_at", "id"),
    )
    principal_id: Mapped[UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(120))
    lifecycle: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(BigInteger)
    lifecycle_sequence: Mapped[int] = mapped_column(BigInteger)
    latest_version_id: Mapped[UUID | None] = mapped_column()
    active_version_id: Mapped[UUID | None] = mapped_column()
    next_scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_admission_sequence: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AlertRuleVersionModel(AlertAccountOwned):
    __tablename__ = "alert_rule_versions"
    __table_args__ = (
        _owned("alert_rule_versions"),
        _account("alert_rule_versions"),
        _account_parent("alert_rule_versions", "rule_id", "alert_rules"),
        UniqueConstraint("rule_id", "version_number", name="uq_alert_version_number"),
        UniqueConstraint("owner_id", "rule_id", "id", name="uq_alert_version_rule_id"),
        CheckConstraint("version_number >= 1", name="version_positive"),
        CheckConstraint(
            (
                "family IN ('target_drift','group_drift','holding_drift','concentration','effec"
                "tive_company_concentration','etf_overlap','cash_threshold','stale_data','missi"
                "ng_coverage','reconciliation_failure','provider_failure','failed_refresh','div"
                "idend_received','unusual_activity','report_outcome')"
            ),
            name="family_allowed",
        ),
        CheckConstraint(
            (
                "metric IN ('portfolio_l1_drift','group_absolute_drift','holding_absolute_drift"
                "','direct_max_weight','direct_top_n_weight','direct_hhi','effective_entity_wei"
                "ght','effective_top_n_weight','effective_hhi','etf_pair_overlap','portfolio_du"
                "plicated_exposure','cash_amount','cash_weight','source_age_seconds','source_mi"
                "ssing_sessions','missing_count','missing_fraction','reconciliation_failed','re"
                "conciliation_discrepancy_count','provider_failed','provider_consecutive_failur"
                "es','refresh_failed','positive_dividend','absolute_external_flow_amount','acti"
                "vity_count','unclassified_activity','report_terminal')"
            ),
            name="metric_allowed",
        ),
        CheckConstraint("severity IN ('info','warning','critical')", name="severity_allowed"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "octet_length(definition_payload) BETWEEN 1 AND 65536", name="definition_bound"
        ),
        CheckConstraint("cooldown_seconds BETWEEN 0 AND 604800", name="cooldown_bound"),
        CheckConstraint("schedule_kind IN ('interval','daily_utc')", name="schedule_kind"),
        CheckConstraint(
            (
                "(schedule_kind='interval' AND anchor_at IS NOT NULL AND interval_seconds BETWE"
                "EN 300 AND 86400 AND daily_minute IS NULL) OR (schedule_kind='daily_utc' AND a"
                "nchor_at IS NULL AND interval_seconds IS NULL AND daily_minute BETWEEN 0 AND 1"
                "439)"
            ),
            name="schedule_shape",
        ),
    )
    rule_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    family: Mapped[str] = mapped_column(String(50))
    metric: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))
    content_digest: Mapped[str] = mapped_column(String(64))
    definition_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    schedule_kind: Mapped[str] = mapped_column(String(12))
    anchor_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    daily_minute: Mapped[int | None] = mapped_column(Integer)
    cooldown_seconds: Mapped[int] = mapped_column(Integer)


class AlertRuleEventModel(AlertAccountOwned):
    __tablename__ = "alert_rule_events"
    __table_args__ = (
        _owned("alert_rule_events"),
        _account("alert_rule_events"),
        _account_parent("alert_rule_events", "rule_id", "alert_rules"),
        _account_parent("alert_rule_events", "version_id", "alert_rule_versions"),
        _parent("alert_rule_events", "principal_id", "principals"),
        UniqueConstraint("rule_id", "sequence", name="uq_alert_rule_event_sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            (
                "kind IN ('created','version_created','activated','resumed','paused','archived'"
                ",'superseded')"
            ),
            name="kind_allowed",
        ),
        CheckConstraint(f"lifecycle IN ({ALERT_LIFECYCLES})", name="lifecycle_allowed"),
        Index("ix_alert_rule_events_asof", "owner_id", "rule_id", "occurred_at", "sequence"),
    )
    rule_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    principal_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(24))
    lifecycle: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    due_frontier: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertInputSnapshotModel(AlertAccountOwned):
    __tablename__ = "alert_input_snapshots"
    __table_args__ = (
        _owned("alert_input_snapshots"),
        _account("alert_input_snapshots"),
        _account_parent("alert_input_snapshots", "rule_version_id", "alert_rule_versions"),
        UniqueConstraint("rule_version_id", "scheduled_for", name="uq_alert_input_slot"),
        CheckConstraint("execution_intent IN ('live','observe_only')", name="intent_allowed"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("byte_length BETWEEN 1 AND 2097152", name="byte_bound"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        CheckConstraint("source_cutoff_at=scheduled_for", name="slot_cutoff"),
        CheckConstraint("expires_at <= created_at + interval '90 days'", name="expiry_bound"),
        Index("ix_alert_inputs_expiry", "owner_id", "expires_at", "id"),
    )
    rule_version_id: Mapped[UUID] = mapped_column()
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime())
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    execution_intent: Mapped[str] = mapped_column(String(16))
    input_digest: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    sealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertJobBase(AlertAccountOwned):
    __abstract__ = True
    principal_id: Mapped[UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(20))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    consumer_attempts: Mapped[int] = mapped_column(Integer)
    fence: Mapped[int] = mapped_column(BigInteger)
    lease_id: Mapped[UUID | None] = mapped_column()
    consumer_id: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


def _job(
    table: str,
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _account(table),
        _parent(table, "principal_id", "principals"),
        CheckConstraint(f"state IN ({ALERT_STATES})", name="state_allowed"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({ALERT_FAILURES})", name="failure_allowed"
        ),
        CheckConstraint("consumer_attempts BETWEEN 0 AND 4 AND fence >= 0", name="attempt_bound"),
        CheckConstraint(
            (
                "(state='running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL AND"
                " consumer_id IS NOT NULL)"
            ),
            name="lease_state",
        ),
        CheckConstraint(
            "state NOT IN ('succeeded','failed','expired','cancelled') OR completed_at IS NOT NULL",
            name="terminal_time",
        ),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
    )


class AlertEvaluationJobModel(AlertJobBase):
    __tablename__ = "alert_evaluation_jobs"
    __table_args__ = (
        *_job("alert_evaluation_jobs"),
        _account_parent("alert_evaluation_jobs", "rule_id", "alert_rules"),
        _account_parent("alert_evaluation_jobs", "rule_version_id", "alert_rule_versions"),
        _account_parent("alert_evaluation_jobs", "input_id", "alert_input_snapshots"),
        _account_parent("alert_evaluation_jobs", "cancelled_by_event_id", "alert_rule_events"),
        UniqueConstraint("rule_version_id", "scheduled_for", name="uq_alert_evaluation_slot"),
        UniqueConstraint("input_id", name="uq_alert_job_input"),
        CheckConstraint("execution_intent IN ('live','observe_only')", name="intent_allowed"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("lifecycle_sequence >= 1", name="lifecycle_sequence_positive"),
        Index(
            "ix_alert_jobs_predecessor",
            "rule_version_id",
            "execution_intent",
            "scheduled_for",
            "state",
        ),
    )
    rule_id: Mapped[UUID] = mapped_column()
    rule_version_id: Mapped[UUID] = mapped_column()
    input_id: Mapped[UUID] = mapped_column()
    input_digest: Mapped[str] = mapped_column(String(64))
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime())
    execution_intent: Mapped[str] = mapped_column(String(16))
    lifecycle_sequence: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    cancelled_by_event_id: Mapped[UUID | None] = mapped_column()


class AlertOutboxBase(AlertOwned):
    __abstract__ = True
    job_id: Mapped[UUID] = mapped_column()
    task_name: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(16))
    publication_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    claim_token: Mapped[UUID | None] = mapped_column()
    dispatcher_id: Mapped[str | None] = mapped_column(String(120))
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str | None] = mapped_column(String(40))


def _outbox(
    table: str, jobs: str, task: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        UniqueConstraint("job_id", "task_name", name=f"uq_{table}_job_task"),
        CheckConstraint(f"task_name='{task}' AND schema_version='1.0.0'", name="task_allowed"),
        CheckConstraint(
            "state IN ('pending','claimed','published','failed')", name="state_allowed"
        ),
        CheckConstraint("publication_attempts BETWEEN 0 AND 8", name="attempt_bound"),
        CheckConstraint(
            (
                "(state='claimed') = (claim_token IS NOT NULL AND dispatcher_id IS NOT NULL AND"
                " claim_expires_at IS NOT NULL)"
            ),
            name="claim_state",
        ),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
    )


class AlertEvaluationOutboxModel(AlertOutboxBase):
    __tablename__ = "alert_evaluation_outbox"
    __table_args__ = _outbox(
        "alert_evaluation_outbox", "alert_evaluation_jobs", "alerts.evaluate.v1"
    )


class AlertEvaluationModel(AlertAccountOwned):
    __tablename__ = "alert_evaluations"
    __table_args__ = (
        _owned("alert_evaluations"),
        _account("alert_evaluations"),
        _account_parent("alert_evaluations", "job_id", "alert_evaluation_jobs"),
        _account_parent("alert_evaluations", "input_id", "alert_input_snapshots"),
        _account_parent("alert_evaluations", "rule_version_id", "alert_rule_versions"),
        UniqueConstraint("job_id", name="uq_alert_evaluation_job"),
        CheckConstraint("publication_fence > 0", name="publication_fence_positive"),
        UniqueConstraint(
            "rule_version_id",
            "input_digest",
            "method_version",
            name="uq_alert_evaluation_method_input",
        ),
        CheckConstraint(
            "outcome IN ('matched','not_matched','suppressed','unavailable','failed')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            "method_name='alert_evaluation_v1' AND method_version='1.0.0'", name="method_allowed"
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint("byte_length BETWEEN 1 AND 2097152", name="byte_bound"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        Index("ix_alert_evaluations_asof", "owner_id", "account_id", "evaluated_at", "id"),
    )
    publication_fence: Mapped[int] = mapped_column(BigInteger)
    job_id: Mapped[UUID] = mapped_column()
    input_id: Mapped[UUID] = mapped_column()
    rule_version_id: Mapped[UUID] = mapped_column()
    input_digest: Mapped[str] = mapped_column(String(64))
    method_name: Mapped[str] = mapped_column(String(40))
    method_version: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    decision: Mapped[bool | None] = mapped_column(Boolean)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime())
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertConditionModel(AlertAccountOwned):
    __tablename__ = "alert_conditions"
    __table_args__ = (
        _owned("alert_conditions"),
        _account("alert_conditions"),
        _account_parent("alert_conditions", "rule_version_id", "alert_rule_versions"),
        UniqueConstraint("rule_version_id", name="uq_alert_condition_version"),
        CheckConstraint("octet_length(state_payload) BETWEEN 1 AND 65536", name="state_bound"),
    )
    rule_version_id: Mapped[UUID] = mapped_column()
    last_applied_scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime())
    state_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class AlertEventModel(AlertAccountOwned):
    __tablename__ = "alert_events"
    __table_args__ = (
        _owned("alert_events"),
        _account("alert_events"),
        _account_parent("alert_events", "rule_id", "alert_rules"),
        _account_parent("alert_events", "rule_version_id", "alert_rule_versions"),
        _account_parent("alert_events", "evaluation_id", "alert_evaluations"),
        _account_parent("alert_events", "correction_of_id", "alert_events"),
        UniqueConstraint("rule_version_id", "dedup_digest", name="uq_alert_event_identity"),
        CheckConstraint("dedup_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("state IN ('open','resolved')", name="state_allowed"),
        CheckConstraint(
            (
                "notification_state IN ('eligible','suppressed_cooldown','external_delivery_una"
                "vailable')"
            ),
            name="notification_allowed",
        ),
        CheckConstraint("payload IS NULL OR octet_length(payload)<=2097152", name="payload_bound"),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        Index("ix_alert_events_feed", "owner_id", "account_id", "opened_at", "id"),
    )
    rule_id: Mapped[UUID] = mapped_column()
    rule_version_id: Mapped[UUID] = mapped_column()
    evaluation_id: Mapped[UUID] = mapped_column()
    dedup_digest: Mapped[str] = mapped_column(String(64))
    episode_key: Mapped[str | None] = mapped_column(String(200))
    episode_ordinal: Mapped[int | None] = mapped_column(Integer)
    event_identity: Mapped[UUID | None] = mapped_column()
    event_revision_id: Mapped[UUID | None] = mapped_column()
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    family: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(12))
    revision: Mapped[int] = mapped_column(BigInteger)
    notification_state: Mapped[str] = mapped_column(String(40))
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolution_reason: Mapped[str | None] = mapped_column(String(40))
    correction_of_id: Mapped[UUID | None] = mapped_column()
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertEventTransitionModel(AlertAccountOwned):
    __tablename__ = "alert_event_transitions"
    __table_args__ = (
        _owned("alert_event_transitions"),
        _account("alert_event_transitions"),
        _account_parent("alert_event_transitions", "event_id", "alert_events"),
        _account_parent("alert_event_transitions", "evaluation_id", "alert_evaluations"),
        _parent("alert_event_transitions", "principal_id", "principals"),
        UniqueConstraint("event_id", "sequence", name="uq_alert_event_transition_sequence"),
        CheckConstraint(
            "kind IN ('opened','acknowledged','resolved','reopened','observed')",
            name="kind_allowed",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("note IS NULL OR length(note)<=1000", name="note_bound"),
        Index("ix_alert_event_transitions_asof", "owner_id", "event_id", "occurred_at", "sequence"),
    )
    event_id: Mapped[UUID] = mapped_column()
    evaluation_id: Mapped[UUID | None] = mapped_column()
    principal_id: Mapped[UUID | None] = mapped_column()
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(String(1000))


class AlertCommandModel(AlertAccountOwned):
    __tablename__ = "alert_command_identities"
    __table_args__ = (
        _owned("alert_command_identities"),
        _account("alert_command_identities"),
        _account_parent("alert_command_identities", "rule_id", "alert_rules"),
        _account_parent("alert_command_identities", "event_id", "alert_events"),
        UniqueConstraint("owner_id", "command", "idempotency_key", name="uq_alert_command_key"),
        CheckConstraint(
            (
                "command IN ('create_rule','create_rule_version','activate_rule','pause_rule','"
                "archive_rule','acknowledge_event','resolve_event','backfill')"
            ),
            name="command_allowed",
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,180}$'", name="key_format"),
        CheckConstraint("command_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("num_nonnulls(rule_id,event_id)=1", name="parent_xor"),
    )
    command: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    command_digest: Mapped[str] = mapped_column(String(64))
    rule_id: Mapped[UUID | None] = mapped_column()
    event_id: Mapped[UUID | None] = mapped_column()
    resulting_revision: Mapped[int] = mapped_column(BigInteger)
    result_id: Mapped[UUID] = mapped_column()


class AlertAcknowledgmentModel(AlertAccountOwned):
    __tablename__ = "alert_acknowledgments"
    __table_args__ = (
        _owned("alert_acknowledgments"),
        _account("alert_acknowledgments"),
        _account_parent("alert_acknowledgments", "event_id", "alert_events"),
        _account_parent("alert_acknowledgments", "command_id", "alert_command_identities"),
        _parent("alert_acknowledgments", "principal_id", "principals"),
        UniqueConstraint("command_id", name="uq_alert_ack_command"),
        CheckConstraint("note IS NULL OR length(note)<=1000", name="note_bound"),
    )
    event_id: Mapped[UUID] = mapped_column()
    command_id: Mapped[UUID] = mapped_column()
    principal_id: Mapped[UUID] = mapped_column()
    acknowledged_at: Mapped[datetime] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(String(1000))


class InAppNotificationModel(AlertAccountOwned):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        _owned("in_app_notifications"),
        _account("in_app_notifications"),
        _account_parent("in_app_notifications", "event_id", "alert_events"),
        UniqueConstraint("owner_id", "event_id", name="uq_in_app_notification_event"),
    )
    event_id: Mapped[UUID] = mapped_column()
    eligibility: Mapped[str] = mapped_column(String(40))


class NotificationDestinationModel(AlertAccountOwned):
    __tablename__ = "notification_destinations"
    __table_args__ = (
        _owned("notification_destinations"),
        _account("notification_destinations"),
        ForeignKeyConstraint(
            ["owner_id", "id", "current_version_id"],
            [
                "notification_destination_versions.owner_id",
                "notification_destination_versions.destination_id",
                "notification_destination_versions.id",
            ],
            name="fk_destination_current_version",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id", "account_id", "configuration_key", name="uq_notification_destination_config"
        ),
        CheckConstraint("state IN ('configured','unavailable','disabled')", name="state_allowed"),
    )
    configuration_key: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20))
    current_version_id: Mapped[UUID | None] = mapped_column()


class NotificationDestinationVersionModel(AlertAccountOwned):
    __tablename__ = "notification_destination_versions"
    __table_args__ = (
        _owned("notification_destination_versions"),
        _account("notification_destination_versions"),
        _account_parent(
            "notification_destination_versions", "destination_id", "notification_destinations"
        ),
        UniqueConstraint(
            "destination_id", "version_number", name="uq_notification_destination_version"
        ),
        UniqueConstraint("owner_id", "destination_id", "id", name="uq_destination_version_parent"),
        CheckConstraint("channel IN ('in_app','email','webhook')", name="channel_allowed"),
        CheckConstraint(
            "version_number>=1 AND length(label) BETWEEN 1 AND 120", name="version_label_bound"
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    destination_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(12))
    label: Mapped[str] = mapped_column(String(120))
    configuration_key: Mapped[str] = mapped_column(String(120))
    secret_reference: Mapped[str | None] = mapped_column(String(200))
    content_digest: Mapped[str] = mapped_column(String(64))


class NotificationDeliveryJobModel(AlertJobBase):
    __tablename__ = "notification_delivery_jobs"
    __table_args__ = (
        *_job("notification_delivery_jobs"),
        _account_parent("notification_delivery_jobs", "event_id", "alert_events"),
        _account_parent(
            "notification_delivery_jobs",
            "destination_version_id",
            "notification_destination_versions",
        ),
        UniqueConstraint(
            "event_id",
            "destination_version_id",
            "payload_digest",
            name="uq_notification_delivery_identity",
        ),
        CheckConstraint("channel IN ('email','webhook')", name="channel_allowed"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("octet_length(payload) BETWEEN 1 AND 65536", name="payload_bound"),
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    event_id: Mapped[UUID] = mapped_column()
    destination_version_id: Mapped[UUID] = mapped_column()
    channel: Mapped[str] = mapped_column(String(12))
    payload_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class NotificationDeliveryOutboxModel(AlertOutboxBase):
    __tablename__ = "notification_delivery_outbox"
    __table_args__ = _outbox(
        "notification_delivery_outbox", "notification_delivery_jobs", "notifications.deliver.v1"
    )


class AlertAttemptBase(AlertOwned):
    __abstract__ = True
    job_id: Mapped[UUID] = mapped_column()
    phase: Mapped[str] = mapped_column(String(12))
    attempt: Mapped[int] = mapped_column(Integer)
    fence: Mapped[int] = mapped_column(BigInteger)
    outcome: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(String(40))


def _attempt(
    table: str, job_table: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", job_table),
        CheckConstraint("phase IN ('dispatch','consumer')", name="phase_allowed"),
        CheckConstraint("attempt BETWEEN 1 AND 8 AND fence>=0", name="attempt_bound"),
        CheckConstraint(
            "outcome IN ('claimed','published','retry','succeeded','failed','expired','cancelled')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({ALERT_FAILURES})", name="failure_allowed"
        ),
        UniqueConstraint("job_id", "phase", "attempt", "outcome", name=f"uq_{table}_outcome"),
    )


class AlertEvaluationAttemptModel(AlertAttemptBase):
    __tablename__ = "alert_evaluation_attempts"
    __table_args__ = _attempt("alert_evaluation_attempts", "alert_evaluation_jobs")


class NotificationDeliveryAttemptModel(AlertAttemptBase):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = _attempt("notification_delivery_attempts", "notification_delivery_jobs")


class AlertRetentionWorkModel(AlertOwned):
    __tablename__ = "alert_retention_work"
    __table_args__ = (
        _owned("alert_retention_work"),
        _parent("alert_retention_work", "input_id", "alert_input_snapshots"),
        UniqueConstraint("input_id", name="uq_alert_retention_input"),
        CheckConstraint("reason IN ('ttl','source','owner')", name="reason_allowed"),
    )
    input_id: Mapped[UUID] = mapped_column()
    reason: Mapped[str] = mapped_column(String(12))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertInputDependencyModel(AlertOwned):
    __tablename__ = "alert_input_dependencies"
    __table_args__ = (
        _owned("alert_input_dependencies"),
        _parent("alert_input_dependencies", "input_id", "alert_input_snapshots"),
        UniqueConstraint("input_id", "source_key", name="uq_alert_dependencies_source"),
        _parent("alert_input_dependencies", "license_version_id", "provider_license_versions"),
        _parent("alert_input_dependencies", "provider_id", "market_data_providers"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_alert_dependencies_provider_license",
            ondelete="RESTRICT",
        ),
        _parent("alert_input_dependencies", "price_snapshot_id", "price_snapshots"),
        _parent("alert_input_dependencies", "fx_snapshot_id", "fx_snapshots"),
        _parent("alert_input_dependencies", "benchmark_snapshot_id", "benchmark_snapshots"),
        _parent(
            "alert_input_dependencies",
            "corporate_action_snapshot_id",
            "corporate_action_snapshots",
        ),
        _parent(
            "alert_input_dependencies", "classification_snapshot_id", "classification_snapshots"
        ),
        _parent("alert_input_dependencies", "constituent_snapshot_id", "constituent_snapshots"),
        _parent(
            "alert_input_dependencies", "entity_evidence_version_id", "entity_evidence_versions"
        ),
        _parent("alert_input_dependencies", "fund_definition_id", "fund_definitions"),
        _parent("alert_input_dependencies", "fund_mapping_id", "fund_source_mappings"),
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
        Index("ix_alert_dependencies_input", "owner_id", "input_id", "id"),
        Index("ix_alert_dependencies_license", "owner_id", "license_version_id", "input_id"),
        Index("ix_alert_dependencies_source", "owner_id", "kind", "source_id", "input_id"),
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


class AlertInputLicenseModel(AlertOwned):
    __tablename__ = "alert_input_licenses"
    __table_args__ = (
        _owned("alert_input_licenses"),
        _parent("alert_input_licenses", "input_id", "alert_input_snapshots"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_alert_input_licenses_provider_license",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("input_id", "license_version_id", name="uq_alert_input_license"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_alert_licenses_input", "owner_id", "input_id", "id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))


ALERT_MODELS = (
    AlertRuleModel,
    AlertRuleVersionModel,
    AlertRuleEventModel,
    AlertInputSnapshotModel,
    AlertEvaluationJobModel,
    AlertEvaluationOutboxModel,
    AlertEvaluationModel,
    AlertConditionModel,
    AlertEventModel,
    AlertEventTransitionModel,
    AlertCommandModel,
    AlertAcknowledgmentModel,
    InAppNotificationModel,
    NotificationDestinationModel,
    NotificationDestinationVersionModel,
    NotificationDeliveryJobModel,
    NotificationDeliveryOutboxModel,
    AlertEvaluationAttemptModel,
    NotificationDeliveryAttemptModel,
    AlertRetentionWorkModel,
    AlertInputDependencyModel,
    AlertInputLicenseModel,
)
