"""Align only retained X-ray canonical documents with the frozen32MiB ceiling.

Revision ID:20261115_0036; down revision20261114_0035.
Published revisions and historical/ordinary analytics limits remain unchanged.
"""

from alembic import op

revision = "20261115_0036"
down_revision = "20261114_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This lock is acquired before either validated check is replaced. All DDL
    # and the version update share PostgreSQL's migration transaction.
    op.execute("LOCK TABLE analytics_runs IN ACCESS EXCLUSIVE MODE")
    op.drop_constraint(
        op.f("ck_analytics_runs_bound_canonical_input"), "analytics_runs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_bound_canonical_input"),
        "analytics_runs",
        "octet_length(canonical_input) <= CASE WHEN kind IN "
        "('performance','benchmark','income','attribution','cash_flow','xray') "
        "THEN 33554432 ELSE 8388608 END",
    )
    op.drop_constraint(
        op.f("ck_analytics_runs_bound_canonical_result"), "analytics_runs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_bound_canonical_result"),
        "analytics_runs",
        "octet_length(canonical_result) <= CASE WHEN kind IN "
        "('performance','benchmark','income','attribution','cash_flow','xray') "
        "THEN 33554432 ELSE 8388608 END",
    )


def downgrade() -> None:
    # Never rewrite, truncate, delete or ignore newly legal immutable evidence.
    # The same table lock closes the check-to-DDL race with concurrent inserts.
    op.execute(
        "DO $$ BEGIN "
        "LOCK TABLE analytics_runs IN ACCESS EXCLUSIVE MODE; "
        "IF EXISTS (SELECT 1 FROM analytics_runs WHERE kind='xray' AND "
        "(octet_length(canonical_input)>8388608 OR octet_length(canonical_result)>8388608)) "
        "THEN RAISE EXCEPTION 'X-ray canonical payload prevents downgrade' "
        "USING ERRCODE='23514'; END IF; END $$"
    )
    op.drop_constraint(
        op.f("ck_analytics_runs_bound_canonical_input"), "analytics_runs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_bound_canonical_input"),
        "analytics_runs",
        "octet_length(canonical_input) <= CASE WHEN kind IN "
        "('performance','benchmark','income','attribution','cash_flow') "
        "THEN 33554432 ELSE 8388608 END",
    )
    op.drop_constraint(
        op.f("ck_analytics_runs_bound_canonical_result"), "analytics_runs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_bound_canonical_result"),
        "analytics_runs",
        "octet_length(canonical_result) <= CASE WHEN kind IN "
        "('performance','benchmark','income','attribution','cash_flow') "
        "THEN 33554432 ELSE 8388608 END",
    )
