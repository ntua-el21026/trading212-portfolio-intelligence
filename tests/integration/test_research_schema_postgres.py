"""Research migration parity and legacy-preserving empty downgrade/upgrade."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from tests.integration.test_migrations import database_engine as database_engine

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_research_migration_parity_and_empty_round_trip(database_engine: Engine) -> None:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", database_engine.url.render_as_string(hide_password=False)
    )
    command.check(config)
    inspector = inspect(database_engine)
    item_columns = {column["name"] for column in inspector.get_columns("research_items")}
    assert {
        "revision_id",
        "revision_digest",
        "xray_run_id",
        "xray_input_digest",
        "xray_result_digest",
        "xray_pin_digest",
        "source_cutoff_at",
        "expires_at",
    } <= item_columns
    assert (
        not {"canonical_result", "canonical_portfolio", "amount", "effective_exposure"}
        & item_columns
    )
    assert "canonical_note" not in {
        column["name"] for column in inspector.get_columns("research_note_revisions")
    }
    assert "canonical_note" in {
        column["name"] for column in inspector.get_columns("research_note_payloads")
    }
    head_tables = set(inspector.get_table_names())
    command.downgrade(config, "20260915_0024")
    before = set(inspect(database_engine).get_table_names())
    command.downgrade(config, "20260915_0023")
    without = set(inspect(database_engine).get_table_names())
    assert before - without and all(name.startswith("research_") for name in before - without)
    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260915_0023"
    command.upgrade(config, "20260915_0024")
    command.upgrade(config, "20260915_0024")
    assert set(inspect(database_engine).get_table_names()) == before
    command.upgrade(config, "head")
    command.check(config)
    assert set(inspect(database_engine).get_table_names()) == head_tables
