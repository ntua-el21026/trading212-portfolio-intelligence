"""Generate the additive OpenAPI contract and bounded fixed-purpose web clients."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from trading212_api.main import create_app
from trading212_api_contracts.typescript import (
    render_alert_client,
    render_historical_client,
    render_owner_layout_client,
    render_planning_client,
    render_premium_provider_client,
    render_premium_report_client,
    render_projection_client,
    render_report_client,
    render_research_client,
    render_risk_client,
    render_scenario_client,
    render_source_client,
    render_target_client,
    render_xray_client,
)
from trading212_application.services import SyntheticPortfolioService
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/openapi/phase1-v1.json"
TARGET_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/targets.generated.ts"
PLANNING_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/planning.generated.ts"
HISTORICAL_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/historical.generated.ts"
XRAY_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/xray.generated.ts"
SOURCE_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/sources.generated.ts"
REPORT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/reports.generated.ts"
PREMIUM_REPORT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/premium-reports.generated.ts"
ALERT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/alerts.generated.ts"
RISK_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/risk.generated.ts"
SCENARIO_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/scenarios.generated.ts"
PROJECTION_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/projections.generated.ts"
OWNER_LAYOUT_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/owner-layouts.generated.ts"
RESEARCH_OUTPUT = REPOSITORY_ROOT / "packages/api-contracts/src/research.generated.ts"
PREMIUM_PROVIDER_OUTPUT = (
    REPOSITORY_ROOT / "packages/api-contracts/src/premium-providers.generated.ts"
)


def render_contract() -> str:
    application = create_app(
        service=SyntheticPortfolioService(),
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("localhost",),
        ),
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
    clients: dict[Path, str] = {}
    contract = json.loads(rendered)
    for output, render in (
        (TARGET_OUTPUT, render_target_client),
        (PLANNING_OUTPUT, render_planning_client),
        (SOURCE_OUTPUT, render_source_client),
        (HISTORICAL_OUTPUT, render_historical_client),
        (XRAY_OUTPUT, render_xray_client),
        (REPORT_OUTPUT, render_report_client),
        (PREMIUM_REPORT_OUTPUT, render_premium_report_client),
        (ALERT_OUTPUT, render_alert_client),
        (RISK_OUTPUT, render_risk_client),
        (SCENARIO_OUTPUT, render_scenario_client),
        (PROJECTION_OUTPUT, render_projection_client),
        (RESEARCH_OUTPUT, render_research_client),
        (OWNER_LAYOUT_OUTPUT, render_owner_layout_client),
        (PREMIUM_PROVIDER_OUTPUT, render_premium_provider_client),
    ):
        clients[output] = subprocess.run(  # noqa: S603
            [*package_manager, "exec", "prettier", "--stdin-filepath", str(output)],
            cwd=REPOSITORY_ROOT,
            input=render(contract),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    if arguments.check:
        if not arguments.output.is_file():
            parser.error(f"contract artifact is missing: {arguments.output}")
        if arguments.output.read_text(encoding="utf-8") != rendered:
            parser.error("committed OpenAPI artifact is stale; regenerate it")
        for output, client in clients.items():
            if not output.is_file() or output.read_text(encoding="utf-8") != client:
                parser.error(f"committed {output.name} is stale; regenerate it")
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    for output, client in clients.items():
        output.write_text(client, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
