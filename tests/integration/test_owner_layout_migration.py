"""Fresh parity, repeated upgrade, populated predecessor and guarded downgrade."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from tests.integration.test_migrations import database_engine as database_engine

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_saved_layouts_schema_parity_and_populated_predecessor(database_engine: Engine) -> None:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", database_engine.url.render_as_string(hide_password=False)
    )
    command.check(config)
    head_tables = set(inspect(database_engine).get_table_names())
    command.downgrade(config, "20260915_0028")
    owner = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO owners(id,display_name) VALUES(:id,'Existing owner before layouts')"),
            {"id": owner},
        )
    before = set(inspect(database_engine).get_table_names())
    command.upgrade(config, "20260915_0029")
    command.upgrade(config, "20260915_0029")
    inspector = inspect(database_engine)
    assert set(inspector.get_table_names()) - before == {
        "owner_layouts",
        "saved_view_versions",
        "saved_layout_widgets",
        "owner_layout_command_identities",
        "owner_layout_erasure",
    }
    assert {index["name"] for index in inspector.get_indexes("broker_connections")} >= {
        "ix_broker_connections_layout_active_owner"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("saved_layout_widgets")} == {
        "uq_saved_layout_widget_identity",
        "uq_saved_layout_widget_ordinal",
    }
    assert not {"query", "url", "amount", "financial_result", "canonical_result"} & {
        column["name"] for column in inspector.get_columns("saved_layout_widgets")
    }
    with database_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT display_name FROM owners WHERE id=:id"), {"id": owner})
            == "Existing owner before layouts"
        )
    command.downgrade(config, "20260915_0028")
    assert set(inspect(database_engine).get_table_names()) == before
    command.upgrade(config, "head")
    command.check(config)
    assert set(inspect(database_engine).get_table_names()) == head_tables
    # A permanent content-free privacy marker still blocks destructive downgrade.
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO owner_layout_erasure(owner_id,created_at) "
                "VALUES(:id,CURRENT_TIMESTAMP)"
            ),
            {"id": owner},
        )
    with pytest.raises(Exception, match=r"saved layout|owner layout|Owner layout"):
        command.downgrade(config, "20260915_0028")
