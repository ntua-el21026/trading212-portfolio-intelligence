#!/usr/bin/env python3
"""Exercise exact evidence exceptions and inherited rules in one offline scanner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:"
    "c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
)
SOURCE = "7b102663ea193b4668924a7252180731954f4b00"
ACCEPTANCE = "docs/implementation/evidence/phase-2-p2-05-7b10266.json"
RUNTIME = "docs/implementation/evidence/phase-2-p2-05-7b10266-runtime.json"
EVIDENCE_HASHES = {
    ACCEPTANCE: "a89625d12c03ffeda2e7e2efe121610814b3ab5246c003671b33793142cf2326",
    RUNTIME: "2ab196f1c97fb04d44743005220b660563aa66338f8c0300a9684c44bd3548b4",
}
SOURCE_FILES = tuple(
    f"packages/persistence/src/trading212_persistence/xray_{name}.py"
    for name in (
        "base",
        "exposure_reads",
        "overlap_reads",
        "publication",
        "run_store",
        "source_reads",
    )
)
LOG = "p205-persistence-candidate/pg-xray-all-store-01.log"
RULE = "jfrog-identity-token"


class PolicyCheckError(ValueError):
    """A safe failure message containing no scanner payload or synthetic credential."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise PolicyCheckError(message)


def member(value: object, *keys: str) -> object:
    for key in keys:
        require(isinstance(value, dict) and key in value, "Evidence structure differs.")
        assert isinstance(value, dict)
        value = value[key]
    return value


def checksum(value: object) -> str:
    require(isinstance(value, str), "Evidence checksum is missing.")
    assert isinstance(value, str)
    require(re.fullmatch(r"[0-9a-f]{64}", value), "Evidence checksum is invalid.")
    return value


@dataclass(frozen=True)
class ApprovedLine:
    path: str
    key: str
    value: str
    line: str


def approved_lines() -> list[ApprovedLine]:
    documents: dict[str, object] = {}
    lines: dict[str, list[str]] = {}
    for path, expected in EVIDENCE_HASHES.items():
        source = ROOT / path
        require(source.stat().st_size <= 2 * 1024 * 1024, "Evidence exceeds its bound.")
        content = source.read_bytes()
        require(hashlib.sha256(content).hexdigest() == expected, "Immutable evidence changed.")
        documents[path] = json.loads(content)
        lines[path] = content.decode("utf-8").splitlines()
    acceptance, runtime = documents[ACCEPTANCE], documents[RUNTIME]
    require(
        member(acceptance, "source_sha") == member(runtime, "source_sha") == SOURCE
        and member(acceptance, "evidence_kind") == "p205_exact_commit_acceptance"
        and member(acceptance, "result") == "passed"
        and member(runtime, "status") == "passed"
        and member(acceptance, "runtime") == runtime,
        "Accepted source/runtime binding differs.",
    )
    seal = member(
        acceptance, "assertion_map", "persistence_source_inventory", "store_guard_source_seal"
    )
    require(member(seal, "algorithm") == "SHA-256", "Source seal algorithm differs.")
    selected = [(ACCEPTANCE, key, checksum(member(seal, "files", key))) for key in SOURCE_FILES]
    selected.append((ACCEPTANCE, LOG, checksum(member(seal, "logs", LOG))))
    html = checksum(member(runtime, "checks", "web_smoke", "xray_html_sha256"))
    selected.extend((path, "xray_html_sha256", html) for path in (ACCEPTANCE, RUNTIME))
    result = []
    for path, key, value in selected:
        expected_line = f"{json.dumps(key)}: {json.dumps(value)}"
        matches = [
            line for line in lines[path] if line.strip() in {expected_line, expected_line + ","}
        ]
        require(len(matches) == 1, "Approved evidence line is missing or ambiguous.")
        result.append(ApprovedLine(path, key, value, matches[0]))
    require(len(result) == 9, "Approved evidence inventory differs.")
    return result


def fixtures(
    directory: Path, approved: list[ApprovedLine]
) -> tuple[set[tuple[str, str, int]], set[str]]:
    def write(path: str, content: str) -> None:
        destination = directory / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    for path in (ACCEPTANCE, RUNTIME):
        # Retain the actual approved lines, including their original indentation.
        write(
            "approved/" + path, "\n".join(row.line for row in approved if row.path == path) + "\n"
        )
    html = next(row for row in approved if row.path == ACCEPTANCE and row.key == "xray_html_sha256")
    changed = html.value[:-1] + ("0" if html.value[-1] != "0" else "1")
    github = "".join(("gh", "p", "_", hashlib.sha256(b"policy regression canary").hexdigest()[:36]))
    cases = {
        "changed_value/" + ACCEPTANCE: (RULE, f'"{html.key}": "{changed}"'),
        "wrong_field/" + ACCEPTANCE: (RULE, f'"xray_token": "{html.value}"'),
        "wrong_path/docs/implementation/evidence/unreviewed.json": (
            RULE,
            f'"{html.key}": "{html.value}"',
        ),
        "second_field/" + ACCEPTANCE: (RULE, f'"{html.key}": "{html.value}", "extra": true'),
        "default_rule/" + ACCEPTANCE: ("github-pat", f'"credential": "{github}"'),
    }
    expected = set()
    for path, (rule, line) in cases.items():
        write(path, "{\n  " + line + "\n}\n")
        expected.add((path, rule, 2))
    return expected, {changed, html.value, github}


def scan(directory: Path, config: Path) -> int:
    docker = shutil.which("docker")
    require(docker is not None, "Docker and the pinned local scanner image are required.")
    assert docker is not None
    name = "t212pi-gitleaks-policy-" + uuid4().hex
    output = directory / "output"
    output.mkdir(mode=0o700)
    require(
        all("," not in str(path) for path in (directory, config)),
        "Scanner mount paths must not contain commas.",
    )
    command = [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--cpus=1",
        "--memory=1g",
        "--memory-swap=1g",
        "--pids-limit=128",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--mount",
        f"type=bind,source={directory / 'fixtures'},target=/fixtures,readonly",
        "--mount",
        f"type=bind,source={config},target=/config.toml,readonly",
        "--mount",
        f"type=bind,source={output},target=/output",
        IMAGE,
        "dir",
        "/fixtures",
        "--config=/config.toml",
        "--redact",
        "--no-banner",
        "--no-color",
        "--report-format=json",
        "--report-path=/output/findings.json",
        "--exit-code=1",
    ]
    finished = False
    try:
        result = subprocess.run(  # noqa: S603
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
        finished = True
        return result.returncode
    finally:
        # Killing a timed-out Docker client does not remove its daemon-side container.
        if not finished:
            cleanup = subprocess.run(  # noqa: S603
                [docker, "rm", "--force", name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            require(cleanup.returncode == 0, "Interrupted scanner cleanup needs inspection.")


def findings(path: Path, forbidden: set[str]) -> set[tuple[str, str, int]]:
    require(
        path.is_file() and path.stat().st_size <= 2 * 1024 * 1024,
        "Scanner report is missing or oversized.",
    )
    content = path.read_bytes()
    require(
        not any(value.encode() in content for value in forbidden),
        "Scanner report was not redacted.",
    )
    values: object = json.loads(content)
    require(isinstance(values, list) and len(values) == 5, "Scanner finding count differs.")
    assert isinstance(values, list)
    result = set()
    for value in values:
        file, rule, line = (
            member(value, "File"),
            member(value, "RuleID"),
            member(value, "StartLine"),
        )
        require(
            isinstance(file, str)
            and isinstance(rule, str)
            and type(line) is int
            and member(value, "EndLine") == line
            and member(value, "Secret") == "REDACTED",
            "Scanner finding structure or redaction differs.",
        )
        assert isinstance(file, str) and isinstance(rule, str) and isinstance(line, int)
        relative = PurePosixPath(file.removeprefix("/fixtures/"))
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "Scanner finding path differs.",
        )
        result.add((relative.as_posix(), rule, line))
    require(len(result) == 5, "Scanner findings contain duplicates.")
    return result


def main() -> int:
    """Check real scanner behavior without accepting arbitrary scanner arguments."""
    try:
        approved = approved_lines()
        policy = (ROOT / ".gitleaks.toml").read_bytes()
        with TemporaryDirectory(prefix="t212pi-gitleaks-policy-") as temporary:
            directory = Path(temporary)
            config = directory / "config.toml"
            config.write_bytes(policy)
            expected, forbidden = fixtures(directory / "fixtures", approved)
            require(
                scan(directory, config) == 1, "Scanner did not detect the required negative cases."
            )
            require(
                findings(directory / "output/findings.json", forbidden) == expected,
                "Scanner suppressed an unapproved finding or rejected approved evidence.",
            )
        print(
            json.dumps(
                {
                    "result": "passed",
                    "approved_lines": 9,
                    "detected_negative_cases": 5,
                    "config_sha256": hashlib.sha256(policy).hexdigest(),
                    "scanner_image": IMAGE,
                }
            )
        )
        return 0
    except PolicyCheckError as error:
        print(f"Gitleaks policy regression failed: {error}")
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        print("Gitleaks policy regression could not complete; scanner output was suppressed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
