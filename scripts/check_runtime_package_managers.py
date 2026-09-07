#!/usr/bin/env python3
"""Execute each built runtime image and reject retained package-manager tooling."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence

RUNTIME_SERVICES = ("api", "worker", "mcp", "web", "postgres", "redis")
PROBE = r"""
failed=0
for directory in /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin /opt/venv/bin; do
    for manager in "$directory"/apt* "$directory"/dpkg* \
        "$directory"/npm "$directory"/npx "$directory"/corepack \
        "$directory"/pnpm "$directory"/pnpx "$directory"/yarn "$directory"/yarnpkg \
        "$directory"/uv "$directory"/uvx "$directory"/pip*; do
        if [ -e "$manager" ] || [ -L "$manager" ]; then
            printf 'retained package manager: %s\n' "$manager"
            failed=1
        fi
    done
done
for installation in /usr/lib/apt /usr/lib/dpkg /opt/yarn-v* \
    /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    /usr/local/lib/node_modules/pnpm /usr/local/lib/node_modules/yarn; do
    if [ -e "$installation" ] || [ -L "$installation" ]; then
        printf 'retained package manager installation: %s\n' "$installation"
        failed=1
    fi
done
if command -v python >/dev/null 2>&1; then
    if ! python -I -c '
import importlib.util
import sys
found = [name for name in ("pip", "ensurepip", "uv") if importlib.util.find_spec(name)]
for name in found:
    print("retained Python package manager module: " + name)
sys.exit(bool(found))
'; then
        failed=1
    fi
fi
if [ ! -s /var/lib/dpkg/status ]; then
    printf 'missing dpkg status metadata for vulnerability/license provenance\n'
    failed=1
fi
exit "$failed"
"""


def _docker(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("docker")
    if executable is None:
        raise FileNotFoundError("Docker CLI is unavailable")
    return subprocess.run(  # noqa: S603 -- fixed docker executable; argv never enters a shell.
        [executable, *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def compose_runtime_images() -> tuple[str, ...]:
    result = _docker(("compose", "config", "--format", "json"))
    if result.returncode:
        raise ValueError("Docker Compose configuration could not be resolved")
    config = json.loads(result.stdout)
    project_name = config["name"]
    services = config["services"]
    return tuple(
        services[name].get("image", f"{project_name}-{name}:latest") for name in RUNTIME_SERVICES
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    try:
        images = arguments or compose_runtime_images()
        failed = False
        for image in images:
            if not image or image.startswith("-"):
                raise ValueError("Expected an image reference, not a Docker option")
            inspected = _docker(("image", "inspect", "--format", "{{.Id}}", image))
            image_id = inspected.stdout.strip()
            if inspected.returncode or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                print(f"FAIL {image}: image must be built before this check", file=sys.stderr)
                failed = True
                continue
            checked = _docker(
                (
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--entrypoint",
                    "/bin/sh",
                    image_id,
                    "-c",
                    PROBE,
                )
            )
            if checked.returncode:
                print(f"FAIL {image} ({image_id})", file=sys.stderr)
                print(
                    checked.stdout.strip() or "Runtime package-manager probe failed",
                    file=sys.stderr,
                )
                failed = True
            else:
                print(f"PASS {image} ({image_id}): no package managers; dpkg metadata retained")
        return int(failed)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        print(
            f"Runtime package-manager validation unavailable: {type(exc).__name__}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
