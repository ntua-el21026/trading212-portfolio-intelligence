"""Durable closed provider acquisition authority and fenced attempts.

Revision ID: 20260915_0027; down revision: 20260915_0026.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0027"
down_revision = "20260915_0026"
branch_labels = None
depends_on = None

CAPABILITIES = "('daily_adjusted','etf_profile','company_overview','news_sentiment','reference_fx')"
OUTCOMES = "('not_configured','access_denied','license_denied','authentication_failed','rate_limited','timeout','transient_failure','invalid_schema','payload_too_large','unsupported','permanent_failure','attempt_fence_lost')"


def owned():
    return sa.UniqueConstraint("owner_id", "id")


def owner_fk(column, table):
    return sa.ForeignKeyConstraint(
        ["owner_id", column], [f"{table}.owner_id", f"{table}.id"], ondelete="RESTRICT"
    )


def upgrade():
    op.create_table(
        "provider_capability_scopes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(24), nullable=False),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        sa.CheckConstraint(f"capability IN {CAPABILITIES}", name="capability"),
        sa.CheckConstraint(
            "(capability IN ('daily_adjusted','etf_profile') AND subject_kind='instrument' AND subject_id IS NOT NULL) OR (capability IN ('company_overview','news_sentiment') AND subject_kind='entity' AND subject_id IS NOT NULL) OR (capability='reference_fx' AND subject_kind='reference_fx' AND subject_id IS NULL)",
            name="subject",
        ),
        sa.UniqueConstraint("owner_id", "provider_id", "id", name="uq_acq_scope_provider"),
    )
    op.create_table(
        "provider_capability_grants",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("store_allowed", sa.Boolean(), nullable=False),
        sa.Column("display_allowed", sa.Boolean(), nullable=False),
        sa.Column("report_allowed", sa.Boolean(), nullable=False),
        sa.Column("export_allowed", sa.Boolean(), nullable=False),
        sa.Column("daily_allowance", sa.Integer(), nullable=False),
        sa.Column("evidence_key", sa.String(120), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        owned(),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id", "scope_id"],
            [
                "provider_capability_scopes.owner_id",
                "provider_capability_scopes.provider_id",
                "provider_capability_scopes.id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
        ),
        sa.UniqueConstraint("scope_id", "version_number"),
        sa.CheckConstraint(
            "version_number >= 1 AND expires_at > effective_at AND daily_allowance BETWEEN 0 AND 25",
            name="bounds",
        ),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
    )
    op.create_table(
        "provider_acquisition_policies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_allowance", sa.Integer(), nullable=False),
        sa.Column("evidence_key", sa.String(120), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        sa.UniqueConstraint("provider_id", "version_number"),
        sa.CheckConstraint(
            "version_number >= 1 AND expires_at > effective_at AND daily_allowance BETWEEN 0 AND 25 AND (NOT enabled OR daily_allowance > 0)",
            name="bounds",
        ),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
    )
    op.create_table(
        "provider_acquisition_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("market_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
        sa.Column("source_series_id", sa.Uuid(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_key", sa.String(120), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        owned(),
        owner_fk("scope_id", "provider_capability_scopes"),
        owner_fk("market_mapping_id", "market_data_instruments"),
        owner_fk("calendar_id", "source_calendars"),
        owner_fk("source_series_id", "market_source_series"),
        sa.UniqueConstraint("scope_id", "version_number"),
        sa.CheckConstraint("version_number >= 1 AND expires_at > effective_at", name="bounds"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
    )
    op.create_table(
        "provider_acquisition_requests",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(24), nullable=False),
        sa.Column("mapping_version_id", sa.Uuid(), nullable=False),
        sa.Column("mapping_digest", sa.String(64), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("grant_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("first_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("mapping_version_id", "provider_acquisition_mappings"),
        owner_fk("policy_version_id", "provider_acquisition_policies"),
        owner_fk("grant_id", "provider_capability_grants"),
        sa.ForeignKeyConstraint(
            ["owner_id", "principal_id"], ["principals.owner_id", "principals.id"]
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$' AND mapping_digest ~ '^[0-9a-f]{64}$' AND policy_digest ~ '^[0-9a-f]{64}$' AND grant_digest ~ '^[0-9a-f]{64}$'",
            name="digests",
        ),
        sa.CheckConstraint(f"capability IN {CAPABILITIES}", name="capability"),
        sa.CheckConstraint(
            "attempt_count BETWEEN 1 AND 3 AND deadline > first_started_at AND deadline <= first_started_at + interval '20 seconds'",
            name="deadline",
        ),
        sa.CheckConstraint(
            "state IN ('inflight','retry','succeeded','failed') AND ((state='retry' AND retry_at IS NOT NULL AND retry_at < deadline) OR (state<>'retry' AND retry_at IS NULL))",
            name="state",
        ),
    )
    op.create_table(
        "provider_acquisition_days",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("utc_day", sa.Date(), nullable=False),
        sa.Column("charged_attempts", sa.Integer(), nullable=False),
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        sa.UniqueConstraint("owner_id", "provider_id", "utc_day", name="uq_acq_daily_provider"),
        sa.CheckConstraint("charged_attempts BETWEEN 0 AND 25", name="charged"),
    )
    op.create_table(
        "provider_acquisition_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("day_id", sa.Uuid(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("first_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        owned(),
        owner_fk("request_id", "provider_acquisition_requests"),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("day_id", "provider_acquisition_days"),
        sa.UniqueConstraint("request_id", "ordinal"),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 3 AND reserved_at < lease_expires_at AND lease_expires_at <= deadline AND deadline <= first_started_at + interval '20 seconds' AND reserved_at >= first_started_at",
            name="times",
        ),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        sa.CheckConstraint(f"outcome IS NULL OR outcome IN {OUTCOMES}", name="outcome"),
        sa.CheckConstraint(
            "(finished_at IS NULL AND outcome IS NULL AND retry_at IS NULL) OR (finished_at >= reserved_at AND (retry_at IS NULL OR (outcome IN ('rate_limited','timeout','transient_failure') AND ordinal < 3 AND retry_at >= finished_at + ordinal * interval '1 second' AND retry_at <= finished_at + interval '60 seconds' AND retry_at < deadline)))",
            name="finish",
        ),
    )
    op.create_table(
        "provider_acquisition_slots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("attempt_id", "provider_acquisition_attempts"),
        sa.UniqueConstraint("owner_id", "provider_id", name="uq_acq_active_provider_slot"),
        sa.UniqueConstraint("attempt_id"),
    )
    op.create_table(
        "provider_acquisition_publications",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(12), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("acquisition_digest", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        owned(),
        owner_fk("attempt_id", "provider_acquisition_attempts"),
        sa.UniqueConstraint("attempt_id", "source_kind", "source_id"),
        sa.UniqueConstraint("owner_id", "source_kind", "source_id", name="uq_acq_original_source"),
        sa.CheckConstraint(
            "source_kind IN ('price','fx','research') AND content_digest ~ '^[0-9a-f]{64}$' AND acquisition_digest ~ '^[0-9a-f]{64}$'",
            name="identity",
        ),
        sa.CheckConstraint(
            "first_known_at=acquired_at AND published_at >= acquired_at AND expires_at > published_at AND expires_at <= acquired_at + interval '30 days'",
            name="original_clock",
        ),
    )
    op.create_table(
        "provider_acquisition_market_results",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("owners.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        owned(),
        owner_fk("attempt_id", "provider_acquisition_attempts"),
        owner_fk("publication_id", "provider_acquisition_publications"),
        sa.UniqueConstraint("attempt_id"),
    )
    op.create_index(
        "uq_acq_subject_scope",
        "provider_capability_scopes",
        ["owner_id", "provider_id", "capability", "subject_id"],
        unique=True,
        postgresql_where=sa.text("subject_id IS NOT NULL"),
    )
    op.create_index(
        "uq_acq_fx_scope",
        "provider_capability_scopes",
        ["owner_id", "provider_id", "capability"],
        unique=True,
        postgresql_where=sa.text("subject_id IS NULL"),
    )
    op.create_index(
        "ix_acq_grant_current",
        "provider_capability_grants",
        ["owner_id", "scope_id", "effective_at", "version_number", "id"],
    )
    op.create_index(
        "ix_acq_policy_current",
        "provider_acquisition_policies",
        ["owner_id", "provider_id", "effective_at", "version_number", "id"],
    )
    op.create_index(
        "ix_acq_mapping_current",
        "provider_acquisition_mappings",
        ["owner_id", "scope_id", "effective_at", "version_number", "id"],
    )
    op.create_index("ix_acq_request_owner", "provider_acquisition_requests", ["owner_id", "id"])
    op.create_index(
        "ix_acq_attempt_day", "provider_acquisition_attempts", ["owner_id", "day_id", "id"]
    )
    op.execute(_GUARDS)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM provider_capability_scopes)
        OR EXISTS (SELECT 1 FROM provider_acquisition_requests)
        OR EXISTS (SELECT 1 FROM provider_acquisition_days)
        OR EXISTS (SELECT 1 FROM provider_acquisition_policies)
      THEN RAISE EXCEPTION 'Acquisition authority and charged receipts must not be discarded';
      END IF;
    END $$;""")
    op.execute(_DROP_GUARDS)
    op.drop_table("provider_acquisition_market_results")
    op.drop_table("provider_acquisition_publications")
    op.drop_table("provider_acquisition_slots")
    op.drop_table("provider_acquisition_attempts")
    op.drop_table("provider_acquisition_days")
    op.drop_table("provider_acquisition_requests")
    op.drop_table("provider_acquisition_mappings")
    op.drop_table("provider_acquisition_policies")
    op.drop_table("provider_capability_grants")
    op.drop_table("provider_capability_scopes")


_GUARDS = r"""
CREATE FUNCTION acquisition_owned_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s provider_capability_scopes; p market_data_providers; r provider_acquisition_requests;
 a provider_acquisition_attempts; d provider_acquisition_days; g provider_capability_grants;
 cg provider_capability_grants; pol provider_acquisition_policies; cp provider_acquisition_policies;
 m provider_acquisition_mappings; mm market_data_instruments; account_owner uuid; cap integer;
 original_l provider_license_versions; current_l provider_license_versions; needed text[];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Acquisition identities are immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('sources:'||NEW.owner_id::text,0));
 IF TG_TABLE_NAME IN ('provider_capability_scopes','provider_capability_grants','provider_acquisition_policies','provider_acquisition_mappings','provider_acquisition_publications') AND TG_OP='UPDATE'
 THEN RAISE EXCEPTION 'Acquisition authority is immutable' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='provider_capability_scopes' THEN
  SELECT * INTO p FROM market_data_providers WHERE owner_id=NEW.owner_id AND id=NEW.provider_id;
  IF p.id IS NULL OR p.key<>(CASE WHEN NEW.capability='reference_fx' THEN 'ecb' ELSE 'alpha_vantage' END) THEN RAISE EXCEPTION 'Acquisition provider mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.subject_kind='entity' THEN
   IF NOT EXISTS(SELECT 1 FROM economic_entities WHERE owner_id=NEW.owner_id AND id=NEW.subject_id) THEN RAISE EXCEPTION 'Acquisition entity missing' USING ERRCODE='23514'; END IF;
  ELSIF NEW.subject_kind='instrument' THEN
   IF NOT EXISTS(SELECT 1 FROM instruments WHERE id=NEW.subject_id) THEN RAISE EXCEPTION 'Acquisition instrument missing' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='provider_capability_grants' THEN
  SELECT * INTO s FROM provider_capability_scopes WHERE owner_id=NEW.owner_id AND id=NEW.scope_id;
  IF s.id IS NULL OR s.provider_id<>NEW.provider_id THEN RAISE EXCEPTION 'Grant scope mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.version_number<>coalesce((SELECT max(version_number) FROM provider_capability_grants WHERE scope_id=NEW.scope_id),0)+1 THEN RAISE EXCEPTION 'Grant revision mismatch' USING ERRCODE='23514'; END IF;
  IF s.capability='reference_fx' AND NEW.daily_allowance>24 THEN RAISE EXCEPTION 'ECB allowance exceeds cap' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_policies' THEN
  SELECT * INTO p FROM market_data_providers WHERE owner_id=NEW.owner_id AND id=NEW.provider_id;
  IF p.id IS NULL OR p.key NOT IN ('alpha_vantage','ecb') OR (p.key='ecb' AND NEW.daily_allowance>24) THEN RAISE EXCEPTION 'Policy provider mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.version_number<>coalesce((SELECT max(version_number) FROM provider_acquisition_policies WHERE provider_id=NEW.provider_id),0)+1 THEN RAISE EXCEPTION 'Policy revision mismatch' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_mappings' THEN
  SELECT * INTO s FROM provider_capability_scopes WHERE owner_id=NEW.owner_id AND id=NEW.scope_id;
  IF NEW.version_number<>coalesce((SELECT max(version_number) FROM provider_acquisition_mappings WHERE scope_id=NEW.scope_id),0)+1 THEN RAISE EXCEPTION 'Mapping revision mismatch' USING ERRCODE='23514'; END IF;
  IF s.capability='reference_fx' THEN
   IF NEW.market_mapping_id IS NOT NULL OR NEW.source_series_id IS NOT NULL THEN RAISE EXCEPTION 'ECB cannot invent a security mapping' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO mm FROM market_data_instruments WHERE owner_id=NEW.owner_id AND id=NEW.market_mapping_id;
   IF mm.id IS NULL OR mm.provider_id<>s.provider_id OR mm.state<>'resolved' OR mm.instrument_id IS NULL OR (s.subject_kind='instrument' AND s.subject_id<>mm.instrument_id) THEN RAISE EXCEPTION 'Canonical mapping mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.source_series_id IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM market_source_series WHERE owner_id=NEW.owner_id AND id=NEW.source_series_id AND provider_id=s.provider_id AND mapping_id=NEW.market_mapping_id AND calendar_id=NEW.calendar_id AND basis='raw_close' AND instrument_id=mm.instrument_id AND currency=mm.currency) THEN RAISE EXCEPTION 'Canonical raw series mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_requests' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.state<>'inflight' OR NEW.attempt_count<>1 THEN RAISE EXCEPTION 'Initial request state invalid' USING ERRCODE='23514'; END IF;
  ELSE
   IF (to_jsonb(NEW)-ARRAY['state','retry_at','attempt_count']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','retry_at','attempt_count']) THEN RAISE EXCEPTION 'Request identity changed' USING ERRCODE='23514'; END IF;
   IF NOT ((OLD.state='retry' AND NEW.state='inflight' AND NEW.attempt_count=OLD.attempt_count+1 AND OLD.retry_at<=clock_timestamp() AND OLD.deadline>clock_timestamp()) OR (OLD.state='inflight' AND NEW.state IN ('retry','succeeded','failed') AND NEW.attempt_count=OLD.attempt_count)) THEN RAISE EXCEPTION 'Request transition invalid' USING ERRCODE='23514'; END IF;
  END IF;
  SELECT c.owner_id INTO account_owner FROM broker_accounts b JOIN broker_connections c ON c.id=b.connection_id WHERE b.id=NEW.account_id;
  IF account_owner IS DISTINCT FROM NEW.owner_id OR NOT EXISTS(SELECT 1 FROM principals WHERE id=NEW.principal_id AND owner_id=NEW.owner_id) THEN RAISE EXCEPTION 'Request account identity missing' USING ERRCODE='23514'; END IF;
  IF NEW.state<>'failed' THEN
   IF NOT EXISTS(SELECT 1 FROM broker_accounts b JOIN broker_connections c ON c.id=b.connection_id WHERE b.id=NEW.account_id AND b.status='active' AND c.status='active')
    OR NOT EXISTS(SELECT 1 FROM principals WHERE id=NEW.principal_id AND owner_id=NEW.owner_id AND status='active') THEN RAISE EXCEPTION 'Request account authority missing' USING ERRCODE='23514'; END IF;
   needed:=ARRAY['portfolio:read','analytics:read','targets:write'];
   IF NEW.capability IN ('news_sentiment','company_overview') THEN needed:=needed||ARRAY['research:read','research:write']; END IF;
   IF EXISTS(SELECT 1 FROM unnest(needed) required(scope) WHERE NOT EXISTS(
    SELECT 1 FROM principal_scope_grants scope_grant WHERE scope_grant.principal_id=NEW.principal_id AND scope_grant.scope=required.scope
     AND scope_grant.granted_at<=clock_timestamp() AND scope_grant.revoked_at IS NULL AND (scope_grant.expires_at IS NULL OR scope_grant.expires_at>clock_timestamp())))
   THEN RAISE EXCEPTION 'Request current scopes missing' USING ERRCODE='23514'; END IF;
  END IF;
  SELECT * INTO m FROM provider_acquisition_mappings WHERE owner_id=NEW.owner_id AND id=NEW.mapping_version_id;
  SELECT * INTO s FROM provider_capability_scopes WHERE owner_id=NEW.owner_id AND id=m.scope_id;
  SELECT * INTO g FROM provider_capability_grants WHERE owner_id=NEW.owner_id AND id=NEW.grant_id;
  SELECT * INTO pol FROM provider_acquisition_policies WHERE owner_id=NEW.owner_id AND id=NEW.policy_version_id;
  IF s.provider_id IS DISTINCT FROM NEW.provider_id OR s.capability IS DISTINCT FROM NEW.capability OR g.scope_id IS DISTINCT FROM s.id OR pol.provider_id IS DISTINCT FROM NEW.provider_id OR NEW.mapping_digest IS DISTINCT FROM m.content_digest OR NEW.grant_digest IS DISTINCT FROM g.content_digest OR NEW.policy_digest IS DISTINCT FROM pol.content_digest THEN RAISE EXCEPTION 'Request pinned authority mismatch' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_days' THEN
  SELECT * INTO p FROM market_data_providers WHERE owner_id=NEW.owner_id AND id=NEW.provider_id;
  IF p.id IS NULL OR p.key NOT IN ('alpha_vantage','ecb') OR NEW.charged_attempts>(CASE WHEN p.key='ecb' THEN 24 ELSE 25 END) THEN RAISE EXCEPTION 'Provider daily cap exceeded' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.charged_attempts<>0 THEN RAISE EXCEPTION 'Daily allowance starts empty' USING ERRCODE='23514'; END IF;
  ELSE
   IF (to_jsonb(NEW)-'charged_attempts') IS DISTINCT FROM (to_jsonb(OLD)-'charged_attempts') OR NEW.charged_attempts<>OLD.charged_attempts+1 THEN RAISE EXCEPTION 'Quota reservation cannot be refunded or reset' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_attempts' THEN
  SELECT * INTO r FROM provider_acquisition_requests WHERE owner_id=NEW.owner_id AND id=NEW.request_id;
  IF r.id IS NULL OR (NEW.provider_id,NEW.request_digest,NEW.first_started_at,NEW.deadline) IS DISTINCT FROM (r.provider_id,r.request_digest,r.first_started_at,r.deadline) THEN RAISE EXCEPTION 'Attempt request mismatch' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' THEN
   IF OLD.finished_at IS NOT NULL OR (to_jsonb(NEW)-ARRAY['finished_at','outcome','retry_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['finished_at','outcome','retry_at']) OR NEW.finished_at IS NULL THEN RAISE EXCEPTION 'Attempt completion is immutable' USING ERRCODE='23514'; END IF;
   IF NOT EXISTS(SELECT 1 FROM provider_acquisition_slots WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND attempt_id=NEW.id) THEN RAISE EXCEPTION 'Attempt completion fence lost' USING ERRCODE='23514'; END IF;
   IF NEW.outcome IS NULL AND (NEW.finished_at>=NEW.lease_expires_at OR clock_timestamp()>=NEW.lease_expires_at) THEN RAISE EXCEPTION 'Expired attempt cannot succeed' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.ordinal<>r.attempt_count OR NEW.finished_at IS NOT NULL OR r.state<>'inflight' OR NEW.reserved_at>=r.deadline OR NEW.reserved_at>clock_timestamp() THEN RAISE EXCEPTION 'Attempt reservation invalid' USING ERRCODE='23514'; END IF;
   SELECT * INTO d FROM provider_acquisition_days WHERE owner_id=NEW.owner_id AND id=NEW.day_id;
   IF d.id IS NULL OR d.provider_id<>NEW.provider_id OR d.utc_day<>(NEW.reserved_at AT TIME ZONE 'UTC')::date THEN RAISE EXCEPTION 'Attempt daily charge mismatch' USING ERRCODE='23514'; END IF;
   SELECT * INTO g FROM provider_capability_grants WHERE owner_id=NEW.owner_id AND id=r.grant_id;
   SELECT * INTO cg FROM provider_capability_grants WHERE owner_id=NEW.owner_id AND scope_id=g.scope_id AND effective_at<=clock_timestamp() ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
   SELECT * INTO pol FROM provider_acquisition_policies WHERE owner_id=NEW.owner_id AND id=r.policy_version_id;
   SELECT * INTO cp FROM provider_acquisition_policies WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND effective_at<=clock_timestamp() ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
   SELECT * INTO original_l FROM provider_license_versions WHERE owner_id=NEW.owner_id AND id=g.license_version_id;
   SELECT * INTO current_l FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND effective_at<=clock_timestamp() ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
   IF original_l.id IS NULL OR current_l.id IS NULL OR cg.license_version_id IS DISTINCT FROM current_l.id
    OR original_l.provider_id<>NEW.provider_id OR original_l.effective_at>NEW.reserved_at
    OR original_l.store_permission<>'allowed' OR original_l.display_permission<>'allowed'
    OR current_l.store_permission<>'allowed' OR current_l.display_permission<>'allowed'
    OR original_l.retention_days IS NULL OR current_l.retention_days IS NULL
    OR least(original_l.retention_days,current_l.retention_days)<1
   THEN RAISE EXCEPTION 'Actual original and current licence unavailable' USING ERRCODE='23514'; END IF;
   IF cg.id IS NULL OR cp.id IS NULL OR g.effective_at>NEW.reserved_at OR pol.effective_at>NEW.reserved_at OR NOT g.store_allowed OR NOT g.display_allowed OR NOT cg.store_allowed OR NOT cg.display_allowed OR NOT pol.enabled OR NOT cp.enabled OR least(g.expires_at,cg.expires_at,pol.expires_at,cp.expires_at)<=clock_timestamp() OR d.charged_attempts>least(g.daily_allowance,cg.daily_allowance,pol.daily_allowance,cp.daily_allowance) THEN RAISE EXCEPTION 'Actual licensed allowance unavailable' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_slots' THEN
  IF TG_OP='UPDATE' THEN
   IF (to_jsonb(NEW)-'attempt_id') IS DISTINCT FROM (to_jsonb(OLD)-'attempt_id') THEN RAISE EXCEPTION 'Provider slot identity changed' USING ERRCODE='23514'; END IF;
   IF OLD.attempt_id IS NOT NULL THEN
    IF NOT EXISTS(SELECT 1 FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND id=OLD.attempt_id AND finished_at IS NOT NULL) THEN RAISE EXCEPTION 'Active attempt cannot be released' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
  IF NEW.attempt_id IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND id=NEW.attempt_id AND provider_id=NEW.provider_id AND finished_at IS NULL) THEN RAISE EXCEPTION 'Slot attempt mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='provider_acquisition_publications' THEN
  SELECT * INTO a FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND id=NEW.attempt_id;
  IF a.id IS NULL OR a.finished_at IS NULL OR a.outcome IS NOT NULL OR (NEW.acquired_at<a.reserved_at OR NEW.acquired_at>a.finished_at) THEN RAISE EXCEPTION 'Publication needs successful exact acquisition' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION acquisition_request_complete(target_owner uuid,target_request uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r provider_acquisition_requests; a provider_acquisition_attempts; n integer;
BEGIN
 SELECT * INTO r FROM provider_acquisition_requests WHERE owner_id=target_owner AND id=target_request;
 IF r.id IS NULL THEN RETURN; END IF;
 SELECT count(*) INTO n FROM (SELECT id FROM provider_acquisition_attempts WHERE owner_id=target_owner AND request_id=target_request LIMIT 4) q;
 IF n<>r.attempt_count THEN RAISE EXCEPTION 'Request attempt registration incomplete' USING ERRCODE='23514'; END IF;
 SELECT * INTO a FROM provider_acquisition_attempts WHERE owner_id=target_owner AND request_id=target_request AND ordinal=r.attempt_count;
 IF a.id IS NULL THEN RAISE EXCEPTION 'Request current attempt missing' USING ERRCODE='23514'; END IF;
 IF r.state='inflight' THEN
  IF a.finished_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM provider_acquisition_slots WHERE owner_id=target_owner AND provider_id=r.provider_id AND attempt_id=a.id) THEN RAISE EXCEPTION 'Request inflight fence missing' USING ERRCODE='23514'; END IF;
 ELSE
  IF a.finished_at IS NULL OR EXISTS(SELECT 1 FROM provider_acquisition_slots WHERE owner_id=target_owner AND provider_id=r.provider_id AND attempt_id=a.id) THEN RAISE EXCEPTION 'Request completion incomplete' USING ERRCODE='23514'; END IF;
  IF (r.state='succeeded') IS DISTINCT FROM (a.outcome IS NULL) OR r.retry_at IS DISTINCT FROM a.retry_at OR (r.state='retry') IS DISTINCT FROM (a.retry_at IS NOT NULL) THEN RAISE EXCEPTION 'Request outcome mismatch' USING ERRCODE='23514'; END IF;
 END IF;
END $$;

CREATE FUNCTION acquisition_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_day uuid; d provider_acquisition_days; n integer; previous_request uuid;
BEGIN
 IF TG_TABLE_NAME='provider_acquisition_requests' THEN
  PERFORM acquisition_request_complete(NEW.owner_id,NEW.id);
 ELSIF TG_TABLE_NAME='provider_acquisition_attempts' THEN
  PERFORM acquisition_request_complete(NEW.owner_id,NEW.request_id); target_day:=NEW.day_id;
 ELSIF TG_TABLE_NAME='provider_acquisition_days' THEN target_day:=NEW.id;
 ELSIF TG_TABLE_NAME='provider_acquisition_slots' THEN
  IF NEW.attempt_id IS NOT NULL THEN
   SELECT request_id INTO previous_request FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND id=NEW.attempt_id;
   PERFORM acquisition_request_complete(NEW.owner_id,previous_request);
  END IF;
  IF TG_OP='UPDATE' THEN
   IF OLD.attempt_id IS NOT NULL THEN
    SELECT request_id INTO previous_request FROM provider_acquisition_attempts WHERE owner_id=OLD.owner_id AND id=OLD.attempt_id;
    PERFORM acquisition_request_complete(OLD.owner_id,previous_request);
   END IF;
  END IF;
 END IF;
 IF target_day IS NOT NULL THEN
  SELECT * INTO d FROM provider_acquisition_days WHERE owner_id=NEW.owner_id AND id=target_day;
  SELECT count(*) INTO n FROM (SELECT id FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND day_id=target_day LIMIT 26) q;
  IF n<>d.charged_attempts THEN RAISE EXCEPTION 'Every reservation must consume exactly one durable daily charge' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
"""

_TABLES = (
    "provider_capability_scopes",
    "provider_capability_grants",
    "provider_acquisition_policies",
    "provider_acquisition_mappings",
    "provider_acquisition_requests",
    "provider_acquisition_days",
    "provider_acquisition_attempts",
    "provider_acquisition_slots",
    "provider_acquisition_publications",
)
for _table in _TABLES:
    _GUARDS += f"\nCREATE TRIGGER acquisition_owned BEFORE INSERT OR UPDATE OR DELETE ON {_table} FOR EACH ROW EXECUTE FUNCTION acquisition_owned_guard();"
for _table in (
    "provider_acquisition_requests",
    "provider_acquisition_days",
    "provider_acquisition_attempts",
    "provider_acquisition_slots",
):
    _GUARDS += f"\nCREATE CONSTRAINT TRIGGER acquisition_complete AFTER INSERT OR UPDATE ON {_table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION acquisition_complete_guard();"
_DROP_GUARDS = "\n".join(f"DROP TRIGGER acquisition_owned ON {table};" for table in _TABLES)
_DROP_GUARDS += "\n" + "\n".join(
    f"DROP TRIGGER acquisition_complete ON {table};"
    for table in (
        "provider_acquisition_requests",
        "provider_acquisition_days",
        "provider_acquisition_attempts",
        "provider_acquisition_slots",
    )
)
_DROP_GUARDS += "\nDROP FUNCTION acquisition_complete_guard();\nDROP FUNCTION acquisition_request_complete(uuid,uuid);\nDROP FUNCTION acquisition_owned_guard();"

_ACQUISITION_SOURCE_GUARD = r"""
CREATE FUNCTION acquisition_source_restricted(p_owner uuid,p_kind text,p_source uuid,p_at timestamptz,p_use text DEFAULT 'store')
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE h record; pub provider_acquisition_publications; a provider_acquisition_attempts;
 r provider_acquisition_requests; g provider_capability_grants; current_g provider_capability_grants;
 l provider_license_versions; current_l provider_license_versions; s provider_capability_scopes;
 p market_data_providers; m provider_acquisition_mappings; series market_source_series;
 original_at timestamptz; original_expiry timestamptz; allowed boolean;
BEGIN
 IF p_use IS NULL OR p_use NOT IN ('store','display','report','export') THEN RETURN true; END IF;
 IF p_kind='price' THEN
  SELECT owner_id,provider_id,license_version_id,content_digest,first_observed_at AS first_known_at,
   expires_at,adapter_version,series_id INTO h FROM price_snapshots WHERE owner_id=p_owner AND id=p_source;
 ELSIF p_kind='fx' THEN
  SELECT owner_id,provider_id,license_version_id,content_digest,first_observed_at AS first_known_at,
   expires_at,adapter_version INTO h FROM fx_snapshots WHERE owner_id=p_owner AND id=p_source;
 ELSIF p_kind='research' THEN
  SELECT owner_id,provider_id,license_version_id,content_digest,first_known_at,effective_expires_at AS expires_at,
   adapter_version,origin_id,capability_grant_id,capability_grant_digest,entity_id,capability INTO h
   FROM research_source_versions WHERE owner_id=p_owner AND id=p_source;
 ELSE RETURN true;
 END IF;
 IF h.owner_id IS NULL THEN RETURN true; END IF;
 IF h.adapter_version<>'premium_fixed_get_v1' THEN RETURN false; END IF;
 SELECT * INTO pub FROM provider_acquisition_publications WHERE owner_id=p_owner AND source_kind=p_kind AND source_id=p_source;
 IF pub.id IS NULL OR pub.content_digest<>h.content_digest OR pub.first_known_at<>h.first_known_at OR h.expires_at>pub.expires_at OR h.expires_at<=p_at THEN RETURN true; END IF;
 SELECT * INTO a FROM provider_acquisition_attempts WHERE owner_id=p_owner AND id=pub.attempt_id;
 IF a.id IS NULL OR a.finished_at IS NULL OR a.outcome IS NOT NULL OR pub.acquired_at<a.reserved_at OR pub.acquired_at>a.finished_at OR a.finished_at>=a.deadline THEN RETURN true; END IF;
 SELECT * INTO r FROM provider_acquisition_requests WHERE owner_id=p_owner AND id=a.request_id;
 IF r.id IS NULL OR r.state<>'succeeded' OR r.provider_id<>h.provider_id THEN RETURN true; END IF;
 SELECT * INTO g FROM provider_capability_grants WHERE owner_id=p_owner AND id=r.grant_id;
 IF g.id IS NULL OR g.provider_id<>h.provider_id OR g.license_version_id<>h.license_version_id OR g.content_digest<>r.grant_digest THEN RETURN true; END IF;
 SELECT * INTO s FROM provider_capability_scopes WHERE owner_id=p_owner AND id=g.scope_id;
 IF s.id IS NULL OR s.capability<>r.capability OR (p_kind='price' AND s.capability<>'daily_adjusted') OR (p_kind='fx' AND s.capability<>'reference_fx') OR (p_kind='research' AND s.capability NOT IN ('news_sentiment','company_overview')) THEN RETURN true; END IF;
 IF p_kind='price' THEN
  SELECT * INTO m FROM provider_acquisition_mappings WHERE owner_id=p_owner AND id=r.mapping_version_id;
  SELECT * INTO series FROM market_source_series WHERE owner_id=p_owner AND id=h.series_id;
  IF m.id IS NULL OR series.id IS NULL OR m.content_digest<>r.mapping_digest
   OR m.scope_id<>s.id OR m.source_series_id IS DISTINCT FROM series.id
   OR m.market_mapping_id IS DISTINCT FROM series.mapping_id
   OR m.calendar_id IS DISTINCT FROM series.calendar_id OR series.basis<>'raw_close'
   OR series.instrument_id IS DISTINCT FROM s.subject_id OR series.provider_id<>h.provider_id
   OR series.license_version_id<>h.license_version_id THEN RETURN true; END IF;
 ELSIF p_kind='research' THEN
  IF h.entity_id IS DISTINCT FROM s.subject_id
   OR h.capability<>(CASE s.capability WHEN 'news_sentiment' THEN 'news' ELSE 'company_overview' END)
  THEN RETURN true; END IF;
 END IF;
 SELECT * INTO current_g FROM provider_capability_grants WHERE owner_id=p_owner AND scope_id=g.scope_id AND effective_at<=p_at ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 SELECT * INTO l FROM provider_license_versions WHERE owner_id=p_owner AND id=g.license_version_id;
 SELECT * INTO current_l FROM provider_license_versions WHERE owner_id=p_owner AND provider_id=h.provider_id AND effective_at<=p_at ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
 SELECT * INTO p FROM market_data_providers WHERE owner_id=p_owner AND id=h.provider_id;
 IF current_g.id IS NULL OR l.id IS NULL OR current_l.id IS NULL OR p.id IS NULL OR p.configuration_state<>'configured' OR p.key NOT IN ('alpha_vantage','ecb') OR current_g.license_version_id<>current_l.id OR g.effective_at>pub.acquired_at OR l.effective_at>pub.acquired_at OR least(g.expires_at,current_g.expires_at)<=p_at OR NOT g.store_allowed OR NOT g.display_allowed OR NOT current_g.store_allowed OR NOT current_g.display_allowed OR l.store_permission<>'allowed' OR l.display_permission<>'allowed' OR current_l.store_permission<>'allowed' OR current_l.display_permission<>'allowed' OR l.retention_days IS NULL OR current_l.retention_days IS NULL THEN RETURN true; END IF;
 original_at:=pub.acquired_at; original_expiry:=pub.expires_at;
 IF p_kind='research' THEN
  IF h.capability_grant_id<>g.id OR h.capability_grant_digest<>g.content_digest THEN RETURN true; END IF;
  SELECT original_retained_at,expires_at INTO original_at,original_expiry FROM research_source_origins WHERE owner_id=p_owner AND id=h.origin_id;
  IF original_at IS NULL THEN RETURN true; END IF;
 END IF;
 IF h.expires_at>least(pub.expires_at,original_expiry,g.expires_at,current_g.expires_at,
   original_at+make_interval(days=>least(30,l.retention_days,current_l.retention_days))) THEN RETURN true; END IF;
 allowed:=CASE p_use WHEN 'report' THEN g.report_allowed AND current_g.report_allowed AND l.report_permission='allowed' AND current_l.report_permission='allowed'
  WHEN 'export' THEN g.export_allowed AND current_g.export_allowed AND l.export_permission='allowed' AND current_l.export_permission='allowed' ELSE true END;
 RETURN NOT allowed;
END $$;

CREATE FUNCTION acquisition_publication_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE k text; sid uuid; acquired record;
BEGIN
 IF TG_TABLE_NAME='provider_acquisition_publications' THEN
  k:=NEW.source_kind; sid:=NEW.source_id;
 ELSE
  IF NEW.adapter_version<>'premium_fixed_get_v1' THEN RETURN NULL; END IF;
  k:=CASE TG_TABLE_NAME WHEN 'price_snapshots' THEN 'price' WHEN 'fx_snapshots' THEN 'fx' ELSE 'research' END;
  sid:=NEW.id;
 END IF;
 IF acquisition_source_restricted(NEW.owner_id,k,sid,clock_timestamp(),'store') THEN
  RAISE EXCEPTION 'Canonical acquisition publication lacks original authority or clocks' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER acquisition_publication_complete AFTER INSERT ON provider_acquisition_publications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION acquisition_publication_complete();
CREATE CONSTRAINT TRIGGER acquisition_publication_complete AFTER INSERT ON price_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION acquisition_publication_complete();
CREATE CONSTRAINT TRIGGER acquisition_publication_complete AFTER INSERT ON fx_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION acquisition_publication_complete();
CREATE CONSTRAINT TRIGGER acquisition_publication_complete AFTER INSERT ON research_source_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION acquisition_publication_complete();
"""
_GUARDS += _ACQUISITION_SOURCE_GUARD
_DROP_GUARDS = (
    "\n".join(
        f"DROP TRIGGER acquisition_publication_complete ON {table};"
        for table in (
            "provider_acquisition_publications",
            "price_snapshots",
            "fx_snapshots",
            "research_source_versions",
        )
    )
    + "\nDROP FUNCTION acquisition_publication_complete();\nDROP FUNCTION acquisition_source_restricted(uuid,text,uuid,timestamptz,text);\n"
    + _DROP_GUARDS
)


_MARKET_RESULT_GUARD = r"""
CREATE FUNCTION acquisition_market_result_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a provider_acquisition_attempts; r provider_acquisition_requests;
 pub provider_acquisition_publications; original_attempt provider_acquisition_attempts;
 original_request provider_acquisition_requests; m provider_acquisition_mappings;
 g provider_capability_grants; s provider_capability_scopes; h record;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Acquisition market results are immutable' USING ERRCODE='23514';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('sources:'||NEW.owner_id::text,0));
 SELECT * INTO a FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND id=NEW.attempt_id;
 SELECT * INTO r FROM provider_acquisition_requests WHERE owner_id=NEW.owner_id AND id=a.request_id;
 SELECT * INTO pub FROM provider_acquisition_publications WHERE owner_id=NEW.owner_id AND id=NEW.publication_id;
 SELECT * INTO original_attempt FROM provider_acquisition_attempts WHERE owner_id=NEW.owner_id AND id=pub.attempt_id;
 SELECT * INTO original_request FROM provider_acquisition_requests WHERE owner_id=NEW.owner_id AND id=original_attempt.request_id;
 IF a.id IS NULL OR r.id IS NULL OR pub.id IS NULL OR original_request.id IS NULL
  OR a.finished_at IS NULL OR a.outcome IS NOT NULL OR r.state<>'succeeded'
  OR a.finished_at>=a.deadline OR NEW.observed_at<a.reserved_at OR NEW.observed_at>a.finished_at
  OR NEW.created_at<NEW.observed_at OR pub.acquired_at>NEW.observed_at
  OR (r.provider_id,r.capability) IS DISTINCT FROM (original_request.provider_id,original_request.capability)
  OR pub.source_kind NOT IN ('price','fx') THEN
  RAISE EXCEPTION 'Market result requires a successful matching acquisition' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM broker_accounts b JOIN broker_connections c ON c.id=b.connection_id
   WHERE b.id=r.account_id AND c.owner_id=NEW.owner_id AND b.status='active' AND c.status='active')
  OR NOT EXISTS(SELECT 1 FROM principals WHERE owner_id=NEW.owner_id AND id=r.principal_id AND status='active')
  OR EXISTS(SELECT 1 FROM unnest(ARRAY['portfolio:read','analytics:read','targets:write']) required(scope)
    WHERE NOT EXISTS(SELECT 1 FROM principal_scope_grants granted WHERE granted.principal_id=r.principal_id
      AND granted.scope=required.scope AND granted.granted_at<=clock_timestamp() AND granted.revoked_at IS NULL
      AND (granted.expires_at IS NULL OR granted.expires_at>clock_timestamp()))) THEN
  RAISE EXCEPTION 'Market result current account authority missing' USING ERRCODE='23514';
 END IF;
 SELECT * INTO m FROM provider_acquisition_mappings WHERE owner_id=NEW.owner_id AND id=r.mapping_version_id;
 SELECT * INTO g FROM provider_capability_grants WHERE owner_id=NEW.owner_id AND id=r.grant_id;
 SELECT * INTO s FROM provider_capability_scopes WHERE owner_id=NEW.owner_id AND id=g.scope_id;
 IF pub.source_kind='price' THEN
  SELECT p.owner_id,p.provider_id,p.license_version_id,p.content_digest,p.source_revision,p.series_id,series.calendar_id
   INTO h FROM price_snapshots p JOIN market_source_series series ON series.owner_id=p.owner_id AND series.id=p.series_id
   WHERE p.owner_id=NEW.owner_id AND p.id=pub.source_id;
 ELSE
  SELECT owner_id,provider_id,license_version_id,content_digest,source_revision,NULL::uuid AS series_id,calendar_id
   INTO h FROM fx_snapshots WHERE owner_id=NEW.owner_id AND id=pub.source_id;
 END IF;
 IF h.owner_id IS NULL OR m.id IS NULL OR g.id IS NULL OR s.id IS NULL
  OR h.provider_id<>r.provider_id OR h.license_version_id<>g.license_version_id
  OR h.content_digest<>pub.content_digest OR h.source_revision IS DISTINCT FROM pub.acquisition_digest
  OR m.scope_id<>s.id OR s.capability<>r.capability OR g.provider_id<>r.provider_id
  OR m.calendar_id IS DISTINCT FROM h.calendar_id
  OR (pub.source_kind='price' AND (r.capability<>'daily_adjusted' OR m.source_series_id IS DISTINCT FROM h.series_id))
  OR (pub.source_kind='fx' AND (r.capability<>'reference_fx' OR m.source_series_id IS NOT NULL))
  OR g.effective_at>NEW.observed_at OR g.expires_at<=clock_timestamp()
  OR NOT g.store_allowed OR NOT g.display_allowed
  OR EXISTS(SELECT 1 FROM source_retention_work w WHERE w.owner_id=NEW.owner_id
    AND ((pub.source_kind='price' AND w.price_snapshot_id=pub.source_id)
      OR (pub.source_kind='fx' AND w.fx_snapshot_id=pub.source_id)))
  OR acquisition_source_restricted(NEW.owner_id,pub.source_kind,pub.source_id,clock_timestamp(),'store')
  OR acquisition_source_restricted(NEW.owner_id,pub.source_kind,pub.source_id,clock_timestamp(),'display') THEN
  RAISE EXCEPTION 'Market result must retain exact original source authority' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER acquisition_market_result BEFORE INSERT OR UPDATE OR DELETE
 ON provider_acquisition_market_results FOR EACH ROW EXECUTE FUNCTION acquisition_market_result_guard();
"""
_GUARDS += _MARKET_RESULT_GUARD
_DROP_GUARDS = (
    "DROP TRIGGER acquisition_market_result ON provider_acquisition_market_results;\n"
    "DROP FUNCTION acquisition_market_result_guard();\n" + _DROP_GUARDS
)
