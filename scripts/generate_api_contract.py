"""Generate or verify the committed deterministic Phase 1 OpenAPI document."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from trading212_api.main import create_app
from trading212_api_contracts.typescript import render_target_client
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/openapi/phase1-v1.json"
TARGET_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/targets.generated.ts"


def render_contract() -> str:
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("localhost",),
        )
    )
    return json.dumps(application.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    rendered = render_contract()
    pnpm = shutil.which("pnpm")
    corepack = shutil.which("corepack")
    if pnpm is not None:
        package_manager = [pnpm]
    elif corepack is not None:
        package_manager = [corepack, "pnpm"]
    else:
        parser.error("pnpm or Corepack is required for the generated client; run bootstrap")
    client = subprocess.run(  # noqa: S603
        [*package_manager, "exec", "prettier", "--stdin-filepath", str(TARGET_OUTPUT)],
        cwd=REPOSITORY_ROOT,
        input=render_target_client(json.loads(rendered)),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if arguments.check:
        if not arguments.output.is_file():
            parser.error(f"contract artifact is missing: {arguments.output}")
        if arguments.output.read_text(encoding="utf-8") != rendered:
            parser.error("committed OpenAPI artifact is stale; regenerate it")
        if not TARGET_OUTPUT.is_file() or TARGET_OUTPUT.read_text(encoding="utf-8") != client:
            parser.error("committed target client is stale; regenerate it")
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    TARGET_OUTPUT.write_text(client, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
