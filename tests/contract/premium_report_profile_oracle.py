"""Independent pre-profile contracts permit only the ADR-0026 additive boundary."""

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).with_name("fixtures")
PROFILE_TWO = json.loads((FIXTURES / "premium-report-profile2-baseline.json").read_text())


def assert_profiled_path(path: str, current: dict[str, Any]) -> None:
    expected = deepcopy(PROFILE_TWO["paths"][path])
    for operation in expected.values():
        parameters = operation.setdefault("parameters", [])
        parameters.insert(
            next(
                (i for i, item in enumerate(parameters) if item["in"] == "header"), len(parameters)
            ),
            {
                "name": "profile",
                "in": "query",
                "required": False,
                "schema": {
                    "enum": ["report_sections_v2", "report_sections_v3"],
                    "type": "string",
                    "default": "report_sections_v2",
                    "title": "Profile",
                },
            },
        )
        if operation["operationId"] == "generate_premium_portfolio_report":
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/GeneratePremiumReportRequest"}
            operation["requestBody"]["content"]["application/json"]["schema"] = {
                "anyOf": [schema, {"$ref": schema["$ref"] + "V3"}],
                "title": "Body",
            }
        for status, response in operation["responses"].items():
            if status not in ("200", "202") or "content" not in response:
                continue
            content = response["content"].get("application/json")
            if content is None:
                continue
            schema = content["schema"]
            if schema.get("$ref") not in {
                "#/components/schemas/PremiumReportJobStatus",
                "#/components/schemas/PremiumReportPage",
                "#/components/schemas/PremiumReportManifest",
            }:
                continue
            content["schema"] = {
                "anyOf": [schema, {"$ref": schema["$ref"] + "V3"}],
                "title": "Response " + operation["operationId"].replace("_", " ").title(),
            }
    assert current == expected, path


def client_declarations(value: str) -> dict[str, str]:
    matches = list(re.finditer(r"^export (?:const|type|class) ([A-Za-z0-9_]+)", value, re.M))
    return {
        match.group(1): value[
            match.start() : matches[index + 1].start() if index + 1 < len(matches) else len(value)
        ].strip()
        for index, match in enumerate(matches)
    }


def assert_profile_two_client_declarations(original_client_sha256: str) -> None:
    baseline = json.loads(
        (FIXTURES / "premium-report-profile2-client-declarations.json").read_text()
    )
    assert baseline["original_client_sha256"] == original_client_sha256
    declarations = client_declarations(Path(baseline["path"]).read_text())
    query_addition = '  profile: z.enum(["report_sections_v2", "report_sections_v3"]).optional(),\n'
    for name, expected in baseline["declarations"].items():
        current = declarations[name]
        if name in {
            "get_premium_report_statusQuerySchema",
            "list_premium_reportsQuerySchema",
            "get_premium_report_manifestQuerySchema",
            "create_premium_report_download_grantQuerySchema",
        }:
            assert current.count(query_addition) == 1
            current = current.replace(query_addition, "")
        assert sha256(current.encode()).hexdigest() == expected, name
