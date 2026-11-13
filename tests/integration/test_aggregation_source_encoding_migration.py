"""Forward correction preserves original tagged source evidence and native proof checks."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from trading212_application import aggregation as app
from trading212_domain.aggregation import AggregateActivityWindow, AggregateView
from trading212_worker.postgres_store import _json_value

from tests.integration.test_aggregation_postgres import command, prepared
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_native_source_decoders_accept_only_canonical_finite_tagged_values(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    with case.sessions.begin() as session:
        tagged_number = _json_value(Decimal("0.100000000000000001"))
        assert tagged_number == {"$decimal": "0.100000000000000001"}
        assert session.scalar(
            text("SELECT aggregate_native_source_decimal(CAST(:value AS jsonb))"),
            {"value": json.dumps(tagged_number)},
        ) == Decimal("0.100000000000000001")
        tagged_instant = _json_value(
            datetime(2026, 11, 13, 14, 34, 56, 123456, timezone(timedelta(hours=2)))
        )
        assert tagged_instant == {"$datetime": "2026-11-13T12:34:56.123456+00:00"}
        assert session.scalar(
            text("SELECT aggregate_native_source_instant(CAST(:value AS jsonb))"),
            {"value": json.dumps(tagged_instant)},
        ) == datetime(2026, 11, 13, 12, 34, 56, 123456, UTC)
        for value in (Decimal("-0"), Decimal("-0.00"), Decimal("1E+3")):
            assert (
                session.scalar(
                    text("SELECT aggregate_native_source_decimal(CAST(:value AS jsonb))"),
                    {"value": json.dumps(_json_value(value))},
                )
                == value
            )
        whole_second = datetime(2026, 11, 13, 12, 34, 56, tzinfo=UTC)
        assert _json_value(whole_second) == {"$datetime": "2026-11-13T12:34:56+00:00"}
        assert (
            session.scalar(
                text("SELECT aggregate_native_source_instant(CAST(:value AS jsonb))"),
                {"value": json.dumps(_json_value(whole_second))},
            )
            == whole_second
        )
        for function, invalid in (
            ("decimal", "1"),
            ("decimal", 1),
            ("decimal", True),
            ("decimal", {"$decimal": "1", "extra": None}),
            ("decimal", {"$decimal": 1}),
            ("decimal", {"$decimal": None}),
            ("decimal", {"$datetime": "2026-11-13T00:00:00+00:00"}),
            ("decimal", {"$decimal": "NaN"}),
            ("decimal", {"$decimal": "Infinity"}),
            ("decimal", {"$decimal": "-Infinity"}),
            ("decimal", {"$decimal": "not-a-number"}),
            ("decimal", {"$decimal": "+1"}),
            ("decimal", {"$decimal": "1E+3"}),
            ("decimal", {"$decimal": ".1"}),
            ("decimal", {"$decimal": "1."}),
            ("decimal", {"$decimal": "01"}),
            ("instant", "2026-11-13T00:00:00+00:00"),
            ("instant", {"$datetime": "2026-11-13T00:00:00"}),
            ("instant", {"$datetime": "2026-11-13T00:00:00+01:00"}),
            ("instant", {"$datetime": "2026-99-13T00:00:00+00:00"}),
            ("instant", {"$datetime": "infinity"}),
            ("instant", {"$datetime": "2026-11-13T24:00:00+00:00"}),
            ("instant", {"$datetime": "2026-11-13T00:00:60+00:00"}),
            ("instant", {"$datetime": "2026-11-13T00:00:00.1+00:00"}),
            ("instant", {"$datetime": "2026-11-13T00:00:00.12345+00:00"}),
            ("instant", {"$datetime": "2026-11-13T00:00:00.000000+00:00"}),
            ("instant", {"$datetime": "2026-11-13T00:00:00Z"}),
            ("instant", {"$datetime": None}),
            ("instant", {"$datetime": 1}),
            ("instant", {"$datetime": "2026-11-13T00:00:00+00:00", "extra": None}),
        ):
            query = (
                "SELECT aggregate_native_source_decimal(CAST(:value AS jsonb))"
                if function == "decimal"
                else "SELECT aggregate_native_source_instant(CAST(:value AS jsonb))"
            )
            with (
                pytest.raises(IntegrityError, match=r"aggregate native source .* encoding"),
                session.begin_nested(),
            ):
                session.scalar(text(query), {"value": json.dumps(invalid)})
        assert session.scalar(text("SELECT aggregate_native_source_decimal('null'::jsonb)")) is None
        assert session.scalar(text("SELECT aggregate_native_source_instant('null'::jsonb)")) is None


async def test_populated_0030_forward_upgrade_preserves_source_and_rejects_unsafe_downgrade(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = xray_read_case
    url = case.engine.url.render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("DATABASE_URL", url)
    alembic_command.downgrade(config, "20260915_0030")
    store, selected = await prepared(case, transfer_mode="mutual")
    request = replace(
        command(selected),
        activity_window=AggregateActivityWindow(
            start_at=case.now[0] - timedelta(days=1), end_at=case.now[0]
        ),
    )
    evidence_query = text(
        "SELECT id,octet_length(convert_to(sanitized_payload::text,'UTF8')),"
        "encode(sha256(convert_to(sanitized_payload::text,'UTF8')),'hex'),payload_fingerprint "
        "FROM source_records ORDER BY id"
    )
    with case.sessions() as session:
        before = session.execute(evidence_query).all()
        assert before
    with pytest.raises(app.AggregateServiceError) as old_failure:
        await store.create_run(case.principal, request)
    assert old_failure.value.code is app.AggregateErrorCode.SOURCE_UNAVAILABLE
    alembic_command.upgrade(config, "head")
    alembic_command.upgrade(config, "head")
    alembic_command.check(config)
    with case.sessions() as session:
        assert session.execute(evidence_query).all() == before
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0034"
    run = await store.create_run(case.principal, request)
    assert await store.create_run(case.principal, request) == run
    assert (
        await store.get_run(
            case.principal, run.run_id, app.AggregateRunQuery(view=AggregateView.TRANSFERS)
        )
    ).page is not None
    with pytest.raises(IntegrityError, match="empty aggregate identities"):
        alembic_command.downgrade(config, "20260915_0030")
    with case.sessions() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0034"
        assert session.execute(evidence_query).all() == before
