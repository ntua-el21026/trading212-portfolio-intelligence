"""Real populated0029 migration, repeated0030 upgrade and reversible empty schema."""

from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from trading212_persistence.aggregation_models import AGGREGATION_MODELS

from tests.integration.test_migrations import database_engine as database_engine

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_aggregate_populated_upgrade_repeat_and_empty_downgrade(database_engine: Engine) -> None:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", database_engine.url.render_as_string(hide_password=False)
    )
    head = set(inspect(database_engine).get_table_names())
    command.check(config)
    command.downgrade(config, "20260915_0029")
    owner = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO owners(id,display_name) VALUES(:id,'Aggregate predecessor owner')"),
            {"id": owner},
        )
    before = set(inspect(database_engine).get_table_names())
    command.upgrade(config, "20260915_0030")
    command.upgrade(config, "20260915_0030")
    actual = set(inspect(database_engine).get_table_names())
    assert actual - before == {str(model.__tablename__) for model in AGGREGATION_MODELS}
    with database_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT display_name FROM owners WHERE id=:id"), {"id": owner})
            == "Aggregate predecessor owner"
        )
        assert connection.scalar(text("SELECT aggregate_q18_ratio(1,3)")) == Decimal(
            "0.333333333333333333"
        )
        assert connection.scalar(
            text("SELECT aggregate_q18_ratio(5,2000000000000000000)")
        ) == Decimal("0.000000000000000002")
        assert connection.scalar(
            text("SELECT aggregate_q18_ratio(7,2000000000000000000)")
        ) == Decimal("0.000000000000000004")
    command.downgrade(config, "20260915_0029")
    assert set(inspect(database_engine).get_table_names()) == before
    command.upgrade(config, "head")
    command.check(config)
    assert set(inspect(database_engine).get_table_names()) == head
