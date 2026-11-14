"""Explicitly task-owned operational exercises; inventories never emit row values."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from trading212_persistence.base import Base


def canonical_text_arrays(expression: str) -> str:
    """Normalize only PostgreSQL's two literal varchar-array to text-array forms."""
    quoted = r"'(?:[^']|'')*'"
    literal = (
        r"(?:"
        + quoted
        + r"::character varying(?:::text)?|\("
        + quoted
        + r"::character varying\)::text)"
    )
    arrays = re.compile(
        r"(?P<parenthesis>\()?ARRAY\[(?P<members>(?:"
        + literal
        + r")(?:,\s*"
        + literal
        + r")*)\](?(parenthesis)\))(?P<cast>::text\[\])?"
    )

    def normalized(match: re.Match[str]) -> str:
        members = re.findall(literal, match.group("members"))
        if match.group("cast") is None and any(not member.endswith("::text") for member in members):
            return match.group(0)
        values = re.findall(quoted, match.group("members"))
        assert len(values) == len(members)
        array = "ARRAY[" + ", ".join(value + "::text" for value in values) + "]"
        return (
            "(" + array + ")"
            if match.group("parenthesis") and match.group("cast") is None
            else array
        )

    return arrays.sub(normalized, expression)


def evidence(name: str, payload: dict[str, Any]) -> Path:
    root = Path(os.environ["T212PI_PHASE3_EVIDENCE_DIR"]).resolve()
    assert not root.is_relative_to(Path.cwd().resolve())
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / f"operations-{name}-{uuid4().hex}.json"
    with target.open("x", encoding="utf-8") as output:
        json.dump(payload, output, sort_keys=True, indent=2)
        output.write("\n")
    return target


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, datetime):
        assert value.tzinfo is not None
        return {"utc": value.astimezone(UTC).isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def inventory(sessions: sessionmaker[Session]) -> dict[str, Any]:
    """Hash all canonical rows and schema constraints, in stable primary-key order."""
    tables = {}
    with sessions() as session:
        for name, table in sorted(Base.metadata.tables.items()):
            digest, count = hashlib.sha256(), 0
            rows = session.execute(
                select(table).order_by(*table.primary_key), execution_options={"yield_per": 64}
            )
            for row in rows:
                encoded = json.dumps(
                    _json_value(tuple(row)), sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                count += 1
            tables[name] = {"rows": count, "sha256": digest.hexdigest()}
        head = session.scalar(text("SELECT version_num FROM alembic_version"))
        functions = tuple(
            session.execute(
                text(
                    "SELECT p.proname,pg_get_functiondef(p.oid) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.prokind='f' "
                    "ORDER BY p.proname,p.oid::regprocedure::text"
                )
            )
        )
        triggers = tuple(
            session.execute(
                text(
                    "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,false) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname"
                )
            )
        )
    engine = sessions.kw["bind"]
    schema = inspect(engine)
    actual_tables = sorted(schema.get_table_names())
    assert set(actual_tables) == set(Base.metadata.tables) | {"alembic_version"}
    constraints: dict[str, dict[str, Any]] = {
        name: {
            "columns": schema.get_columns(name),
            "primary_key": schema.get_pk_constraint(name),
            "indexes": sorted(schema.get_indexes(name), key=lambda x: str(x["name"])),
            "checks": sorted(schema.get_check_constraints(name), key=lambda x: str(x["name"])),
            "unique": sorted(schema.get_unique_constraints(name), key=lambda x: str(x["name"])),
            "foreign": sorted(schema.get_foreign_keys(name), key=lambda x: str(x["name"])),
        }
        for name in sorted(Base.metadata.tables)
    }
    descriptor = {
        "constraints": constraints,
        "functions": [tuple(row) for row in functions],
        "triggers": [tuple(row) for row in triggers],
        "public_tables": actual_tables,
    }
    raw_schema = json.dumps(
        descriptor,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode()
    for definition in constraints.values():
        for check in definition["checks"]:
            check["sqltext"] = canonical_text_arrays(check["sqltext"])
        for index in definition["indexes"]:
            options = index.get("dialect_options", {})
            predicate = options.get("postgresql_where")
            if isinstance(predicate, str):
                options["postgresql_where"] = canonical_text_arrays(predicate)
            if "expressions" in index:
                index["expressions"] = [
                    canonical_text_arrays(value) for value in index["expressions"]
                ]
    canonical_schema = json.dumps(
        descriptor,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode()
    return {
        "head": head,
        "tables": tables,
        "schema_sha256": hashlib.sha256(canonical_schema).hexdigest(),
        "raw_schema_sha256": hashlib.sha256(raw_schema).hexdigest(),
        "schema": json.loads(canonical_schema),
    }


def _task_project() -> str:
    project = os.environ.get("T212PI_PHASE3_TASK_PROJECT", "")
    if not (project.startswith("t212pi_batch2_") and project.replace("_", "").isalnum()):
        raise ValueError("Only a validated disposable Batch 2 task project is permitted.")
    return project


def _restore_target(source: Engine) -> None:
    _task_project()
    target = source.url
    if (
        target.drivername != "postgresql+psycopg"
        or target.host != "127.0.0.1"
        or target.port != 55432
        or target.query
    ):
        raise ValueError("Restore operations require the exact task PostgreSQL target.")


def task_postgres() -> str:
    project = _task_project()
    result = subprocess.run(  # noqa: S603 -- fixed Docker argv; task label is validated above.
        [
            "/usr/bin/docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=postgres",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    identifiers = result.stdout.split()
    assert len(identifiers) == 1
    inspected = subprocess.run(  # noqa: S603 -- fixed port-only inspection of the selected task.
        [
            "/usr/bin/docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Ports}}",
            identifiers[0],
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        ports = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        raise ValueError("The selected task PostgreSQL endpoint does not match.") from None
    if not isinstance(ports, dict) or ports.get("5432/tcp") != [
        {"HostIp": "127.0.0.1", "HostPort": "55432"}
    ]:
        raise ValueError("The selected task PostgreSQL endpoint does not match.")
    return identifiers[0]


def _preserve_restore_failure(
    source: Engine,
    *,
    container: str,
    target: str,
    dump: Path,
    failure: Exception,
    phase: str,
    created: bool,
) -> None:
    retained: dict[str, Any] = {
        "target": target,
        "target_creation_confirmed": created,
        "failure_type": type(failure).__name__,
        "failure_phase": phase,
        "source_dump_file": dump.name,
        "diagnostic_export_attempted": False,
        "target_removed": False,
    }

    def persist(name: str) -> Path | None:
        try:
            return evidence(name, retained)
        except Exception as error:
            disposition = (
                "removal was confirmed" if retained["target_removed"] else "was not removed"
            )
            failure.add_note(
                f"Restore target {target} {disposition}; {name} recording failed "
                f"({type(error).__name__})."
            )
            return None

    # This immutable receipt precedes every optional file read/export. Even a
    # failed diagnostic must leave the exact target and original failure known.
    initial = persist("restore-failure-quarantined")
    if initial is None or not created:
        return
    retained["quarantine_receipt"] = initial.name
    retained["diagnostic_export_attempted"] = True
    try:
        stderr = getattr(failure, "stderr", None) or b""
        if isinstance(stderr, str):
            stderr = stderr.encode()
        error_file = dump.with_suffix(".restore-error.log")
        error_file.write_bytes(stderr)
        partial = subprocess.run(  # noqa: S603 -- fixed schema-only dump of the owned target.
            [
                "/usr/bin/docker",
                "exec",
                container,
                "pg_dump",
                "--schema-only",
                "--no-owner",
                "--no-acl",
                "--username=portfolio",
                "--dbname=" + target,
            ],
            check=False,
            capture_output=True,
            timeout=120,
        )
        partial_file = dump.with_suffix(".failed-schema.sql")
        partial_file.write_bytes(partial.stdout)
        retained.update(
            source_dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
            stderr_file=error_file.name,
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            partial_schema_file=partial_file.name,
            partial_schema_sha256=hashlib.sha256(partial.stdout).hexdigest(),
            partial_schema_export_exit_code=partial.returncode,
        )
        # Do not remove an uncertain target or one whose diagnostic evidence
        # could not be retained. Successful export is recorded before disposal.
        if partial.returncode == 0 and persist("restore-failure-diagnostics") is not None:
            drop_restored(source, target)
            retained["target_removed"] = True
    except Exception as error:
        retained["diagnostic_failure_type"] = type(error).__name__
        failure.add_note(
            f"Restore target {target} remains quarantined after diagnostic failure "
            f"({type(error).__name__})."
        )
    persist("restore-failure-preserved")


def restore_empty(source: Engine, *, directory: Path) -> tuple[str, dict[str, Any]]:
    """Use pg_dump/pg_restore in the inspected task container and a new empty DB."""
    _restore_target(source)
    source_name = source.url.database
    assert source_name is not None and source_name.startswith("t212pi_xray_reads_")
    container = task_postgres()
    target_name = "t212pi_phase3_ops_" + uuid4().hex[:16]
    admin_url = source.url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    dump = directory / f"synthetic-{uuid4().hex}.dump"
    started = time.perf_counter()
    partial_dump = dump.with_suffix(".dump.partial")
    with partial_dump.open("xb") as output:
        subprocess.run(  # noqa: S603 -- fixed pg_dump; source comes from the disposable fixture.
            [
                "/usr/bin/docker",
                "exec",
                container,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--username=portfolio",
                "--dbname=" + source_name,
            ],
            check=True,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    partial_dump.rename(dump)
    absent, created, phase = False, False, "create_target"
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT count(*) FROM pg_database WHERE datname=%s", (target_name,)
            ).fetchone() == (0,)
            absent = True
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target_name))
            )
            created = True
        phase = "restore"
        with dump.open("rb") as input_file:
            subprocess.run(  # noqa: S603 -- fixed pg_restore; target is created locally above.
                [
                    "/usr/bin/docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    "--username=portfolio",
                    "--dbname=" + target_name,
                ],
                check=True,
                stdin=input_file,
                capture_output=True,
                timeout=300,
            )
        phase = "observe_dump"
        elapsed = time.perf_counter() - started
        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        return target_name, {
            "dump_sha256": digest,
            "dump_bytes": dump.stat().st_size,
            "backup_and_restore_seconds": elapsed,
            "dump_file": dump.name,
            "target_was_absent_then_created_template0": True,
        }
    except Exception as failure:
        if absent:
            _preserve_restore_failure(
                source,
                container=container,
                target=target_name,
                dump=dump,
                failure=failure,
                phase=phase,
                created=created,
            )
        raise


def drop_restored(source: Engine, name: str) -> None:
    _restore_target(source)
    assert name.startswith("t212pi_phase3_ops_") and name.replace("_", "").isalnum()
    task_postgres()
    admin_url = source.url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
