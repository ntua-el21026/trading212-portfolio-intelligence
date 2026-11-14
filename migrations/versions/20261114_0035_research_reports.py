"""Exact research report dependencies and bounded physical-copy barriers.

Revision ID:20261114_0035; down revision20261113_0034.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261114_0035"
down_revision = "20261113_0034"
branch_labels = None
depends_on = None


def _owned():
    return [
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
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
    ]


def _fk(name, columns, target, target_columns):
    return sa.ForeignKeyConstraint(
        columns, [f"{target}.{c}" for c in target_columns], name=name, ondelete="RESTRICT"
    )


def _member(name):
    return _fk(
        f"fk_{name}_research",
        ["owner_id", "account_id", "input_id"],
        "report_input_research_dependencies",
        ["owner_id", "account_id", "input_id"],
    )


def upgrade() -> None:
    op.create_table(
        "report_input_research_dependencies",
        *_owned(),
        *[
            sa.Column(c, sa.Uuid(), nullable=False)
            for c in (
                "item_id",
                "entity_id",
                "event_id",
                "event_revision_id",
                "xray_run_id",
                "xray_input_id",
            )
        ],
        *[
            sa.Column(c, sa.String(64), nullable=False)
            for c in (
                "item_selection_digest",
                "event_revision_digest",
                "xray_input_digest",
                "xray_result_digest",
                "xray_pin_digest",
            )
        ],
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("note_count", sa.Integer(), nullable=False),
        sa.Column("review_acknowledgment_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("copy_pending", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("payload_pending", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _fk(
            "fk_report_research_input",
            ["owner_id", "account_id", "input_id"],
            "report_input_snapshots",
            ["owner_id", "account_id", "id"],
        ),
        _fk(
            "fk_report_research_item",
            ["owner_id", "account_id", "item_id"],
            "research_items",
            ["owner_id", "account_id", "id"],
        ),
        _fk(
            "fk_report_research_event",
            ["owner_id", "account_id", "event_revision_id"],
            "research_event_revisions",
            ["owner_id", "account_id", "id"],
        ),
        _fk(
            "fk_report_research_review",
            ["owner_id", "account_id", "review_acknowledgment_id"],
            "research_review_acknowledgments",
            ["owner_id", "account_id", "id"],
        ),
        _fk(
            "fk_report_research_xray_input",
            ["owner_id", "xray_input_id"],
            "xray_input_snapshots",
            ["owner_id", "id"],
        ),
        _fk(
            "fk_report_research_xray_run",
            ["owner_id", "xray_run_id"],
            "xray_runs",
            ["owner_id", "id"],
        ),
        sa.UniqueConstraint("input_id", name="uq_report_research_input"),
        sa.UniqueConstraint("owner_id", "account_id", "input_id", name="uq_report_research_scope"),
        sa.CheckConstraint(
            "source_count BETWEEN 1 AND 4160 AND note_count BETWEEN 0 AND 64", name="counts"
        ),
        sa.CheckConstraint("expires_at>created_at", name="expiry"),
        sa.CheckConstraint("copy_pending OR NOT payload_pending", name="physical_pending"),
        sa.CheckConstraint(
            " AND ".join(
                f"{c} ~ '^[0-9a-f]{{64}}$'"
                for c in (
                    "item_selection_digest",
                    "event_revision_digest",
                    "xray_input_digest",
                    "xray_result_digest",
                    "xray_pin_digest",
                )
            ),
            name="digests",
        ),
    )
    op.create_table(
        "report_input_research_sources",
        *_owned(),
        *[
            sa.Column(c, sa.Uuid(), nullable=False)
            for c in (
                "source_version_id",
                "origin_id",
                "provider_id",
                "entity_id",
                "license_version_id",
                "capability_grant_id",
            )
        ],
        *[
            sa.Column(c, sa.String(64), nullable=False)
            for c in ("source_version_digest", "license_digest", "capability_grant_digest")
        ],
        sa.Column("capability", sa.String(30), nullable=False),
        *[
            sa.Column(c, sa.DateTime(timezone=True), nullable=False)
            for c in (
                "original_retained_at",
                "original_expires_at",
                "retained_at",
                "effective_expires_at",
            )
        ],
        sa.Column("copy_pending", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _member("report_research_source"),
        _fk(
            "fk_report_research_source_version",
            ["owner_id", "source_version_id"],
            "research_source_versions",
            ["owner_id", "id"],
        ),
        _fk(
            "fk_report_research_source_origin",
            ["owner_id", "origin_id"],
            "research_source_origins",
            ["owner_id", "id"],
        ),
        _fk(
            "fk_report_research_source_license",
            ["owner_id", "provider_id", "license_version_id"],
            "provider_license_versions",
            ["owner_id", "provider_id", "id"],
        ),
        _fk(
            "fk_report_research_source_grant",
            ["owner_id", "capability_grant_id"],
            "provider_capability_grants",
            ["owner_id", "id"],
        ),
        sa.UniqueConstraint("input_id", "source_version_id", name="uq_report_research_source"),
        sa.CheckConstraint("capability IN ('news','company_overview')", name="capability"),
        sa.CheckConstraint(
            " AND ".join(
                f"{c} ~ '^[0-9a-f]{{64}}$'"
                for c in ("source_version_digest", "license_digest", "capability_grant_digest")
            ),
            name="digests",
        ),
        sa.CheckConstraint(
            "original_retained_at<=retained_at AND retained_at<effective_expires_at AND effective_expires_at<=original_expires_at",
            name="clocks",
        ),
    )
    op.create_table(
        "report_input_research_notes",
        *_owned(),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("copy_pending", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _member("report_research_note"),
        _fk(
            "fk_report_research_note_revision",
            ["owner_id", "account_id", "revision_id"],
            "research_note_revisions",
            ["owner_id", "account_id", "id"],
        ),
        sa.UniqueConstraint("input_id", "ordinal", name="uq_report_research_note_ordinal"),
        sa.UniqueConstraint("input_id", "revision_id", name="uq_report_research_note_revision"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 63", name="ordinal"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
    )
    op.create_table(
        "report_research_retention_sweep",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("after_id", sa.Uuid(), nullable=True),
        sa.Column("physical_after_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id=1", name="singleton"),
    )
    for name, table, columns in _INDICES:
        op.create_index(name, table, columns)
    op.drop_constraint(
        op.f("ck_report_retention_work_legacy_witness_bound"),
        "report_retention_work",
        type_="check",
    )
    op.create_check_constraint("legacy_witness_bound", "report_retention_work", _WITNESS_CHECK)
    op.execute(_RIGHTS)
    op.execute(_GUARDS)
    op.execute(_PREMIUM)
    op.execute(_WITNESS)
    op.execute(
        "CREATE TRIGGER report_research_guard BEFORE INSERT OR UPDATE OR DELETE ON "
        "report_input_research_dependencies FOR EACH ROW EXECUTE FUNCTION report_research_guard()"
    )
    op.execute(
        "CREATE TRIGGER report_research_guard BEFORE INSERT OR UPDATE OR DELETE ON "
        "report_input_research_sources FOR EACH ROW EXECUTE FUNCTION report_research_guard()"
    )
    op.execute(
        "CREATE TRIGGER report_research_guard BEFORE INSERT OR UPDATE OR DELETE ON "
        "report_input_research_notes FOR EACH ROW EXECUTE FUNCTION report_research_guard()"
    )
    op.execute(
        "CREATE TRIGGER research_report_complete BEFORE UPDATE ON report_input_snapshots FOR EACH ROW EXECUTE FUNCTION report_research_complete()"
    )
    op.execute(
        "CREATE TRIGGER research_report_copy_barrier BEFORE DELETE ON research_source_payloads "
        "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()"
    )
    op.execute(
        "CREATE TRIGGER research_report_copy_barrier BEFORE DELETE ON research_event_payloads "
        "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()"
    )
    op.execute(
        "CREATE TRIGGER research_report_copy_barrier BEFORE DELETE ON research_note_payloads "
        "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()"
    )
    op.execute(
        "CREATE TRIGGER research_report_copy_barrier BEFORE UPDATE ON research_source_retention "
        "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()"
    )
    op.execute(
        "CREATE TRIGGER research_report_copy_barrier BEFORE UPDATE ON research_owner_erasure "
        "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()"
    )
    op.execute(
        "CREATE TRIGGER research_report_copy_barrier BEFORE UPDATE ON report_retention_work "
        "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()"
    )
    op.execute(
        "CREATE TRIGGER research_report_xray_barrier BEFORE UPDATE OR DELETE ON xray_input_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION research_report_xray_barrier('input')"
    )
    op.execute(
        "CREATE TRIGGER research_report_xray_barrier BEFORE UPDATE OR DELETE ON xray_runs "
        "FOR EACH ROW EXECUTE FUNCTION research_report_xray_barrier('run')"
    )


def downgrade() -> None:
    # Only an unused disposable feature schema can be removed. Lock before the
    # emptiness proof so concurrent captures/cleanup cannot introduce provenance
    # between that proof and DDL. Any refusal rolls back this entire transaction.
    op.execute(_EMPTY_DOWNGRADE_GUARD)
    # Replace the original function bodies in place: existing constraint triggers
    # and cached callers retain the original function OIDs throughout rollback.
    op.execute(_PREVIOUS_PREMIUM)
    op.execute(_PREVIOUS_WITNESS)
    op.drop_constraint(
        op.f("ck_report_retention_work_legacy_witness_bound"),
        "report_retention_work",
        type_="check",
    )
    op.create_check_constraint(
        "legacy_witness_bound", "report_retention_work", _PREVIOUS_WITNESS_CHECK
    )
    op.execute("DROP TRIGGER report_research_guard ON report_input_research_dependencies")
    op.execute("DROP TRIGGER report_research_guard ON report_input_research_sources")
    op.execute("DROP TRIGGER report_research_guard ON report_input_research_notes")
    op.execute("DROP TRIGGER research_report_complete ON report_input_snapshots")
    op.execute("DROP TRIGGER research_report_copy_barrier ON research_source_payloads")
    op.execute("DROP TRIGGER research_report_copy_barrier ON research_event_payloads")
    op.execute("DROP TRIGGER research_report_copy_barrier ON research_note_payloads")
    op.execute("DROP TRIGGER research_report_copy_barrier ON research_source_retention")
    op.execute("DROP TRIGGER research_report_copy_barrier ON research_owner_erasure")
    op.execute("DROP TRIGGER research_report_copy_barrier ON report_retention_work")
    op.execute("DROP TRIGGER research_report_xray_barrier ON xray_input_snapshots")
    op.execute("DROP TRIGGER research_report_xray_barrier ON xray_runs")
    op.execute("DROP FUNCTION report_research_complete()")
    op.execute("DROP FUNCTION report_research_guard()")
    op.execute("DROP FUNCTION research_report_copy_barrier()")
    op.execute("DROP FUNCTION research_report_xray_barrier()")
    op.execute("DROP FUNCTION report_research_restricted(uuid,uuid,timestamptz)")
    op.execute("DROP FUNCTION report_research_source_restricted(uuid,uuid,timestamptz)")
    op.execute("DROP FUNCTION report_research_physical_restricted(uuid,uuid,uuid,timestamptz)")
    op.execute("DROP FUNCTION report_research_acquired_report_restricted(uuid,text,uuid,timestamptz)")
    for name, table, _columns in reversed(_INDICES):
        op.drop_index(name, table_name=table)
    for table in (
        "report_input_research_notes",
        "report_input_research_sources",
        "report_input_research_dependencies",
        "report_research_retention_sweep",
    ):
        op.drop_table(table)


_EMPTY_DOWNGRADE_GUARD = r"""
LOCK TABLE report_input_snapshots,report_retention_work,
 report_input_research_dependencies,report_input_research_sources,
 report_input_research_notes,report_research_retention_sweep IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM report_input_research_dependencies)
 OR EXISTS(SELECT 1 FROM report_input_research_sources)
 OR EXISTS(SELECT 1 FROM report_input_research_notes)
 OR EXISTS(SELECT 1 FROM report_research_retention_sweep)
 OR EXISTS(SELECT 1 FROM report_retention_work WHERE legacy_source_kind IN ('research_source','research_owner','research_xray')) THEN
  RAISE EXCEPTION 'Research report downgrade requires empty research report provenance and cleanup state'
   USING ERRCODE='23514';
 END IF;
END $$;
"""

# Frozen applied definitions from20260915_0023_projection_reports.py::_GUARDS,
# unchanged by0024--0034. CREATE OR REPLACE preserves existing trigger OIDs.
_PREVIOUS_PREMIUM = r"""
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
  WHEN i.contract_version=4 THEN report_projection_restricted(p_owner,p_input,p_at)
  ELSE true END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;

CREATE OR REPLACE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF (version=1 AND dependencies<>0) OR (version IN (2,3,4) AND dependencies<>1) THEN
  RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version IN (2,3,4) AND (EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
  RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

# Frozen0025::_PROBES definition; only CREATE gains OR REPLACE to retain its OID.
_PREVIOUS_WITNESS = r"""
CREATE OR REPLACE FUNCTION legacy_report_witness_restricted(p_owner uuid,p_input uuid,p_kind text,p_subject uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT restricted FROM legacy_report_retention_probe(p_owner,p_input,p_kind,p_subject,p_at)),false)
$$;
"""
_PREVIOUS_WITNESS_CHECK = (
    "(legacy_source_kind IS NULL AND legacy_source_id IS NULL) OR (reason='source' "
    "AND legacy_source_kind IN ('physical','root','report_license','premium_license',"
    "'parents','history','version','observation','evidence') AND legacy_source_id IS "
    "NOT NULL AND projection_source_kind IS NULL AND projection_source_id IS NULL)"
)


_INDICES = (
    ("ix_report_research_physical_sweep", "report_input_dependencies", ["copy_pending", "id"]),
    (
        "ix_report_research_owner_pending",
        "report_input_research_dependencies",
        ["owner_id", "copy_pending", "input_id", "id"],
    ),
    (
        "ix_report_research_event_pending",
        "report_input_research_dependencies",
        ["owner_id", "event_revision_id", "copy_pending", "input_id"],
    ),
    (
        "ix_report_research_xray_pending",
        "report_input_research_dependencies",
        ["owner_id", "xray_input_id", "copy_pending", "input_id"],
    ),
    (
        "ix_report_research_run_pending",
        "report_input_research_dependencies",
        ["owner_id", "xray_run_id", "copy_pending", "input_id"],
    ),
    (
        "ix_report_research_event_payload",
        "report_input_research_dependencies",
        ["owner_id", "event_revision_id", "payload_pending", "input_id"],
    ),
    (
        "ix_report_research_xray_payload",
        "report_input_research_dependencies",
        ["owner_id", "xray_input_id", "payload_pending", "input_id"],
    ),
    (
        "ix_report_research_run_payload",
        "report_input_research_dependencies",
        ["owner_id", "xray_run_id", "payload_pending", "input_id"],
    ),
    (
        "ix_report_research_source_pending",
        "report_input_research_sources",
        ["owner_id", "source_version_id", "copy_pending", "input_id", "id"],
    ),
    (
        "ix_report_research_sources_input",
        "report_input_research_sources",
        ["owner_id", "input_id", "copy_pending", "id"],
    ),
    ("ix_report_research_sources_sweep", "report_input_research_sources", ["copy_pending", "id"]),
    (
        "ix_report_research_note_pending",
        "report_input_research_notes",
        ["owner_id", "revision_id", "copy_pending", "input_id", "id"],
    ),
    (
        "ix_report_research_notes_input",
        "report_input_research_notes",
        ["owner_id", "input_id", "copy_pending", "id"],
    ),
)
_WITNESS_CHECK = """(legacy_source_kind IS NULL AND legacy_source_id IS NULL) OR
 (reason='source' AND legacy_source_kind IN ('physical','root','report_license','premium_license',
 'parents','history','version','observation','evidence','research_source','research_owner','research_xray')
 AND legacy_source_id IS NOT NULL AND projection_source_kind IS NULL AND projection_source_id IS NULL)"""

_RIGHTS = r"""
CREATE FUNCTION report_research_acquired_report_restricted(p_owner uuid,p_kind text,p_source uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 -- Only the existing acquired financial families have this authority. The
 -- existing helper explicitly admits ordinary non-acquired price/FX headers.
 SELECT CASE p_kind WHEN 'price' THEN acquisition_source_restricted(p_owner,'price',p_source,p_at,'report')
 WHEN 'fx' THEN acquisition_source_restricted(p_owner,'fx',p_source,p_at,'report') ELSE false END
$$;

CREATE FUNCTION report_research_physical_restricted(p_owner uuid,p_input uuid,p_member uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM report_input_dependencies m
 JOIN report_input_research_dependencies d ON d.owner_id=m.owner_id AND d.input_id=m.input_id
 WHERE m.owner_id=p_owner AND m.input_id=p_input AND m.id=p_member AND m.copy_pending AND d.copy_pending
 AND (coalesce((SELECT restricted FROM legacy_report_physical_probe(p_owner,p_input,p_member,p_at)),true)
  OR report_research_acquired_report_restricted(p_owner,m.kind,m.source_id,p_at)))
$$;

CREATE FUNCTION report_research_source_restricted(p_owner uuid,p_member uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT EXISTS (
 SELECT 1 FROM report_input_research_sources m
 JOIN research_source_versions s ON s.owner_id=m.owner_id AND s.id=m.source_version_id
 JOIN research_source_origins o ON o.owner_id=s.owner_id AND o.id=s.origin_id
 JOIN market_data_providers p ON p.owner_id=s.owner_id AND p.id=s.provider_id
 JOIN provider_capability_grants g ON g.owner_id=s.owner_id AND g.id=s.capability_grant_id
 JOIN provider_capability_scopes scope ON scope.owner_id=g.owner_id AND scope.id=g.scope_id
 JOIN LATERAL (SELECT * FROM provider_capability_grants WHERE owner_id=g.owner_id AND scope_id=g.scope_id
   AND effective_at<=p_at ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1) current_grant ON true
 JOIN provider_license_versions pinned ON pinned.owner_id=s.owner_id AND pinned.provider_id=s.provider_id AND pinned.id=s.license_version_id
 JOIN LATERAL (SELECT * FROM provider_license_versions WHERE owner_id=s.owner_id AND provider_id=s.provider_id
   AND effective_at<=p_at ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1) current_license ON true
 WHERE m.owner_id=p_owner AND m.id=p_member AND m.copy_pending AND s.sealed
 AND ROW(m.source_version_digest,m.origin_id,m.provider_id,m.entity_id,m.capability,m.license_version_id,
   m.capability_grant_id,m.capability_grant_digest,m.original_retained_at,m.original_expires_at,m.retained_at,m.effective_expires_at)
 IS NOT DISTINCT FROM ROW(s.content_digest,s.origin_id,s.provider_id,s.entity_id,s.capability,s.license_version_id,
   s.capability_grant_id,s.capability_grant_digest,o.original_retained_at,o.expires_at,s.retained_at,s.effective_expires_at)
 AND ROW(o.entity_id,o.capability,o.facts_digest) IS NOT DISTINCT FROM ROW(s.entity_id,s.capability,s.facts_digest)
 AND p.key='alpha_vantage' AND p.configuration_state='configured'
 AND g.provider_id=s.provider_id AND g.content_digest=s.capability_grant_digest AND g.license_version_id=s.license_version_id
 AND scope.provider_id=s.provider_id AND scope.subject_kind='entity' AND scope.subject_id=s.entity_id
 AND scope.capability=CASE s.capability WHEN 'news' THEN 'news_sentiment' WHEN 'company_overview' THEN 'company_overview' ELSE 'invalid' END
 AND g.store_allowed AND g.display_allowed AND g.report_allowed
 AND current_grant.store_allowed AND current_grant.display_allowed AND current_grant.report_allowed
 AND g.effective_at<=s.retained_at AND g.effective_at<=p_at AND g.expires_at>p_at AND current_grant.expires_at>p_at
 AND current_grant.license_version_id=current_license.id
 AND pinned.effective_at<=s.retained_at AND pinned.effective_at<=p_at
 AND pinned.store_permission='allowed' AND pinned.display_permission='allowed' AND pinned.report_permission='allowed'
 AND current_license.store_permission='allowed' AND current_license.display_permission='allowed' AND current_license.report_permission='allowed'
 AND pinned.retention_days IS NOT NULL AND current_license.retention_days IS NOT NULL
 AND o.original_retained_at<=s.retained_at AND s.retained_at<s.effective_expires_at
 AND s.effective_expires_at<=least(s.expires_at,o.expires_at,g.expires_at,current_grant.expires_at,
   o.original_retained_at+make_interval(days=>least(30,pinned.retention_days,current_license.retention_days)))
 AND p_at<least(s.expires_at,s.effective_expires_at,o.expires_at,g.expires_at,current_grant.expires_at,
   o.original_retained_at+make_interval(days=>least(30,pinned.retention_days,current_license.retention_days)))
 AND NOT EXISTS(SELECT 1 FROM research_source_retention WHERE owner_id=p_owner AND source_version_id=s.id)
 AND NOT EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=p_owner)
 AND EXISTS(SELECT 1 FROM research_source_payloads WHERE owner_id=p_owner AND version_id=s.id))
$$;

CREATE FUNCTION report_research_restricted(p_owner uuid,p_input uuid,p_at timestamptz)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE d report_input_research_dependencies; item research_items; event research_event_revisions;
BEGIN
 SELECT * INTO d FROM report_input_research_dependencies WHERE owner_id=p_owner AND input_id=p_input;
 IF d.id IS NULL OR NOT d.copy_pending OR NOT d.payload_pending OR d.expires_at<=p_at THEN RETURN true; END IF;
 SELECT * INTO item FROM research_items WHERE owner_id=p_owner AND account_id=d.account_id AND id=d.item_id;
 SELECT * INTO event FROM research_event_revisions WHERE owner_id=p_owner AND account_id=d.account_id AND id=d.event_revision_id;
 IF item.id IS NULL OR event.id IS NULL OR NOT event.sealed OR event.visible_at>d.source_cutoff_at
 OR ROW(d.item_selection_digest,d.entity_id,d.event_id,d.event_revision_id,d.event_revision_digest,
   d.xray_run_id,d.xray_input_id,d.xray_input_digest,d.xray_result_digest,d.xray_pin_digest,d.source_cutoff_at)
 IS DISTINCT FROM ROW(item.selection_digest,item.entity_id,event.event_id,item.revision_id,item.revision_digest,
   item.xray_run_id,item.xray_input_id,item.xray_input_digest,item.xray_result_digest,item.xray_pin_digest,item.source_cutoff_at)
 OR event.content_digest<>d.event_revision_digest OR d.expires_at>least(item.expires_at,event.expires_at)
 OR EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=p_owner)
 OR EXISTS(SELECT 1 FROM report_retention_work WHERE owner_id=p_owner AND input_id=p_input)
 OR EXISTS(SELECT 1 FROM xray_retention_events WHERE owner_id=p_owner AND input_id=d.xray_input_id)
 OR NOT EXISTS(SELECT 1 FROM research_event_payloads WHERE owner_id=p_owner AND revision_id=event.id)
 OR NOT EXISTS(SELECT 1 FROM xray_runs r JOIN xray_input_snapshots x ON x.owner_id=r.owner_id AND x.id=r.input_id
   WHERE r.owner_id=p_owner AND r.id=d.xray_run_id AND x.id=d.xray_input_id AND x.account_id=d.account_id
   AND r.content_digest=d.xray_result_digest AND x.input_digest=d.xray_input_digest
   AND r.sealed_at IS NOT NULL AND x.sealed_at IS NOT NULL)
 THEN RETURN true; END IF;
 IF (SELECT count(*) FROM report_input_research_sources WHERE owner_id=p_owner AND input_id=p_input)<>d.source_count
 OR (SELECT count(*) FROM report_input_research_notes WHERE owner_id=p_owner AND input_id=p_input)<>d.note_count
 OR EXISTS(SELECT 1 FROM report_input_research_sources WHERE owner_id=p_owner AND input_id=p_input
   AND (NOT copy_pending OR d.expires_at>effective_expires_at OR report_research_source_restricted(p_owner,id,p_at)))
 OR EXISTS(SELECT 1 FROM report_input_research_notes m LEFT JOIN research_note_revisions n
   ON n.owner_id=m.owner_id AND n.account_id=m.account_id AND n.id=m.revision_id
   WHERE m.owner_id=p_owner AND m.input_id=p_input AND (NOT m.copy_pending OR n.id IS NULL OR NOT n.sealed
   OR n.note_id<>m.note_id OR n.content_digest<>m.content_digest OR n.entity_id<>d.entity_id OR n.created_at>p_at
   OR NOT EXISTS(SELECT 1 FROM research_note_payloads WHERE owner_id=p_owner AND revision_id=m.revision_id)))
 THEN RETURN true; END IF;
 RETURN d.review_acknowledgment_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM research_review_acknowledgments
   WHERE owner_id=p_owner AND account_id=d.account_id AND id=d.review_acknowledgment_id
   AND event_id=d.event_id AND revision_id=d.event_revision_id AND revision_digest=d.event_revision_digest AND reviewed_at<=p_at);
END $$;
"""

_GUARDS = r"""
CREATE FUNCTION report_research_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE capture report_input_snapshots; root report_input_research_dependencies; item research_items;
 source research_source_versions; origin research_source_origins; note research_note_revisions;
BEGIN
 IF TG_TABLE_NAME='report_input_research_dependencies' AND TG_OP='UPDATE' THEN
  IF OLD.payload_pending AND NOT NEW.payload_pending
   AND to_jsonb(NEW)-'payload_pending'=to_jsonb(OLD)-'payload_pending'
   AND EXISTS(SELECT 1 FROM report_retention_work WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id AND completed_at IS NULL)
   AND NOT report_capture_pending(OLD.owner_id,OLD.input_id) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND OLD.copy_pending AND NOT NEW.copy_pending
 AND to_jsonb(NEW)-'copy_pending'=to_jsonb(OLD)-'copy_pending'
 AND EXISTS(SELECT 1 FROM report_retention_work WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id AND completed_at IS NULL)
 AND NOT report_capture_pending(OLD.owner_id,OLD.input_id) THEN
  IF TG_TABLE_NAME='report_input_research_dependencies' THEN
   IF NEW.payload_pending OR EXISTS(SELECT 1 FROM report_input_research_sources WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id AND copy_pending)
   OR EXISTS(SELECT 1 FROM report_input_research_notes WHERE owner_id=OLD.owner_id AND input_id=OLD.input_id AND copy_pending) THEN
    RAISE EXCEPTION 'Research report child flags remain' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Research report lineage is immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO capture FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.input_id FOR UPDATE;
 IF capture.id IS NULL OR capture.contract_version<>3 OR capture.kind<>'report' OR capture.sealed_at IS NOT NULL
 OR capture.purged_at IS NOT NULL OR NEW.copy_pending IS DISTINCT FROM true
 OR EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=NEW.owner_id)
 OR EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id) THEN
  RAISE EXCEPTION 'Research report capture is not open' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='report_input_research_dependencies' THEN
  IF NEW.payload_pending IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'Research report payload must begin pending' USING ERRCODE='23514'; END IF;
  SELECT * INTO item FROM research_items WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.item_id;
  IF item.id IS NULL OR ROW(NEW.item_selection_digest,NEW.entity_id,NEW.event_revision_id,NEW.event_revision_digest,
   NEW.xray_run_id,NEW.xray_input_id,NEW.xray_input_digest,NEW.xray_result_digest,NEW.xray_pin_digest,NEW.source_cutoff_at)
   IS DISTINCT FROM ROW(item.selection_digest,item.entity_id,item.revision_id,item.revision_digest,
    item.xray_run_id,item.xray_input_id,item.xray_input_digest,item.xray_result_digest,item.xray_pin_digest,item.source_cutoff_at)
   OR capture.snapshot_id<>item.snapshot_id OR capture.source_cutoff_at<>item.source_cutoff_at
   OR NEW.expires_at>item.expires_at OR NEW.expires_at<=clock_timestamp() THEN
   RAISE EXCEPTION 'Research report item binding differs' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO root FROM report_input_research_dependencies WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND input_id=NEW.input_id;
  IF root.id IS NULL THEN RAISE EXCEPTION 'Research report root missing' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='report_input_research_sources' THEN
   SELECT * INTO source FROM research_source_versions WHERE owner_id=NEW.owner_id AND id=NEW.source_version_id;
   SELECT * INTO origin FROM research_source_origins WHERE owner_id=NEW.owner_id AND id=source.origin_id;
   IF source.id IS NULL OR ROW(NEW.source_version_digest,NEW.origin_id,NEW.provider_id,NEW.entity_id,NEW.capability,
     NEW.license_version_id,NEW.capability_grant_id,NEW.capability_grant_digest,NEW.original_retained_at,
     NEW.original_expires_at,NEW.retained_at,NEW.effective_expires_at)
   IS DISTINCT FROM ROW(source.content_digest,source.origin_id,source.provider_id,source.entity_id,source.capability,
     source.license_version_id,source.capability_grant_id,source.capability_grant_digest,origin.original_retained_at,
     origin.expires_at,source.retained_at,source.effective_expires_at) THEN
    RAISE EXCEPTION 'Research report original source differs' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO note FROM research_note_revisions WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.revision_id;
   IF note.id IS NULL OR NOT note.sealed OR ROW(NEW.note_id,NEW.content_digest,root.entity_id)
    IS DISTINCT FROM ROW(note.note_id,note.content_digest,note.entity_id) THEN
    RAISE EXCEPTION 'Research report exact note differs' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_research_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root report_input_research_dependencies; manifest jsonb; binding jsonb; chosen jsonb; expected_notes jsonb; review research_review_acknowledgments;
BEGIN
 IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO root FROM report_input_research_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF root.id IS NULL THEN RETURN NEW; END IF;
 manifest:=convert_from(NEW.canonical_manifest,'UTF8')::jsonb;
 binding:=manifest->'document'->'premium_binding'; chosen:=manifest->'document'->'selection'->'premium_run';
 SELECT coalesce(jsonb_agg(jsonb_build_object('note_id',note_id,'revision_id',revision_id,'content_digest',content_digest)
  ORDER BY ordinal),'[]'::jsonb) INTO expected_notes FROM report_input_research_notes WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF binding->>'family' IS DISTINCT FROM 'research' OR chosen->>'family' IS DISTINCT FROM 'research'
 OR binding->>'item_id' IS DISTINCT FROM root.item_id::text OR chosen->>'item_id' IS DISTINCT FROM root.item_id::text
 OR binding->>'item_selection_digest' IS DISTINCT FROM root.item_selection_digest
 OR binding->>'owner_id' IS DISTINCT FROM root.owner_id::text OR binding->>'account_id' IS DISTINCT FROM root.account_id::text
 OR binding->>'entity_id' IS DISTINCT FROM root.entity_id::text OR binding->>'event_id' IS DISTINCT FROM root.event_id::text
 OR binding->>'snapshot_id' IS DISTINCT FROM NEW.snapshot_id::text
 OR binding->>'reporting_currency' IS DISTINCT FROM NEW.reporting_currency
 OR (binding->>'valuation_at')::timestamptz IS DISTINCT FROM NEW.valuation_at
 OR (binding->>'created_at')::timestamptz IS DISTINCT FROM (SELECT created_at FROM research_items WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=root.item_id)
 OR binding->>'event_revision_id' IS DISTINCT FROM root.event_revision_id::text
 OR binding->>'event_revision_digest' IS DISTINCT FROM root.event_revision_digest
 OR (binding->>'source_cutoff_at')::timestamptz IS DISTINCT FROM root.source_cutoff_at
 OR (binding->>'expires_at')::timestamptz IS DISTINCT FROM root.expires_at
 OR binding->'note_revisions' IS DISTINCT FROM expected_notes
 OR chosen->'note_revision_ids' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(revision_id ORDER BY ordinal),'[]'::jsonb)
  FROM report_input_research_notes WHERE owner_id=NEW.owner_id AND input_id=NEW.id)
 OR chosen->>'review_acknowledgment_id' IS DISTINCT FROM root.review_acknowledgment_id::text
 OR binding->'xray' IS DISTINCT FROM jsonb_build_object('run_id',root.xray_run_id,'input_id',root.xray_input_id,
  'input_digest',root.xray_input_digest,'result_digest',root.xray_result_digest) THEN
  RAISE EXCEPTION 'Research report manifest binding differs' USING ERRCODE='23514'; END IF;
 IF root.review_acknowledgment_id IS NULL THEN
  IF binding->'review_acknowledgment' IS NOT NULL AND binding->'review_acknowledgment'<>'null'::jsonb THEN
   RAISE EXCEPTION 'Research report review was not selected' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO review FROM research_review_acknowledgments WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=root.review_acknowledgment_id;
  IF binding->'review_acknowledgment'->>'acknowledgment_id' IS DISTINCT FROM review.id::text
  OR binding->'review_acknowledgment'->>'revision_digest' IS DISTINCT FROM review.revision_digest
  OR (binding->'review_acknowledgment'->>'reviewed_at')::timestamptz IS DISTINCT FROM review.reviewed_at THEN
   RAISE EXCEPTION 'Research report exact review differs' USING ERRCODE='23514'; END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id)
 OR report_research_restricted(NEW.owner_id,NEW.id,clock_timestamp())
 OR EXISTS((SELECT source_version_id FROM research_event_citations WHERE owner_id=NEW.owner_id AND revision_id=root.event_revision_id
   UNION SELECT c.source_version_id FROM research_note_citations c JOIN report_input_research_notes n
    ON n.owner_id=c.owner_id AND n.revision_id=c.revision_id WHERE n.owner_id=NEW.owner_id AND n.input_id=NEW.id)
   EXCEPT SELECT source_version_id FROM report_input_research_sources WHERE owner_id=NEW.owner_id AND input_id=NEW.id)
 OR EXISTS((SELECT source_version_id FROM report_input_research_sources WHERE owner_id=NEW.owner_id AND input_id=NEW.id)
   EXCEPT (SELECT source_version_id FROM research_event_citations WHERE owner_id=NEW.owner_id AND revision_id=root.event_revision_id
    UNION SELECT c.source_version_id FROM research_note_citations c JOIN report_input_research_notes n
     ON n.owner_id=c.owner_id AND n.revision_id=c.revision_id WHERE n.owner_id=NEW.owner_id AND n.input_id=NEW.id)) THEN
  RAISE EXCEPTION 'Research report selected membership incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
EXCEPTION WHEN data_exception THEN
 RAISE EXCEPTION 'Research report manifest binding invalid' USING ERRCODE='23514';
END $$;

CREATE FUNCTION research_report_copy_barrier() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pending boolean:=false;
BEGIN
 IF TG_TABLE_NAME='research_source_payloads' THEN
  SELECT EXISTS(SELECT 1 FROM report_input_research_sources WHERE owner_id=OLD.owner_id AND source_version_id=OLD.version_id AND copy_pending) INTO pending;
 ELSIF TG_TABLE_NAME='research_event_payloads' THEN
  SELECT EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=OLD.owner_id AND event_revision_id=OLD.revision_id AND payload_pending) INTO pending;
 ELSIF TG_TABLE_NAME='research_note_payloads' THEN
  SELECT EXISTS(SELECT 1 FROM report_input_research_notes WHERE owner_id=OLD.owner_id AND revision_id=OLD.revision_id AND copy_pending) INTO pending;
 ELSIF NEW.completed_at IS NOT NULL THEN
  IF TG_TABLE_NAME='research_source_retention' THEN
   SELECT EXISTS(SELECT 1 FROM report_input_research_sources WHERE owner_id=NEW.owner_id AND source_version_id=NEW.source_version_id AND copy_pending) INTO pending;
  ELSIF TG_TABLE_NAME='research_owner_erasure' THEN
   SELECT EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=NEW.owner_id AND copy_pending) INTO pending;
  ELSE
   SELECT EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id AND copy_pending) INTO pending;
  END IF;
 END IF;
 IF pending THEN RAISE EXCEPTION 'Research report physical copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION research_report_xray_barrier() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF TG_ARGV[0]='input' THEN
   IF NEW.canonical_input IS NOT DISTINCT FROM OLD.canonical_input THEN RETURN NEW; END IF;
  ELSE
   IF ROW(NEW.canonical_summary,NEW.canonical_reconciliation,NEW.canonical_exact_state)
    IS NOT DISTINCT FROM ROW(OLD.canonical_summary,OLD.canonical_reconciliation,OLD.canonical_exact_state) THEN RETURN NEW; END IF;
  END IF;
 END IF;
 IF (TG_ARGV[0]='input' AND EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=OLD.owner_id AND xray_input_id=OLD.id AND payload_pending))
 OR (TG_ARGV[0]='run' AND EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=OLD.owner_id AND xray_run_id=OLD.id AND payload_pending)) THEN
  RAISE EXCEPTION 'Research report X-ray copies remain' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
"""

_PREMIUM = r"""
CREATE OR REPLACE FUNCTION report_premium_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version integer; deadline timestamptz; purged timestamptz; dependencies bigint; research_dependencies bigint;
BEGIN
 SELECT contract_version,expires_at,purged_at INTO version,deadline,purged FROM report_input_snapshots WHERE id=NEW.id AND owner_id=NEW.owner_id;
 SELECT count(*) INTO dependencies FROM report_input_premium_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 SELECT count(*) INTO research_dependencies FROM report_input_research_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id;
 IF research_dependencies<>0 THEN
  IF version<>3 OR research_dependencies<>1 OR dependencies<>0 THEN
   RAISE EXCEPTION 'Research report contract lineage mismatch' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=NEW.owner_id AND input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_research_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP)) THEN
   RAISE EXCEPTION 'Research report source is unavailable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (version=1 AND dependencies<>0) OR (version IN (2,3,4) AND dependencies<>1) THEN
  RAISE EXCEPTION 'Report contract lineage mismatch' USING ERRCODE='23514'; END IF;
 IF version IN (2,3,4) AND (EXISTS(SELECT 1 FROM report_input_premium_dependencies WHERE input_id=NEW.id AND expires_at<deadline)
   OR (purged IS NULL AND report_premium_restricted(NEW.owner_id,NEW.id,CURRENT_TIMESTAMP))) THEN
  RAISE EXCEPTION 'Premium report source is unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION report_premium_restricted(p_owner uuid,p_input uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE((SELECT CASE
  WHEN i.contract_version IN (1,2) THEN report_premium_restricted_v2(p_owner,p_input,p_at)
  WHEN i.contract_version=3 AND EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=p_owner AND input_id=p_input)
   THEN report_research_restricted(p_owner,p_input,p_at)
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
  WHEN i.contract_version=4 THEN report_projection_restricted(p_owner,p_input,p_at)
  ELSE true END FROM report_input_snapshots i WHERE i.owner_id=p_owner AND i.id=p_input),true)
$$;
"""

_WITNESS = r"""
CREATE OR REPLACE FUNCTION legacy_report_witness_restricted(p_owner uuid,p_input uuid,p_kind text,p_subject uuid,p_at timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT CASE p_kind
 WHEN 'physical' THEN CASE WHEN EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=p_owner AND input_id=p_input)
  THEN report_research_physical_restricted(p_owner,p_input,p_subject,p_at)
  ELSE coalesce((SELECT restricted FROM legacy_report_retention_probe(p_owner,p_input,p_kind,p_subject,p_at)),false) END
 WHEN 'research_source' THEN EXISTS(SELECT 1 FROM report_input_research_sources m
  WHERE m.owner_id=p_owner AND m.input_id=p_input AND m.id=p_subject AND m.copy_pending
  AND report_research_source_restricted(p_owner,p_subject,p_at))
 WHEN 'research_owner' THEN p_subject=p_owner AND EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=p_owner)
  AND EXISTS(SELECT 1 FROM report_input_research_dependencies WHERE owner_id=p_owner AND input_id=p_input AND copy_pending)
 WHEN 'research_xray' THEN EXISTS(SELECT 1 FROM report_input_research_dependencies d
  WHERE d.owner_id=p_owner AND d.input_id=p_input AND d.xray_input_id=p_subject AND d.copy_pending
  AND EXISTS(SELECT 1 FROM xray_retention_events WHERE owner_id=p_owner AND input_id=p_subject))
 ELSE coalesce((SELECT restricted FROM legacy_report_retention_probe(p_owner,p_input,p_kind,p_subject,p_at)),false) END
$$;
"""
