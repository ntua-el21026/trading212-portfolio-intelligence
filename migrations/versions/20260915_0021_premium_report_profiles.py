"""Explicit third report document profile and immutable scenario source lineage.

Revision ID: 20260915_0021
Revises: 20260915_0020

No retained document bytes are rewritten. Profile-two guard SQL is frozen below;
new checks are selected only by the explicit third normalized contract version.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0021"
down_revision = "20260915_0020"
branch_labels = None
depends_on = None

_BASIS_COLUMNS = (
    "result_id",
    "definition_version_id",
    "definition_digest",
    "snapshot_id",
    "snapshot_digest",
    "reporting_currency",
    "source_cutoff_at",
    "valuation_at",
)
_SCENARIO_COPY_TABLES = (
    "scenario_run_payloads",
    "scenario_results",
    "scenario_components",
    "scenario_applied_sensitivities",
)


def _check(table: str, name: str, value: str) -> None:
    constraint = op.f("ck_" + table + "_" + name)
    op.drop_constraint(constraint, table, type_="check")
    op.create_check_constraint(constraint, table, value)


def upgrade() -> None:
    _check(
        "report_input_snapshots",
        "contract_version_allowed",
        "contract_version IN (1,2,3) AND (kind='report' OR contract_version=1)",
    )
    _check("report_jobs", "contract_version_allowed", "contract_version IN (1,2,3)")
    _check("report_input_premium_dependencies", "kind_allowed", "kind IN ('risk','scenario')")
    for name in _BASIS_COLUMNS:
        kind = (
            sa.Uuid()
            if name.endswith("_id")
            else sa.DateTime(timezone=True)
            if name.endswith("_at")
            else sa.String(3 if name == "reporting_currency" else 64)
        )
        op.add_column("report_input_premium_dependencies", sa.Column(name, kind, nullable=True))
    op.create_foreign_key(
        "fk_report_premium_snapshot",
        "report_input_premium_dependencies",
        "portfolio_snapshots",
        ["snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "premium_basis_complete",
        "report_input_premium_dependencies",
        "num_nonnulls(result_id,definition_version_id,definition_digest,snapshot_id,snapshot_digest,reporting_currency,source_cutoff_at,valuation_at) IN (0,8)",
    )
    op.create_check_constraint(
        "premium_basis_format",
        "report_input_premium_dependencies",
        "(definition_digest IS NULL OR definition_digest ~ '^[0-9a-f]{64}$') AND (snapshot_digest IS NULL OR snapshot_digest ~ '^[0-9a-f]{64}$') AND (reporting_currency IS NULL OR reporting_currency ~ '^[A-Z]{3}$')",
    )
    op.execute(_V2_RESTRICTION)
    op.execute(_V3_HELPERS)
    op.execute(_GUARDS)
    for table in _SCENARIO_COPY_TABLES:
        op.execute(
            f"CREATE TRIGGER reports_premium_copy_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION report_premium_copy_guard()"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM report_input_snapshots WHERE contract_version=3)
        OR EXISTS(SELECT 1 FROM report_jobs WHERE contract_version=3)
        OR EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE kind='scenario' OR result_id IS NOT NULL)
      THEN RAISE EXCEPTION 'Third-profile reports must be absent before downgrade' USING ERRCODE='23514'; END IF;
    END $$""")
    for table in _SCENARIO_COPY_TABLES:
        op.execute(f"DROP TRIGGER reports_premium_copy_guard ON {table}")
    op.execute(_PREVIOUS_GUARDS.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"))
    op.execute(_PREVIOUS_SOURCE_PENDING)
    for signature in (
        "report_premium_v3_basis_valid(report_input_premium_dependencies,report_input_snapshots)",
        "report_premium_v3_sources_restricted(uuid,uuid,uuid,text,timestamptz)",
        "report_premium_license_restricted(uuid,uuid,uuid,timestamptz,timestamptz,timestamptz)",
        "report_premium_restricted_v2(uuid,uuid,timestamptz)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    for name in ("premium_basis_complete", "premium_basis_format"):
        op.drop_constraint(
            op.f("ck_report_input_premium_dependencies_" + name),
            "report_input_premium_dependencies",
            type_="check",
        )
    op.drop_constraint(
        "fk_report_premium_snapshot", "report_input_premium_dependencies", type_="foreignkey"
    )
    for name in reversed(_BASIS_COLUMNS):
        op.drop_column("report_input_premium_dependencies", name)
    _check("report_input_premium_dependencies", "kind_allowed", "kind='risk'")
    _check("report_jobs", "contract_version_allowed", "contract_version IN (1,2)")
    _check(
        "report_input_snapshots",
        "contract_version_allowed",
        "contract_version IN (1,2) AND (kind='report' OR contract_version=1)",
    )


_PREVIOUS_GUARDS = r"""
CREATE FUNCTION report_premium_restricted(p_owner uuid, p_input uuid, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE WHEN i.contract_version=1 THEN false ELSE
   (SELECT count(*) FROM report_input_premium_dependencies d
      WHERE d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id)<>1
   OR EXISTS (
    SELECT 1 FROM report_input_premium_dependencies d
    LEFT JOIN premium_runs r ON r.owner_id=d.owner_id AND r.account_id=d.account_id AND r.id=d.run_id
    LEFT JOIN risk_runs rr ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
    LEFT JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
    LEFT JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
    WHERE d.owner_id=i.owner_id AND d.input_id=i.id AND (
      d.kind IS DISTINCT FROM 'risk' OR r.kind IS DISTINCT FROM 'risk'
      OR rr.sealed IS DISTINCT FROM true OR result.sealed IS DISTINCT FROM true
      OR j.state IS DISTINCT FROM 'succeeded'
      OR d.input_digest IS DISTINCT FROM r.input_digest
      OR d.result_digest IS DISTINCT FROM result.content_digest
      OR d.expires_at>r.expires_at OR d.expires_at<=d.created_at
      OR d.expires_at<=p_at OR r.expires_at<=p_at
      OR EXISTS (SELECT 1 FROM premium_retention_events e
          WHERE e.owner_id=d.owner_id AND e.run_id=d.run_id)
      OR EXISTS (
        SELECT 1 FROM premium_run_licenses lineage
        LEFT JOIN provider_license_versions pinned ON pinned.owner_id=lineage.owner_id
          AND pinned.provider_id=lineage.provider_id AND pinned.id=lineage.license_version_id
        LEFT JOIN LATERAL (
          SELECT l.id,l.store_permission,l.display_permission,l.report_permission,l.retention_days
          FROM provider_license_versions l WHERE l.owner_id=lineage.owner_id
            AND l.provider_id=lineage.provider_id AND l.effective_at<=p_at
          ORDER BY l.effective_at DESC,l.version_number DESC,l.id DESC LIMIT 1
        ) current_license ON true
        WHERE lineage.owner_id=d.owner_id AND lineage.account_id=d.account_id AND lineage.run_id=d.run_id
          AND (pinned.id IS NULL OR current_license.id IS NULL
            OR pinned.store_permission IS DISTINCT FROM 'allowed'
            OR pinned.display_permission IS DISTINCT FROM 'allowed'
            OR pinned.report_permission IS DISTINCT FROM 'allowed'
            OR current_license.store_permission IS DISTINCT FROM 'allowed'
            OR current_license.display_permission IS DISTINCT FROM 'allowed'
            OR current_license.report_permission IS DISTINCT FROM 'allowed'
            OR pinned.retention_days IS NULL OR current_license.retention_days IS NULL
            OR r.created_at+LEAST(pinned.retention_days,current_license.retention_days)*INTERVAL '1 day'<=p_at)
      )
    )
   ) END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

CREATE FUNCTION report_premium_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; sealed timestamptz; purged timestamptz;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Premium report lineage is immutable' USING ERRCODE='23514'; END IF;
 PERFORM id FROM premium_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id
   AND id=NEW.run_id FOR UPDATE;
 SELECT contract_version,sealed_at,purged_at INTO version,sealed,purged
   FROM report_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id
     AND account_id=NEW.account_id FOR UPDATE;
 IF version IS DISTINCT FROM 2 OR sealed IS NOT NULL OR purged IS NOT NULL THEN
   RAISE EXCEPTION 'Premium report capture is not open' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS (
   SELECT 1 FROM premium_runs r JOIN risk_runs rr
     ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
   JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
   JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
   WHERE r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id AND r.id=NEW.run_id
     AND r.kind=NEW.kind AND rr.sealed AND result.sealed AND j.state='succeeded'
     AND r.input_digest=NEW.input_digest AND result.content_digest=NEW.result_digest
     AND NEW.expires_at<=r.expires_at AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
     AND NOT EXISTS (SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
 ) THEN RAISE EXCEPTION 'Premium report source binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged
   FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies
   WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF (version=1 AND dependencies<>0) OR (version=2 AND dependencies<>1) THEN
   RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version=2 AND (EXISTS (SELECT 1 FROM report_input_premium_dependencies
     WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
   RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_command_contract_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer;
BEGIN
 IF NEW.command NOT IN ('reports.generate.v1','reports.generate.v2') THEN RETURN NEW; END IF;
 SELECT contract_version INTO version FROM report_jobs
   WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.report_job_id;
 IF version IS DISTINCT FROM (CASE NEW.command WHEN 'reports.generate.v1' THEN 1 ELSE 2 END) THEN
   RAISE EXCEPTION 'Report command contract mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_premium_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; run uuid;
BEGIN
 IF TG_TABLE_NAME='premium_retention_events' THEN
   owner:=NEW.owner_id; run:=NEW.run_id;
   PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
   IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
   IF TG_OP='UPDATE' AND NEW.retained_bytes>=OLD.retained_bytes AND NEW.reserved_bytes>=OLD.reserved_bytes THEN RETURN NEW; END IF;
   owner:=OLD.owner_id; run:=OLD.id;
 ELSIF TG_TABLE_NAME IN ('risk_run_assets','risk_results') THEN
   owner:=OLD.owner_id; run:=OLD.run_id;
 ELSE
   owner:=OLD.owner_id;
   SELECT run_id INTO run FROM risk_results WHERE owner_id=owner AND id=OLD.result_id;
 END IF;
 PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
 IF EXISTS (SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=owner
     AND d.run_id=run AND report_capture_pending(d.owner_id,d.input_id)) THEN
   RAISE EXCEPTION 'Premium report copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
"""

_V2_RESTRICTION = r"""
CREATE FUNCTION report_premium_restricted_v2(p_owner uuid, p_input uuid, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE WHEN i.contract_version=1 THEN false ELSE
   (SELECT count(*) FROM report_input_premium_dependencies d
      WHERE d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id)<>1
   OR EXISTS (
    SELECT 1 FROM report_input_premium_dependencies d
    LEFT JOIN premium_runs r ON r.owner_id=d.owner_id AND r.account_id=d.account_id AND r.id=d.run_id
    LEFT JOIN risk_runs rr ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
    LEFT JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
    LEFT JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
    WHERE d.owner_id=i.owner_id AND d.input_id=i.id AND (
      d.kind IS DISTINCT FROM 'risk' OR r.kind IS DISTINCT FROM 'risk'
      OR rr.sealed IS DISTINCT FROM true OR result.sealed IS DISTINCT FROM true
      OR j.state IS DISTINCT FROM 'succeeded'
      OR d.input_digest IS DISTINCT FROM r.input_digest
      OR d.result_digest IS DISTINCT FROM result.content_digest
      OR d.expires_at>r.expires_at OR d.expires_at<=d.created_at
      OR d.expires_at<=p_at OR r.expires_at<=p_at
      OR EXISTS (SELECT 1 FROM premium_retention_events e
          WHERE e.owner_id=d.owner_id AND e.run_id=d.run_id)
      OR EXISTS (
        SELECT 1 FROM premium_run_licenses lineage
        LEFT JOIN provider_license_versions pinned ON pinned.owner_id=lineage.owner_id
          AND pinned.provider_id=lineage.provider_id AND pinned.id=lineage.license_version_id
        LEFT JOIN LATERAL (
          SELECT l.id,l.store_permission,l.display_permission,l.report_permission,l.retention_days
          FROM provider_license_versions l WHERE l.owner_id=lineage.owner_id
            AND l.provider_id=lineage.provider_id AND l.effective_at<=p_at
          ORDER BY l.effective_at DESC,l.version_number DESC,l.id DESC LIMIT 1
        ) current_license ON true
        WHERE lineage.owner_id=d.owner_id AND lineage.account_id=d.account_id AND lineage.run_id=d.run_id
          AND (pinned.id IS NULL OR current_license.id IS NULL
            OR pinned.store_permission IS DISTINCT FROM 'allowed'
            OR pinned.display_permission IS DISTINCT FROM 'allowed'
            OR pinned.report_permission IS DISTINCT FROM 'allowed'
            OR current_license.store_permission IS DISTINCT FROM 'allowed'
            OR current_license.display_permission IS DISTINCT FROM 'allowed'
            OR current_license.report_permission IS DISTINCT FROM 'allowed'
            OR pinned.retention_days IS NULL OR current_license.retention_days IS NULL
            OR r.created_at+LEAST(pinned.retention_days,current_license.retention_days)*INTERVAL '1 day'<=p_at)
      )
    )
   ) END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

"""

_PREVIOUS_SOURCE_PENDING = r"""CREATE OR REPLACE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v
 WHERE v.version_id=p_version AND scenario_run_has_payload(v.run_id))
$$;
"""

_V3_HELPERS = r"""
CREATE FUNCTION report_premium_license_restricted(p_owner uuid, p_provider uuid, p_license uuid, p_created timestamptz, p_expires timestamptz, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT EXISTS (
  SELECT 1 FROM provider_license_versions pinned
  JOIN LATERAL (
   SELECT l.* FROM provider_license_versions l WHERE l.owner_id=p_owner
    AND l.provider_id=p_provider AND l.effective_at<=p_at
   ORDER BY l.effective_at DESC,l.version_number DESC,l.id DESC LIMIT 1
  ) current_license ON true
  WHERE pinned.owner_id=p_owner AND pinned.provider_id=p_provider AND pinned.id=p_license
    AND pinned.effective_at<=p_at
    AND pinned.store_permission='allowed' AND pinned.display_permission='allowed' AND pinned.report_permission='allowed'
    AND current_license.store_permission='allowed' AND current_license.display_permission='allowed' AND current_license.report_permission='allowed'
    AND pinned.retention_days IS NOT NULL AND current_license.retention_days IS NOT NULL
    AND p_expires>p_at AND p_expires<=p_created+LEAST(30,pinned.retention_days,current_license.retention_days)*INTERVAL '1 day'
    AND p_created+LEAST(30,pinned.retention_days,current_license.retention_days)*INTERVAL '1 day'>p_at
 )
$$;

CREATE FUNCTION report_premium_v3_basis_valid(d report_input_premium_dependencies, i report_input_snapshots)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(
  i.contract_version=3 AND i.kind='report' AND d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id
  AND num_nonnulls(d.result_id,d.definition_version_id,d.definition_digest,d.snapshot_id,d.snapshot_digest,d.reporting_currency,d.source_cutoff_at,d.valuation_at)=8
  AND d.snapshot_id=i.snapshot_id AND d.reporting_currency=i.reporting_currency AND d.source_cutoff_at=i.source_cutoff_at AND d.valuation_at=i.valuation_at
  AND EXISTS(SELECT 1 FROM portfolio_snapshots s WHERE s.id=d.snapshot_id AND s.broker_account_id=d.account_id AND s.valuation_at=d.valuation_at)
  AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='snapshot:snapshot' AND p.subject_id=d.snapshot_id AND p.parent_id IS NULL AND p.content_digest=d.snapshot_digest)
  AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind=d.kind||'\:input' AND p.subject_id=d.run_id AND p.parent_id IS NULL AND p.content_digest=d.input_digest)
  AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind=d.kind||'\:result' AND p.subject_id=d.result_id AND p.parent_id=d.run_id AND p.content_digest=d.result_digest)
  AND (SELECT count(*) FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND split_part(p.kind,':',1) IN ('risk','scenario'))=3
  AND (
   (d.kind='scenario' AND EXISTS(
    SELECT 1 FROM premium_runs r
    JOIN scenario_runs s ON s.id=r.id AND s.owner_id=r.owner_id AND s.account_id=r.account_id
    JOIN scenario_results result ON result.run_id=r.id AND result.owner_id=r.owner_id AND result.account_id=r.account_id
    JOIN scenario_definition_versions v ON v.id=s.definition_version_id AND v.owner_id=s.owner_id AND v.account_id=s.account_id
    JOIN premium_jobs j ON j.run_id=r.id AND j.owner_id=r.owner_id AND j.account_id=r.account_id
    JOIN xray_input_snapshots xi ON xi.id=s.xray_input_id AND xi.owner_id=s.owner_id AND xi.account_id=s.account_id
    JOIN xray_runs xr ON xr.id=s.xray_run_id AND xr.owner_id=s.owner_id AND xr.input_id=xi.id
    WHERE r.owner_id=d.owner_id AND r.account_id=d.account_id AND r.id=d.run_id AND r.kind='scenario'
      AND s.sealed AND result.sealed AND j.state='succeeded' AND j.completed_at IS NOT NULL
      AND r.input_digest=d.input_digest AND result.id=d.result_id AND result.content_digest=d.result_digest
      AND s.definition_version_id=d.definition_version_id AND s.definition_digest=d.definition_digest AND v.content_digest=d.definition_digest
      AND s.portfolio_snapshot_id=d.snapshot_id AND s.portfolio_snapshot_digest=d.snapshot_digest
      AND s.reporting_currency=d.reporting_currency AND s.source_cutoff_at=d.source_cutoff_at
      AND xi.valuation_at=d.valuation_at AND xi.input_digest=s.xray_input_digest AND xr.content_digest=s.xray_result_digest
      AND xi.sealed_at IS NOT NULL AND xr.sealed_at IS NOT NULL
      AND (s.historical_input_id IS NULL OR (s.replay_start_date=i.start_date AND s.replay_end_date=i.end_date AND EXISTS(
       SELECT 1 FROM historical_input_snapshots h JOIN report_input_pins p ON p.subject_id=h.id AND p.owner_id=h.owner_id
       WHERE h.id=s.historical_input_id AND h.owner_id=s.owner_id AND h.broker_account_id=s.account_id AND h.sealed
         AND h.input_digest=s.historical_input_digest AND p.input_id=i.id AND p.kind='performance:input' AND p.parent_id IS NULL AND p.content_digest=h.input_digest)))
      AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='scenario:policy' AND p.subject_id=v.id AND p.parent_id=v.definition_id AND p.content_digest=v.content_digest)
      AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='xray:input' AND p.subject_id=xi.id AND p.parent_id IS NULL AND p.content_digest=xi.input_digest)
      AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='xray:result' AND p.subject_id=xr.id AND p.parent_id IS NULL AND p.content_digest=xr.content_digest)
   )) OR (d.kind='risk' AND EXISTS(
    SELECT 1 FROM premium_runs r
    JOIN risk_runs s ON s.id=r.id AND s.owner_id=r.owner_id AND s.account_id=r.account_id
    JOIN risk_results result ON result.run_id=r.id AND result.owner_id=r.owner_id AND result.account_id=r.account_id
    JOIN risk_definition_versions v ON v.id=s.definition_version_id AND v.owner_id=s.owner_id AND v.account_id=s.account_id
    JOIN historical_input_snapshots h ON h.id=s.historical_input_id AND h.owner_id=s.owner_id AND h.broker_account_id=s.account_id
    JOIN premium_jobs j ON j.run_id=r.id AND j.owner_id=r.owner_id AND j.account_id=r.account_id
    WHERE r.owner_id=d.owner_id AND r.account_id=d.account_id AND r.id=d.run_id AND r.kind='risk'
      AND s.sealed AND result.sealed AND j.state='succeeded' AND j.completed_at IS NOT NULL
      AND r.input_digest=d.input_digest AND result.id=d.result_id AND result.content_digest=d.result_digest
      AND v.id=d.definition_version_id AND v.content_digest=d.definition_digest
      AND s.portfolio_snapshot_id=d.snapshot_id AND s.reporting_currency=d.reporting_currency AND s.source_cutoff_at=d.source_cutoff_at
      AND s.window_start_at=(i.start_date::timestamp AT TIME ZONE 'UTC') AND s.window_end_at=((i.end_date+1)::timestamp AT TIME ZONE 'UTC')
      AND h.input_digest=s.historical_input_digest AND h.sealed
      AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='risk:policy' AND p.subject_id=v.id AND p.parent_id=v.definition_id AND p.content_digest=v.content_digest)
      AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='performance:input' AND p.subject_id=h.id AND p.parent_id IS NULL AND p.content_digest=h.input_digest)
      AND (s.xray_run_id IS NULL OR EXISTS(
       SELECT 1 FROM xray_runs xr JOIN xray_input_snapshots xi ON xi.id=xr.input_id AND xi.owner_id=xr.owner_id
       WHERE xr.id=s.xray_run_id AND xr.owner_id=s.owner_id AND xi.account_id=s.account_id AND xr.sealed_at IS NOT NULL AND xi.sealed_at IS NOT NULL
       AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='xray:input' AND p.subject_id=xi.id AND p.parent_id IS NULL AND p.content_digest=xi.input_digest)
       AND EXISTS(SELECT 1 FROM report_input_pins p WHERE p.owner_id=d.owner_id AND p.input_id=d.input_id AND p.kind='xray:result' AND p.subject_id=xr.id AND p.parent_id IS NULL AND p.content_digest=xr.content_digest)))
   ))
  ),false)
$$;

CREATE FUNCTION report_premium_v3_sources_restricted(p_owner uuid, p_input uuid, p_run uuid, p_kind text, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 WITH RECURSIVE parents AS (
  SELECT s.historical_input_id,s.xray_input_id,s.xray_run_id FROM scenario_runs s WHERE p_kind='scenario' AND s.owner_id=p_owner AND s.id=p_run
  UNION ALL SELECT s.historical_input_id,x.input_id,s.xray_run_id FROM risk_runs s LEFT JOIN xray_runs x ON x.id=s.xray_run_id AND x.owner_id=s.owner_id WHERE p_kind='risk' AND s.owner_id=p_owner AND s.id=p_run
 ), history AS (
  SELECT h.* FROM historical_dependencies h JOIN parents p ON h.input_id=p.historical_input_id WHERE h.owner_id=p_owner
  UNION SELECT h.* FROM historical_dependencies h JOIN history prior ON h.evidence_id=prior.registered_evidence_id WHERE h.owner_id=p_owner
 ), physical AS (
  SELECT 'price' AS kind,s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM price_snapshots s JOIN report_input_dependencies d ON d.price_snapshot_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'fx',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM fx_snapshots s JOIN report_input_dependencies d ON d.fx_snapshot_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'benchmark',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM benchmark_snapshots s JOIN report_input_dependencies d ON d.benchmark_snapshot_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'corporate_action',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM corporate_action_snapshots s JOIN report_input_dependencies d ON d.corporate_action_snapshot_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'classification',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM classification_snapshots s JOIN report_input_dependencies d ON d.classification_snapshot_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'constituent',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM constituent_snapshots s JOIN report_input_dependencies d ON d.constituent_snapshot_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'entity_evidence',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM entity_evidence_versions s JOIN report_input_dependencies d ON d.entity_evidence_version_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'fund_definition',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM fund_definitions s JOIN report_input_dependencies d ON d.fund_definition_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
  UNION ALL SELECT 'fund_mapping',s.id,s.owner_id,s.provider_id,s.license_version_id,s.content_digest,s.created_at,s.expires_at FROM fund_source_mappings s JOIN report_input_dependencies d ON d.fund_mapping_id=s.id AND d.owner_id=s.owner_id WHERE d.input_id=p_input AND d.owner_id=p_owner
 ), required_physical AS (
  SELECT unnest(ARRAY[x.fx_snapshot_id,x.entity_evidence_version_id,x.classification_snapshot_id,x.fund_definition_id,x.fund_mapping_id,x.constituent_snapshot_id]) AS id FROM xray_input_dependencies x JOIN parents p ON p.xray_input_id=x.input_id WHERE x.owner_id=p_owner
  UNION SELECT unnest(ARRAY[h.price_snapshot_id,h.fx_snapshot_id,h.action_snapshot_id,h.benchmark_snapshot_id]) FROM history h
 ), source_headers AS (
  SELECT v.owner_id,v.provider_id,v.license_version_id,v.created_at FROM scenario_run_sensitivity_versions c JOIN scenario_sensitivity_versions v ON v.owner_id=c.owner_id AND v.id=c.version_id WHERE c.owner_id=p_owner AND c.run_id=p_run
  UNION ALL SELECT v.owner_id,v.provider_id,v.license_version_id,v.created_at FROM scenario_run_sensitivity_observations c JOIN scenario_sensitivity_observations v ON v.owner_id=c.owner_id AND v.id=c.observation_id WHERE c.owner_id=p_owner AND c.run_id=p_run
  UNION ALL SELECT v.owner_id,v.provider_id,v.license_version_id,v.created_at FROM scenario_run_sensitivity_evidence c JOIN scenario_sensitivity_evidence v ON v.owner_id=c.owner_id AND v.id=c.evidence_id WHERE c.owner_id=p_owner AND c.run_id=p_run
 )
 SELECT
  (SELECT count(*) FROM premium_run_licenses WHERE owner_id=p_owner AND run_id=p_run)>256
  OR (SELECT count(*) FROM report_input_licenses WHERE owner_id=p_owner AND input_id=p_input)>256
  OR EXISTS(SELECT 1 FROM premium_run_licenses l JOIN premium_runs r ON r.id=l.run_id AND r.owner_id=l.owner_id WHERE l.owner_id=p_owner AND l.run_id=p_run AND (
    report_premium_license_restricted(l.owner_id,l.provider_id,l.license_version_id,r.created_at,r.expires_at,p_at)
    OR NOT EXISTS(SELECT 1 FROM report_input_licenses c WHERE c.owner_id=l.owner_id AND c.input_id=p_input AND c.license_version_id=l.license_version_id AND c.provider_id=l.provider_id)))
  OR EXISTS(SELECT 1 FROM report_input_licenses l JOIN report_input_snapshots i ON i.owner_id=l.owner_id AND i.id=l.input_id WHERE l.owner_id=p_owner AND l.input_id=p_input AND report_premium_license_restricted(l.owner_id,l.provider_id,l.license_version_id,i.created_at,i.expires_at,p_at))
  OR EXISTS(SELECT 1 FROM required_physical r WHERE r.id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM physical s WHERE s.id=r.id))
  OR (SELECT count(*) FROM physical)<>(SELECT count(*) FROM report_input_dependencies WHERE owner_id=p_owner AND input_id=p_input)
  OR EXISTS(SELECT 1 FROM physical s JOIN report_input_dependencies d ON d.owner_id=s.owner_id AND d.source_id=s.id AND d.input_id=p_input WHERE
    d.kind IS DISTINCT FROM s.kind OR d.content_digest IS DISTINCT FROM s.content_digest OR d.provider_id IS DISTINCT FROM s.provider_id OR d.license_version_id IS DISTINCT FROM s.license_version_id OR d.expires_at IS DISTINCT FROM s.expires_at
    OR s.expires_at<=p_at OR report_premium_license_restricted(s.owner_id,s.provider_id,s.license_version_id,s.created_at,(SELECT expires_at FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input),p_at))
  OR EXISTS(SELECT 1 FROM report_input_dependencies d WHERE d.owner_id=p_owner AND d.input_id=p_input AND (
    EXISTS(SELECT 1 FROM source_retention_work w WHERE w.owner_id=d.owner_id AND (w.price_snapshot_id=d.price_snapshot_id OR w.fx_snapshot_id=d.fx_snapshot_id OR w.benchmark_snapshot_id=d.benchmark_snapshot_id OR w.corporate_action_snapshot_id=d.corporate_action_snapshot_id OR w.constituent_snapshot_id=d.constituent_snapshot_id))
    OR EXISTS(SELECT 1 FROM source_expiry_events w WHERE w.owner_id=d.owner_id AND (w.price_snapshot_id=d.price_snapshot_id OR w.fx_snapshot_id=d.fx_snapshot_id OR w.benchmark_snapshot_id=d.benchmark_snapshot_id OR w.corporate_action_snapshot_id=d.corporate_action_snapshot_id OR w.constituent_snapshot_id=d.constituent_snapshot_id))
    OR EXISTS(SELECT 1 FROM enrichment_retention_work w WHERE w.owner_id=d.owner_id AND (w.entity_evidence_version_id=d.entity_evidence_version_id OR w.classification_snapshot_id=d.classification_snapshot_id OR w.fund_definition_id=d.fund_definition_id OR w.fund_mapping_id=d.fund_mapping_id))
    OR EXISTS(SELECT 1 FROM enrichment_expiry_events w WHERE w.owner_id=d.owner_id AND (w.entity_evidence_version_id=d.entity_evidence_version_id OR w.classification_snapshot_id=d.classification_snapshot_id OR w.fund_definition_id=d.fund_definition_id OR w.fund_mapping_id=d.fund_mapping_id))))
  OR EXISTS(SELECT 1 FROM parents p WHERE
    (p.xray_input_id IS NOT NULL AND (EXISTS(SELECT 1 FROM xray_retention_events e WHERE e.owner_id=p_owner AND e.input_id=p.xray_input_id)
      OR NOT EXISTS(SELECT 1 FROM xray_input_snapshots x WHERE x.owner_id=p_owner AND x.id=p.xray_input_id AND octet_length(x.canonical_input)>0)
      OR NOT EXISTS(SELECT 1 FROM xray_runs x WHERE x.owner_id=p_owner AND x.id=p.xray_run_id AND octet_length(x.canonical_summary)>0)))
    OR (p.historical_input_id IS NOT NULL AND (EXISTS(SELECT 1 FROM historical_retention_events e WHERE e.owner_id=p_owner AND e.input_id=p.historical_input_id)
      OR NOT EXISTS(SELECT 1 FROM historical_input_snapshots h WHERE h.owner_id=p_owner AND h.id=p.historical_input_id AND octet_length(h.canonical_input)>0))))
  OR EXISTS(SELECT 1 FROM history h JOIN historical_classification_evidence c ON c.id=h.classification_id AND c.owner_id=h.owner_id JOIN provider_license_versions l ON l.id=c.license_version_id AND l.owner_id=c.owner_id WHERE
    report_premium_license_restricted(c.owner_id,l.provider_id,c.license_version_id,c.created_at,(SELECT expires_at FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input),p_at))
  OR (p_kind='risk' AND NOT EXISTS(SELECT 1 FROM risk_results result WHERE result.owner_id=p_owner AND result.run_id=p_run AND result.sealed AND octet_length(result.canonical_result)>0))
  OR (p_kind='scenario' AND (
    NOT scenario_capture_complete(p_run)
    OR NOT EXISTS(SELECT 1 FROM scenario_results result WHERE result.owner_id=p_owner AND result.run_id=p_run AND result.sealed AND octet_length(result.canonical_result)>0
      AND result.component_count=(SELECT count(*) FROM scenario_components c WHERE c.result_id=result.id)
      AND result.applied_use_count=(SELECT count(*) FROM scenario_applied_sensitivities a WHERE a.result_id=result.id))
    OR EXISTS(SELECT 1 FROM source_headers h WHERE report_premium_license_restricted(h.owner_id,h.provider_id,h.license_version_id,h.created_at,(SELECT expires_at FROM premium_runs WHERE owner_id=p_owner AND id=p_run),p_at))
    OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions c JOIN scenario_sensitivity_versions v ON v.owner_id=c.owner_id AND v.id=c.version_id WHERE c.owner_id=p_owner AND c.run_id=p_run AND (
      v.expires_at<=p_at OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention e WHERE e.owner_id=v.owner_id AND e.version_id=v.id)
      OR NOT EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads p WHERE p.owner_id=v.owner_id AND p.version_id=v.id)))
    OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_observations c WHERE c.owner_id=p_owner AND c.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_observation_payloads p WHERE p.owner_id=c.owner_id AND p.observation_id=c.observation_id))
    OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_evidence c WHERE c.owner_id=p_owner AND c.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads p WHERE p.owner_id=c.owner_id AND p.evidence_id=c.evidence_id))
  ))
$$;
"""

_GUARDS = r"""
CREATE OR REPLACE FUNCTION report_premium_restricted(p_owner uuid, p_input uuid, p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE
  WHEN i.contract_version IN (1,2) THEN report_premium_restricted_v2(p_owner,p_input,p_at)
  WHEN i.contract_version=3 THEN
   (SELECT count(*) FROM report_input_premium_dependencies d WHERE d.owner_id=i.owner_id AND d.account_id=i.account_id AND d.input_id=i.id)<>1
   OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d
    LEFT JOIN premium_runs root ON root.owner_id=d.owner_id AND root.account_id=d.account_id AND root.id=d.run_id
    WHERE d.owner_id=i.owner_id AND d.input_id=i.id AND (
     NOT report_premium_v3_basis_valid(d,i)
     OR root.kind IS DISTINCT FROM d.kind OR root.input_digest IS DISTINCT FROM d.input_digest
     OR d.expires_at>root.expires_at OR d.expires_at<=d.created_at OR d.expires_at<=p_at OR root.expires_at<=p_at
     OR EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=d.owner_id AND e.run_id=d.run_id)
     OR report_premium_v3_sources_restricted(d.owner_id,d.input_id,d.run_id,d.kind,p_at)))
  ELSE true END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

CREATE OR REPLACE FUNCTION report_premium_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Premium report lineage is immutable' USING ERRCODE='23514'; END IF;
 PERFORM id FROM premium_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.run_id FOR UPDATE;
 SELECT * INTO inp FROM report_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
 IF inp.contract_version NOT IN (2,3) OR inp.id IS NULL OR inp.sealed_at IS NOT NULL OR inp.purged_at IS NOT NULL THEN
  RAISE EXCEPTION 'Premium report capture is not open' USING ERRCODE='23514'; END IF;
 IF inp.contract_version=2 THEN
  IF num_nonnulls(NEW.result_id,NEW.definition_version_id,NEW.definition_digest,NEW.snapshot_id,NEW.snapshot_digest,NEW.reporting_currency,NEW.source_cutoff_at,NEW.valuation_at)<>0 OR NOT EXISTS (
   SELECT 1 FROM premium_runs r JOIN risk_runs rr ON rr.owner_id=r.owner_id AND rr.account_id=r.account_id AND rr.id=r.id
   JOIN risk_results result ON result.owner_id=r.owner_id AND result.account_id=r.account_id AND result.run_id=r.id
   JOIN premium_jobs j ON j.owner_id=r.owner_id AND j.account_id=r.account_id AND j.run_id=r.id
   WHERE r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id AND r.id=NEW.run_id
     AND r.kind=NEW.kind AND rr.sealed AND result.sealed AND j.state='succeeded'
     AND r.input_digest=NEW.input_digest AND result.content_digest=NEW.result_digest
     AND NEW.expires_at<=r.expires_at AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
     AND NOT EXISTS (SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
  ) THEN RAISE EXCEPTION 'Premium report source binding mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT report_premium_v3_basis_valid(NEW,inp) OR NOT EXISTS(
   SELECT 1 FROM premium_runs r WHERE r.id=NEW.run_id AND r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id
    AND r.kind=NEW.kind AND r.input_digest=NEW.input_digest AND NEW.expires_at<=r.expires_at
    AND NEW.expires_at>NEW.created_at AND NEW.expires_at>CURRENT_TIMESTAMP
    AND NOT EXISTS(SELECT 1 FROM premium_retention_events e WHERE e.owner_id=r.owner_id AND e.run_id=r.id)
  ) THEN RAISE EXCEPTION 'Third-profile source binding mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF (version=1 AND dependencies<>0) OR (version IN (2,3) AND dependencies<>1) THEN
  RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version IN (2,3) AND (EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
  RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_command_contract_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer;
BEGIN
 IF NEW.command NOT IN ('reports.generate.v1','reports.generate.v2') THEN RETURN NEW; END IF;
 SELECT contract_version INTO version FROM report_jobs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.report_job_id;
 IF version IS NULL OR (NEW.command='reports.generate.v1' AND version<>1) OR (NEW.command='reports.generate.v2' AND version NOT IN (2,3)) THEN
  RAISE EXCEPTION 'Report command contract mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner uuid; run uuid;
BEGIN
 -- Direct financial DELETE/UPDATE already holds the target row. Do not wait
 -- on an owner whose normal cleanup may need that row while holding the root.
 IF TG_TABLE_NAME IN ('scenario_run_payloads','scenario_results','scenario_components','scenario_applied_sensitivities') THEN
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||OLD.owner_id::text,0)) THEN
   RAISE EXCEPTION 'Scenario report source owner is busy' USING ERRCODE='55P03'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_retention_events' THEN
  owner:=NEW.owner_id; run:=NEW.run_id;
  PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
  IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
  IF TG_OP='UPDATE' AND NEW.retained_bytes>=OLD.retained_bytes AND NEW.reserved_bytes>=OLD.reserved_bytes THEN RETURN NEW; END IF;
  owner:=OLD.owner_id; run:=OLD.id;
 ELSIF TG_TABLE_NAME IN ('risk_run_assets','risk_results','scenario_run_payloads','scenario_results') THEN
  owner:=OLD.owner_id; run:=OLD.run_id;
 ELSIF TG_TABLE_NAME IN ('scenario_components','scenario_applied_sensitivities') THEN
  owner:=OLD.owner_id;
  SELECT run_id INTO run FROM scenario_results WHERE owner_id=owner AND id=OLD.result_id;
 ELSE
  owner:=OLD.owner_id;
  SELECT run_id INTO run FROM risk_results WHERE owner_id=owner AND id=OLD.result_id;
 END IF;
 PERFORM id FROM premium_runs WHERE owner_id=owner AND id=run FOR UPDATE;
 IF EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=owner AND d.run_id=run AND report_capture_pending(d.owner_id,d.input_id)) THEN
  RAISE EXCEPTION 'Premium report copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v WHERE v.version_id=p_version AND (
  scenario_run_has_payload(v.run_id) OR EXISTS(SELECT 1 FROM report_input_premium_dependencies d WHERE d.owner_id=v.owner_id AND d.run_id=v.run_id AND report_capture_pending(d.owner_id,d.input_id))))
$$;
"""
