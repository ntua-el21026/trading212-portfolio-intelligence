"""Add a transactional refresh-dispatch outbox and request fingerprints.

Revision ID: 20260901_0004
Revises: 20260831_0003
Create Date: 2026-09-01
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0004"
down_revision: str | None = "20260831_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FULL_CAPABILITIES = (
    "metadata_instruments",
    "metadata_exchanges",
    "account_summary",
    "portfolio_positions",
    "pending_orders",
    "historical_orders",
    "historical_transactions",
    "historical_dividends",
    "historical_exports",
)


def _selection(warnings: object) -> Mapping[str, Any]:
    if not isinstance(warnings, list):
        return {}
    for item in warnings:
        if isinstance(item, Mapping) and item.get("kind") == "refresh_selection":
            return item
    return {}


def _capabilities(value: object, fallback: Sequence[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    parsed = [item for item in value if isinstance(item, str) and item]
    if len(parsed) != len(value) or not parsed or len(parsed) != len(set(parsed)):
        return list(fallback)
    return parsed


def _fingerprint(
    *, owner_id: object, account_id: object, mode: str, capabilities: Sequence[str]
) -> str:
    canonical = json.dumps(
        {
            "account_id": str(account_id),
            "create_snapshot": True,
            "owner_id": str(owner_id),
            "requested_capabilities": list(capabilities),
            "requested_mode": mode,
            "schema_version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def upgrade() -> None:
    op.add_column(
        "ingestion_leases",
        sa.Column("fencing_token", sa.Uuid(), nullable=True),
    )
    connection = op.get_bind()
    lease_ids = connection.scalars(sa.text("SELECT id FROM ingestion_leases ORDER BY id")).all()
    for lease_id in lease_ids:
        connection.execute(
            sa.text(
                "UPDATE ingestion_leases SET fencing_token = :fencing_token WHERE id = :lease_id"
            ),
            {"lease_id": lease_id, "fencing_token": uuid4()},
        )
    op.alter_column("ingestion_leases", "fencing_token", nullable=False)
    op.create_unique_constraint(
        "uq_ingestion_leases_fencing_token",
        "ingestion_leases",
        ["fencing_token"],
    )

    op.add_column(
        "ingestion_runs", sa.Column("request_schema_version", sa.Integer(), nullable=True)
    )
    op.add_column("ingestion_runs", sa.Column("requested_mode", sa.String(20), nullable=True))
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "requested_create_snapshot",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=True,
        ),
    )
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "requested_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "effective_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("ingestion_runs", sa.Column("request_fingerprint", sa.String(64), nullable=True))

    connection.execute(
        sa.text(
            "UPDATE ingestion_runs SET requested_create_snapshot = TRUE "
            "WHERE requested_create_snapshot IS NULL"
        )
    )
    rows = (
        connection.execute(
            sa.text(
                "SELECT runs.id, connections.owner_id, runs.broker_account_id, "
                "runs.mode, runs.warnings FROM ingestion_runs AS runs "
                "JOIN broker_accounts AS accounts ON accounts.id = runs.broker_account_id "
                "JOIN broker_connections AS connections ON connections.id = accounts.connection_id "
                "ORDER BY runs.id"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        selection = _selection(row["warnings"])
        raw_mode = selection.get("requested_mode", row["mode"])
        requested_mode = raw_mode if raw_mode in {"full", "incremental"} else "full"
        effective = _capabilities(selection.get("capabilities"), _FULL_CAPABILITIES)
        requested = _capabilities(selection.get("requested_capabilities"), effective)
        connection.execute(
            sa.text(
                "UPDATE ingestion_runs SET "
                "request_schema_version = 1, requested_mode = :requested_mode, "
                "requested_create_snapshot = TRUE, "
                "requested_capabilities = CAST(:requested_capabilities AS jsonb), "
                "effective_capabilities = CAST(:effective_capabilities AS jsonb), "
                "request_fingerprint = :request_fingerprint WHERE id = :run_id"
            ),
            {
                "run_id": row["id"],
                "requested_mode": requested_mode,
                "requested_capabilities": json.dumps(requested, separators=(",", ":")),
                "effective_capabilities": json.dumps(effective, separators=(",", ":")),
                "request_fingerprint": _fingerprint(
                    owner_id=row["owner_id"],
                    account_id=row["broker_account_id"],
                    mode=requested_mode,
                    capabilities=requested,
                ),
            },
        )

    for column in (
        "request_schema_version",
        "requested_mode",
        "requested_create_snapshot",
        "requested_capabilities",
        "effective_capabilities",
        "request_fingerprint",
    ):
        op.alter_column("ingestion_runs", column, nullable=False)

    op.create_check_constraint(
        op.f("ck_ingestion_runs_requested_mode_allowed"),
        "ingestion_runs",
        "requested_mode IN ('full','incremental')",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_request_schema_version_supported"),
        "ingestion_runs",
        "request_schema_version = 1",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_request_fingerprint_format"),
        "ingestion_runs",
        "request_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_requested_capabilities_array"),
        "ingestion_runs",
        "jsonb_typeof(requested_capabilities) = 'array'",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_effective_capabilities_array"),
        "ingestion_runs",
        "jsonb_typeof(effective_capabilities) = 'array'",
    )

    op.create_table(
        "refresh_dispatch_outbox",
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(80), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumer_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "consecutive_failure_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_owner", sa.String(120), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "task_name = 'portfolio.refresh'",
            name=op.f("ck_refresh_dispatch_outbox_task_name_fixed"),
        ),
        sa.CheckConstraint(
            "task_version = 1", name=op.f("ck_refresh_dispatch_outbox_task_version_supported")
        ),
        sa.CheckConstraint(
            "status IN ('pending','publishing','published','dead')",
            name=op.f("ck_refresh_dispatch_outbox_status_allowed"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_refresh_dispatch_outbox_attempt_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "consumer_attempt_count BETWEEN 0 AND 4",
            name=op.f("ck_refresh_dispatch_outbox_consumer_attempt_count_bounded"),
        ),
        sa.CheckConstraint(
            "consecutive_failure_count >= 0",
            name=op.f("ck_refresh_dispatch_outbox_consecutive_failures_nonnegative"),
        ),
        sa.CheckConstraint(
            "consecutive_failure_count <= attempt_count",
            name=op.f("ck_refresh_dispatch_outbox_consecutive_failures_within_attempts"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND "
            "payload ?& ARRAY['run_id','account_id','request_fingerprint',"
            "'request_schema_version'] AND "
            "payload - ARRAY['run_id','account_id','request_fingerprint',"
            "'request_schema_version'] = '{}'::jsonb AND "
            "(payload->>'run_id')::uuid = ingestion_run_id AND "
            "(payload->>'account_id') ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND "
            "(payload->>'request_fingerprint') ~ '^[0-9a-f]{64}$' AND "
            "payload->>'request_schema_version' = '1'",
            name=op.f("ck_refresh_dispatch_outbox_payload_contract"),
        ),
        sa.CheckConstraint(
            "(status = 'publishing' AND claim_token IS NOT NULL "
            "AND claim_owner IS NOT NULL AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL) OR "
            "(status != 'publishing' AND claim_token IS NULL AND claim_owner IS NULL "
            "AND claimed_at IS NULL AND claim_expires_at IS NULL)",
            name=op.f("ck_refresh_dispatch_outbox_publishing_claim_present"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND published_at IS NULL) OR "
            "(status = 'publishing' AND published_at IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL) OR "
            "(status = 'dead' AND published_at IS NULL)",
            name=op.f("ck_refresh_dispatch_outbox_publication_state_match"),
        ),
        sa.CheckConstraint(
            "claim_owner IS NULL OR claim_owner ~ '^[A-Za-z0-9._:-]{1,120}$'",
            name=op.f("ck_refresh_dispatch_outbox_claim_owner_format"),
        ),
        sa.CheckConstraint(
            "claim_expires_at IS NULL OR "
            "(claimed_at IS NOT NULL AND claim_expires_at > claimed_at)",
            name=op.f("ck_refresh_dispatch_outbox_claim_expiry_order"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_refresh_dispatch_outbox_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_dispatch_outbox")),
        sa.UniqueConstraint("ingestion_run_id", name="uq_refresh_dispatch_outbox_run"),
    )
    op.create_index(
        "ix_refresh_dispatch_outbox_ready",
        "refresh_dispatch_outbox",
        ["status", "available_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_refresh_dispatch_outbox_claim_expiry",
        "refresh_dispatch_outbox",
        ["claim_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'publishing'"),
    )

    op.create_table(
        "refresh_dispatcher_heartbeats",
        sa.Column("dispatcher_id", sa.String(120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_successful_cycle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "dispatcher_id ~ '^[A-Za-z0-9._:-]{1,120}$'",
            name=op.f("ck_refresh_dispatcher_heartbeats_identity_format"),
        ),
        sa.CheckConstraint(
            "state IN ('healthy','degraded')",
            name=op.f("ck_refresh_dispatcher_heartbeats_state_allowed"),
        ),
        sa.CheckConstraint(
            "heartbeat_at >= started_at",
            name=op.f("ck_refresh_dispatcher_heartbeats_heartbeat_order"),
        ),
        sa.CheckConstraint(
            "last_successful_cycle_at IS NULL OR "
            "(last_successful_cycle_at >= started_at "
            "AND last_successful_cycle_at <= heartbeat_at)",
            name=op.f("ck_refresh_dispatcher_heartbeats_success_order"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_dispatcher_heartbeats")),
        sa.UniqueConstraint(
            "dispatcher_id",
            name="uq_refresh_dispatcher_heartbeats_identity",
        ),
    )
    op.create_index(
        "ix_refresh_dispatcher_heartbeats_state_heartbeat",
        "refresh_dispatcher_heartbeats",
        ["state", "heartbeat_at"],
        unique=False,
    )

    now = datetime.now(UTC)
    recoverable = (
        connection.execute(
            sa.text(
                "SELECT id, broker_account_id, request_fingerprint, "
                "request_schema_version, status, error_code FROM ingestion_runs "
                "WHERE status IN ('queued','running') "
                "OR (status = 'failed' AND error_code = 'queue_unavailable') "
                "ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    outbox_table = sa.table(
        "refresh_dispatch_outbox",
        sa.column("id", sa.Uuid()),
        sa.column("ingestion_run_id", sa.Uuid()),
        sa.column("task_name", sa.String()),
        sa.column("task_version", sa.Integer()),
        sa.column("payload", postgresql.JSONB()),
        sa.column("status", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("consecutive_failure_count", sa.Integer()),
        sa.column("available_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    if recoverable:
        op.bulk_insert(
            outbox_table,
            [
                {
                    "id": uuid4(),
                    "ingestion_run_id": row["id"],
                    "task_name": "portfolio.refresh",
                    "task_version": 1,
                    "payload": {
                        "run_id": str(row["id"]),
                        "account_id": str(row["broker_account_id"]),
                        "request_fingerprint": row["request_fingerprint"],
                        "request_schema_version": row["request_schema_version"],
                    },
                    "status": "pending",
                    "attempt_count": 0,
                    "consecutive_failure_count": 0,
                    "available_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
                for row in recoverable
            ],
        )
    connection.execute(
        sa.text(
            "UPDATE ingestion_runs SET status = 'queued', error_code = NULL, "
            "completed_at = NULL WHERE status = 'failed' AND error_code = 'queue_unavailable'"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_refresh_dispatcher_heartbeats_state_heartbeat",
        table_name="refresh_dispatcher_heartbeats",
    )
    op.drop_table("refresh_dispatcher_heartbeats")
    op.drop_index("ix_refresh_dispatch_outbox_claim_expiry", table_name="refresh_dispatch_outbox")
    op.drop_index("ix_refresh_dispatch_outbox_ready", table_name="refresh_dispatch_outbox")
    op.drop_table("refresh_dispatch_outbox")
    op.drop_constraint(
        "ck_ingestion_runs_effective_capabilities_array", "ingestion_runs", type_="check"
    )
    op.drop_constraint(
        "ck_ingestion_runs_requested_capabilities_array", "ingestion_runs", type_="check"
    )
    op.drop_constraint(
        "ck_ingestion_runs_request_fingerprint_format", "ingestion_runs", type_="check"
    )
    op.drop_constraint(
        "ck_ingestion_runs_request_schema_version_supported", "ingestion_runs", type_="check"
    )
    op.drop_constraint("ck_ingestion_runs_requested_mode_allowed", "ingestion_runs", type_="check")
    op.drop_column("ingestion_runs", "request_fingerprint")
    op.drop_column("ingestion_runs", "effective_capabilities")
    op.drop_column("ingestion_runs", "requested_capabilities")
    op.drop_column("ingestion_runs", "requested_create_snapshot")
    op.drop_column("ingestion_runs", "requested_mode")
    op.drop_column("ingestion_runs", "request_schema_version")
    op.drop_constraint(
        "uq_ingestion_leases_fencing_token",
        "ingestion_leases",
        type_="unique",
    )
    op.drop_column("ingestion_leases", "fencing_token")
