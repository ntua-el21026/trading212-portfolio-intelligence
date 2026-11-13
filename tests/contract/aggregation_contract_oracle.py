"""Permit only the ADR-0034 registry and the accepted saved FX reference read."""

import re
from hashlib import sha256
from pathlib import Path
from typing import Any

AGGREGATION_ADDITIONS = {
    "list_aggregate_selections": ("get", "/api/v1/aggregate-selections"),
    "create_aggregate_selection": ("post", "/api/v1/aggregate-selections"),
    "get_aggregate_selection": ("get", "/api/v1/aggregate-selections/{selection_id}"),
    "list_aggregate_runs": ("get", "/api/v1/aggregate-selections/{selection_id}/runs"),
    "create_aggregate_run": ("post", "/api/v1/aggregate-selections/{selection_id}/runs"),
    "get_aggregate_run": ("get", "/api/v1/aggregate-runs/{run_id}"),
    "list_fx_observation_references": (
        "get",
        "/api/v1/fx-snapshots/{snapshot_id}/observation-references",
    ),
}


def assert_aggregation_additions(document: dict[str, Any]) -> None:
    actual = {
        operation["operationId"]: (method, path)
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
        if "aggregate" in operation.get("tags", [])
        or operation["operationId"] == "list_fx_observation_references"
    }
    assert actual == AGGREGATION_ADDITIONS
    assert len({path for _, path in actual.values()}) == 5


def assert_pre_aggregation_source_client(original_sha256: str) -> None:
    """Keep the original byte fingerprint after removing only the authorized additions.

    The original fingerprint remains in pre_scenario_api_fingerprints.json. The
    new read is specified in docs/verification/FX-OBSERVATION-REFERENCE-READ.md;
    its closed DTOs and fixed GET are independently checked by its contract tests.
    Generated-client equality against canonical OpenAPI remains a separate gate.
    """
    current = Path("packages/api-contracts/src/sources.generated.ts").read_text()
    declarations = re.compile(r"^export (?:const|type|class) ([A-Za-z0-9_]+)", re.M)
    matches = list(declarations.finditer(current))
    additions = {
        "list_fx_observation_referencesQuerySchema",
        "list_fx_observation_referencesQuery",
        "FxObservationReferenceSchema",
        "FxObservationReference",
        "FxObservationReferencePageSchema",
        "FxObservationReferencePage",
    }
    assert sorted(match[1] for match in matches if match[1] in additions) == sorted(additions)
    for index in reversed(range(len(matches))):
        match = matches[index]
        if match[1] in additions:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(current)
            current = current[: match.start()] + current[end:]
    method = re.compile(
        r"^  async list_fx_observation_references\(\n.*?(?=^  async list_fx_observations\()",
        re.M | re.S,
    )
    assert len(method.findall(current)) == 1
    current = method.sub("", current)
    assert sha256(current.encode()).hexdigest() == original_sha256
