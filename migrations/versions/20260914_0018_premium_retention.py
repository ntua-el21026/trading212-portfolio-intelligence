"""Source-license lineage for bounded premium retention; no financial payload changes.

Revision ID: 20260914_0018
Revises: 20260914_0017
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0018"
down_revision = "20260914_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "premium_run_licenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["broker_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            ondelete="RESTRICT",
            name="fk_premium_premium_runs_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_premium_run_license_owner_provider",
        ),
        sa.UniqueConstraint("owner_id", "account_id", "id"),
        sa.UniqueConstraint("run_id", "license_version_id"),
    )
    op.create_index(
        "ix_premium_run_licenses_provider",
        "premium_run_licenses",
        ["owner_id", "provider_id", "run_id"],
    )
    # Existing risk captures carry normalized references, including nested registered
    # evidence. UNION deduplicates revisits; no financial document is decoded or changed.
    op.execute("""
      WITH RECURSIVE dependencies AS (
        SELECT r.id AS run_id, r.owner_id, r.account_id, d.id, d.license_version_id,
               d.registered_evidence_id
        FROM risk_runs r JOIN historical_dependencies d
          ON d.owner_id=r.owner_id AND d.input_id=r.historical_input_id
        UNION
        SELECT p.run_id, p.owner_id, p.account_id, d.id, d.license_version_id,
               d.registered_evidence_id
        FROM dependencies p JOIN historical_dependencies d
          ON d.owner_id=p.owner_id AND d.evidence_id=p.registered_evidence_id
      ), licenses AS (
        SELECT run_id, owner_id, account_id, license_version_id FROM dependencies
        WHERE license_version_id IS NOT NULL
        UNION
        SELECT r.id, r.owner_id, r.account_id, d.license_version_id
        FROM risk_runs r JOIN xray_runs x ON x.owner_id=r.owner_id AND x.id=r.xray_run_id
        JOIN xray_input_dependencies d ON d.owner_id=x.owner_id AND d.input_id=x.input_id
        WHERE d.license_version_id IS NOT NULL
      )
      INSERT INTO premium_run_licenses
        (id, owner_id, account_id, run_id, provider_id, license_version_id, created_at)
      SELECT gen_random_uuid(), p.owner_id, p.account_id, p.run_id, l.provider_id,
             l.id, r.created_at
      FROM licenses p JOIN provider_license_versions l
        ON l.owner_id=p.owner_id AND l.id=p.license_version_id
      JOIN premium_runs r ON r.owner_id=p.owner_id AND r.id=p.run_id
    """)
    op.execute("""
      CREATE FUNCTION premium_run_license_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE pinned boolean;
      BEGIN
        IF TG_OP <> 'INSERT' THEN
          RAISE EXCEPTION 'Premium license lineage is immutable' USING ERRCODE='23514';
        END IF;
        SELECT sealed INTO pinned FROM risk_runs
          WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        IF pinned IS DISTINCT FROM false OR
          (SELECT count(*) FROM premium_run_licenses WHERE run_id=NEW.run_id)>=8192 THEN
          RAISE EXCEPTION 'Premium license lineage is sealed or over capacity' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER premium_run_license_guard BEFORE INSERT OR UPDATE OR DELETE
        ON premium_run_licenses FOR EACH ROW EXECUTE FUNCTION premium_run_license_guard();
    """)


def downgrade() -> None:
    op.drop_table("premium_run_licenses")
    op.execute("DROP FUNCTION premium_run_license_guard()")
