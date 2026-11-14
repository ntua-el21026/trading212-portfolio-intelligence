"""Fixed research DDL preserves the original ordered trigger/function effects."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_MIGRATION = Path("migrations/versions/20261114_0035_research_reports.py")

# Independent literal oracle from the pre-remediation migration, SHA-256
# 790f4bcb75eff2e8d5bf730f546a8aa33ea87998b50cf30610fb25ae869a8c35.
# Exact original bytes are retained outside the checkout with the Batch 2 evidence.
_UPGRADE_SQL = (
    "CREATE TRIGGER report_research_guard BEFORE INSERT OR UPDATE OR DELETE ON "
    "report_input_research_dependencies FOR EACH ROW EXECUTE FUNCTION report_research_guard()",
    "CREATE TRIGGER report_research_guard BEFORE INSERT OR UPDATE OR DELETE ON "
    "report_input_research_sources FOR EACH ROW EXECUTE FUNCTION report_research_guard()",
    "CREATE TRIGGER report_research_guard BEFORE INSERT OR UPDATE OR DELETE ON "
    "report_input_research_notes FOR EACH ROW EXECUTE FUNCTION report_research_guard()",
    "CREATE TRIGGER research_report_complete BEFORE UPDATE ON report_input_snapshots "
    "FOR EACH ROW EXECUTE FUNCTION report_research_complete()",
    "CREATE TRIGGER research_report_copy_barrier BEFORE DELETE ON research_source_payloads "
    "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()",
    "CREATE TRIGGER research_report_copy_barrier BEFORE DELETE ON research_event_payloads "
    "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()",
    "CREATE TRIGGER research_report_copy_barrier BEFORE DELETE ON research_note_payloads "
    "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()",
    "CREATE TRIGGER research_report_copy_barrier BEFORE UPDATE ON research_source_retention "
    "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()",
    "CREATE TRIGGER research_report_copy_barrier BEFORE UPDATE ON research_owner_erasure "
    "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()",
    "CREATE TRIGGER research_report_copy_barrier BEFORE UPDATE ON report_retention_work "
    "FOR EACH ROW EXECUTE FUNCTION research_report_copy_barrier()",
    "CREATE TRIGGER research_report_xray_barrier BEFORE UPDATE OR DELETE ON xray_input_snapshots "
    "FOR EACH ROW EXECUTE FUNCTION research_report_xray_barrier('input')",
    "CREATE TRIGGER research_report_xray_barrier BEFORE UPDATE OR DELETE ON xray_runs "
    "FOR EACH ROW EXECUTE FUNCTION research_report_xray_barrier('run')",
)
_DOWNGRADE_SQL = (
    "DROP TRIGGER report_research_guard ON report_input_research_dependencies",
    "DROP TRIGGER report_research_guard ON report_input_research_sources",
    "DROP TRIGGER report_research_guard ON report_input_research_notes",
    "DROP TRIGGER research_report_complete ON report_input_snapshots",
    "DROP TRIGGER research_report_copy_barrier ON research_source_payloads",
    "DROP TRIGGER research_report_copy_barrier ON research_event_payloads",
    "DROP TRIGGER research_report_copy_barrier ON research_note_payloads",
    "DROP TRIGGER research_report_copy_barrier ON research_source_retention",
    "DROP TRIGGER research_report_copy_barrier ON research_owner_erasure",
    "DROP TRIGGER research_report_copy_barrier ON report_retention_work",
    "DROP TRIGGER research_report_xray_barrier ON xray_input_snapshots",
    "DROP TRIGGER research_report_xray_barrier ON xray_runs",
    "DROP FUNCTION report_research_complete()",
    "DROP FUNCTION report_research_guard()",
    "DROP FUNCTION research_report_copy_barrier()",
    "DROP FUNCTION research_report_xray_barrier()",
    "DROP FUNCTION report_research_restricted(uuid,uuid,timestamptz)",
    "DROP FUNCTION report_research_source_restricted(uuid,uuid,timestamptz)",
    "DROP FUNCTION report_research_physical_restricted(uuid,uuid,uuid,timestamptz)",
    "DROP FUNCTION report_research_acquired_report_restricted(uuid,text,uuid,timestamptz)",
)
_FIXED_SQL_BODIES = {
    "_RIGHTS",
    "_GUARDS",
    "_PREMIUM",
    "_WITNESS",
    "_EMPTY_DOWNGRADE_GUARD",
    "_PREVIOUS_PREMIUM",
    "_PREVIOUS_WITNESS",
}


@pytest.mark.parametrize(
    ("operation", "expected"), (("upgrade", _UPGRADE_SQL), ("downgrade", _DOWNGRADE_SQL))
)
def test_research_report_ddl_is_literal_and_preserves_original_order(
    operation: str, expected: tuple[str, ...]
) -> None:
    module = ast.parse(_MIGRATION.read_text())
    function = next(
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == operation
    )
    statements = []
    for node in ast.walk(function):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.func.attr == "execute"
        ):
            continue
        assert len(node.args) == 1 and not node.keywords
        sql = node.args[0]
        if isinstance(sql, ast.Name):
            assert sql.id in _FIXED_SQL_BODIES
            continue
        assert isinstance(sql, ast.Constant) and isinstance(sql.value, str), (
            "Research DDL must be a fixed literal without identifier construction."
        )
        statements.append(sql.value)
    assert tuple(statements) == expected
