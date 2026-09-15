"""Scenario additions preserve all previously delivered tool and resource bytes."""

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from mcp.server.lowlevel.helper_types import ReadResourceContents
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.contract


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def baseline() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("tests/contract/fixtures/pre_scenario_mcp_fingerprints.json").read_text()),
    )


async def test_previous_28_descriptors_and_six_resources_are_byte_equivalent() -> None:
    expected = baseline()
    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        )
    ).server
    tools = await server.list_tools()
    assert tuple(item.name for item in tools[:28]) == tuple(expected["tools"])
    for tool in tools[:28]:
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert fingerprint(descriptor) == expected["tools"][tool.name], tool.name
    resources = await server.list_resources()
    assert len(resources) == 7
    assert tuple(str(item.uri) for item in resources[:6]) == tuple(expected["resources"])
    for item in resources[:6]:
        previous = expected["resources"][str(item.uri)]
        assert (
            fingerprint(item.model_dump(mode="json", by_alias=True, exclude_none=True))
            == previous["descriptor_sha256"]
        )
        contents = list(await server.read_resource(str(item.uri)))
        digests = []
        for value in contents:
            assert isinstance(value, ReadResourceContents)
            digests.append(hashlib.sha256(str(value.content).encode()).hexdigest())
        assert digests == previous["content_sha256"]
