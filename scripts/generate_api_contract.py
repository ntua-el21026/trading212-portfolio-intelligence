"""Generate or verify the committed deterministic Phase 1 OpenAPI document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading212_api.main import create_app
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/openapi/phase1-v1.json"


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
    if arguments.check:
        if not arguments.output.is_file():
            parser.error(f"contract artifact is missing: {arguments.output}")
        if arguments.output.read_text(encoding="utf-8") != rendered:
            parser.error("committed OpenAPI artifact is stale; regenerate it")
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
