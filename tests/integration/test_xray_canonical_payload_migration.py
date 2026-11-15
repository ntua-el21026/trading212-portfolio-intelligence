"""Actual bytea constraints and non-destructive 0035→0036 X-ray migration.

Canonical JSON here isolates the storage-schema boundary. It is synthetic schema
evidence, not a semantically complete X-ray calculation or report qualification;
the genuine X-ray publication/retained-reader journey is tested separately.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from trading212_domain.serialization import canonical_json
from trading212_persistence import create_database_engine
from trading212_persistence.planning_models import AnalyticsRunModel

from tests.integration.phase3_operational_fixture import evidence, task_postgres
from tests.integration.test_migrations import _add_identity_graph
from tests.integration.test_migrations import database_engine as database_engine

pytestmark = [pytest.mark.integration, pytest.mark.migrations]

_OLD = "20261114_0035"
_NEW = "20261115_0036"
_EIGHT_MIB = 8 * 1024 * 1024
_THIRTY_TWO_MIB = 32 * 1024 * 1024
_AT = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=UTC)
_COLUMNS = ("canonical_input", "canonical_result")
_OTHER_KINDS = (
    ("actual_vs_target", _EIGHT_MIB),
    ("drift", _EIGHT_MIB),
    ("performance", _THIRTY_TWO_MIB),
    ("benchmark", _THIRTY_TWO_MIB),
    ("income", _THIRTY_TWO_MIB),
    ("attribution", _THIRTY_TWO_MIB),
    ("cash_flow", _THIRTY_TWO_MIB),
)


def _constraint_name(error: IntegrityError) -> str | None:
    original = error.orig
    assert isinstance(original, psycopg.errors.CheckViolation)
    return original.diag.constraint_name


def _canonical_bytes(size: int) -> bytes:
    overhead = len(canonical_json({"synthetic_schema_boundary": ""}).encode())
    assert size >= overhead
    encoded = canonical_json({"synthetic_schema_boundary": "x" * (size - overhead)}).encode()
    assert type(encoded) is bytes and len(encoded) == size
    return encoded


def _row(owner: UUID, account: UUID, kind: str, column: str, payload: bytes) -> AnalyticsRunModel:
    assert column in _COLUMNS
    identity = canonical_json({"synthetic_row": str(uuid4())}).encode()
    canonical_input = payload if column == "canonical_input" else identity
    canonical_result = payload if column == "canonical_result" else identity
    return AnalyticsRunModel(
        id=uuid4(),
        owner_id=owner,
        broker_account_id=account,
        kind=kind,
        input_digest=sha256(canonical_input).hexdigest(),
        content_digest=sha256(canonical_result).hexdigest(),
        method_version="schema-boundary-v1",
        reporting_currency="EUR",
        valuation_at=_AT,
        source_cutoff_at=_AT,
        canonical_input=canonical_input,
        canonical_result=canonical_result,
        created_at=_AT,
    )


def _assert_retained(session: Session, row: AnalyticsRunModel, column: str, payload: bytes) -> None:
    actual_column = getattr(AnalyticsRunModel, column)
    size, digest = session.execute(
        select(
            func.octet_length(actual_column), func.encode(func.sha256(actual_column), "hex")
        ).where(AnalyticsRunModel.id == row.id)
    ).one()
    assert size == len(payload) and digest == sha256(payload).hexdigest()


@pytest.mark.parametrize("column", _COLUMNS)
@pytest.mark.parametrize("size", (_EIGHT_MIB + 1, _THIRTY_TWO_MIB))
def test_xray_schema_accepts_actual_canonical_bytes_through_thirty_two_mib(
    database_engine: Engine, column: str, size: int
) -> None:
    payload = _canonical_bytes(size)
    with Session(database_engine) as session:
        owner, _, account, _, _, _ = _add_identity_graph(session)
        row = _row(owner, account, "xray", column, payload)
        session.add(row)
        session.flush()
        _assert_retained(session, row, column, payload)
        session.rollback()


@pytest.mark.parametrize("column", _COLUMNS)
def test_xray_schema_rejects_one_actual_byte_over_limit_without_publishing(
    database_engine: Engine, column: str
) -> None:
    payload = _canonical_bytes(_THIRTY_TWO_MIB + 1)
    with Session(database_engine) as session:
        owner, _, account, _, _, _ = _add_identity_graph(session)
        before = session.scalar(select(func.count()).select_from(AnalyticsRunModel))
        with pytest.raises(IntegrityError) as rejected, session.begin_nested():
            session.add(_row(owner, account, "xray", column, payload))
            session.flush()
        assert _constraint_name(rejected.value) == f"ck_analytics_runs_bound_{column}"
        assert session.scalar(select(func.count()).select_from(AnalyticsRunModel)) == before
        session.rollback()


@pytest.mark.parametrize("column", _COLUMNS)
@pytest.mark.parametrize(("kind", "limit"), _OTHER_KINDS)
def test_every_other_analytics_kind_retains_its_actual_byte_boundary(
    database_engine: Engine, column: str, kind: str, limit: int
) -> None:
    legal = _canonical_bytes(limit)
    oversized = _canonical_bytes(limit + 1)
    with Session(database_engine) as session:
        owner, _, account, _, _, _ = _add_identity_graph(session)
        row = _row(owner, account, kind, column, legal)
        session.add(row)
        session.flush()
        _assert_retained(session, row, column, legal)
        before = session.scalar(select(func.count()).select_from(AnalyticsRunModel))
        with pytest.raises(IntegrityError) as rejected, session.begin_nested():
            session.add(_row(owner, account, kind, column, oversized))
            session.flush()
        assert _constraint_name(rejected.value) == f"ck_analytics_runs_bound_{column}"
        assert session.scalar(select(func.count()).select_from(AnalyticsRunModel)) == before
        _assert_retained(session, row, column, legal)
        session.rollback()


@pytest.fixture
def prior_xray_payload_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Engine, Config]]:
    """An exact disposable database, independent of the module boundary fixture."""
    configured = make_url(os.environ["TEST_DATABASE_URL"])
    name = "t212pi_xray_payload_migration_" + uuid4().hex[:12]
    admin = configured.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = configured.set(drivername="postgresql+psycopg", database=name).render_as_string(
        hide_password=False
    )
    engine = None
    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        with monkeypatch.context() as environment:
            environment.setenv("DATABASE_URL", url)
            command.upgrade(config, _OLD)
            engine = create_database_engine(url)
            yield engine, config
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _retained_headers(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT id,owner_id,broker_account_id,kind,input_digest,content_digest,"
                    "method_version,reporting_currency,valuation_at,source_cutoff_at,created_at,"
                    "octet_length(canonical_input),octet_length(canonical_result),"
                    "encode(sha256(canonical_input),'hex'),encode(sha256(canonical_result),'hex') "
                    "FROM analytics_runs ORDER BY id"
                )
            )
        ]


def _constraints(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT oid,conname,convalidated,pg_get_constraintdef(oid) "
                    "FROM pg_constraint WHERE conrelid='analytics_runs'::regclass "
                    "AND conname IN ('ck_analytics_runs_bound_canonical_input',"
                    "'ck_analytics_runs_bound_canonical_result') ORDER BY conname"
                )
            )
        ]


def _backup_before_schema_change(engine: Engine, *, label: str, column: str) -> None:
    """Preserve this exact synthetic database before any populated migration."""
    assert label in {"old-upgrade", "compatible-downgrade", "incompatible-downgrade"}
    assert column in _COLUMNS
    target = engine.url
    database = target.database
    assert target.drivername == "postgresql+psycopg" and target.host == "127.0.0.1"
    assert target.port == 55432 and not target.query
    assert database is not None and database.startswith("t212pi_xray_payload_migration_")
    root = Path(os.environ["T212PI_PHASE3_EVIDENCE_DIR"]).resolve()
    assert not root.is_relative_to(Path.cwd().resolve())
    directory = root / "operations-backups"
    assert not directory.is_symlink()
    directory.mkdir(mode=0o700, exist_ok=True)
    name = "xray-" + label + "-" + column.removeprefix("canonical_") + "-" + uuid4().hex[:12]
    dump, catalog = directory / (name + ".dump"), directory / (name + ".catalog.txt")
    partial = directory / (name + ".partial")
    container = task_postgres()
    with partial.open("xb") as output:
        subprocess.run(  # noqa: S603 -- fixed pg_dump and validated task-only source database.
            [
                "/usr/bin/docker",
                "exec",
                container,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--username=portfolio",
                "--dbname=" + database,
            ],
            check=True,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    partial.chmod(0o600)
    assert not dump.exists()
    partial.rename(dump)
    with dump.open("rb") as source:
        listing = subprocess.run(  # noqa: S603 -- fixed read-only catalog of the owned backup.
            ["/usr/bin/docker", "exec", "-i", container, "pg_restore", "--list"],
            check=True,
            stdin=source,
            capture_output=True,
            timeout=120,
        ).stdout
    with catalog.open("xb") as output:
        output.write(listing)
    catalog.chmod(0o600)
    assert listing and dump.stat().st_size > 0
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    headers = _retained_headers(engine)
    evidence(
        "xray-canonical-migration-backup",
        {
            "phase": label,
            "column": column,
            "source_database": database,
            "source_head": head,
            "dump": str(dump.relative_to(root)),
            "dump_bytes": dump.stat().st_size,
            "dump_sha256": sha256(dump.read_bytes()).hexdigest(),
            "catalog": str(catalog.relative_to(root)),
            "catalog_bytes": len(listing),
            "catalog_sha256": sha256(listing).hexdigest(),
            "retained_rows": len(headers),
            "retained_header_sha256": sha256(canonical_json(headers).encode()).hexdigest(),
            "synthetic_only": True,
            "raw_private_payloads_or_credentials_logged": False,
            "source_provenance": (
                "Outer actual test receipt and source manifests; no SHA is inferred."
            ),
        },
    )


@pytest.mark.parametrize("column", _COLUMNS)
def test_populated_upgrade_repeat_safe_downgrade_and_incompatible_refusal_preserve_bytes(
    prior_xray_payload_database: tuple[Engine, Config], column: str
) -> None:
    engine, config = prior_xray_payload_database
    old_xray = _canonical_bytes(_EIGHT_MIB)
    old_historical = _canonical_bytes(_THIRTY_TWO_MIB)
    with Session(engine) as session, session.begin():
        owner, _, account, _, _, _ = _add_identity_graph(session)
        session.add_all(
            (
                _row(owner, account, "xray", column, old_xray),
                _row(owner, account, "performance", column, old_historical),
                _row(owner, account, "drift", column, b"{}"),
            )
        )
    retained = _retained_headers(engine)
    assert len(retained) == 3
    _backup_before_schema_change(engine, label="old-upgrade", column=column)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == _NEW
    assert _retained_headers(engine) == retained
    assert len(_constraints(engine)) == 2 and all(row[2] is True for row in _constraints(engine))
    _backup_before_schema_change(engine, label="compatible-downgrade", column=column)
    command.downgrade(config, _OLD)
    assert _retained_headers(engine) == retained
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == _OLD
    with Session(engine) as session:
        with pytest.raises(IntegrityError) as old_bound, session.begin_nested():
            session.add(_row(owner, account, "xray", column, _canonical_bytes(_EIGHT_MIB + 1)))
            session.flush()
        assert _constraint_name(old_bound.value) == f"ck_analytics_runs_bound_{column}"
        session.rollback()
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as session, session.begin():
        session.add(_row(owner, account, "xray", column, _canonical_bytes(_EIGHT_MIB + 1)))
    before_refusal, checks_before = _retained_headers(engine), _constraints(engine)
    _backup_before_schema_change(engine, label="incompatible-downgrade", column=column)
    with pytest.raises(DBAPIError, match="X-ray canonical payload prevents downgrade"):
        command.downgrade(config, _OLD)
    assert _retained_headers(engine) == before_refusal
    assert _constraints(engine) == checks_before
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == _NEW
    command.upgrade(config, "head")
    command.check(config)
