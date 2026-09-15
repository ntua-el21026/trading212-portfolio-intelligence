"""Projection registration leaves every original tool and resource byte-equivalent."""

import hashlib
import json
from typing import Any

import pytest
from mcp.server.lowlevel.helper_types import ReadResourceContents
from trading212_mcp import server as module
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.contract


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def test_original_32_descriptors_seven_resources_and_resource_contents_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
    )

    # Keep this projection-only compatibility comparison on its original scope;
    # the final research test independently covers its exact authorized UI deltas.
    def absent(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(module, "register_research_tools", absent)
    monkeypatch.setattr(module, "register_analysis_widgets", absent)
    extended = module.create_runtime(security_settings=settings).server

    monkeypatch.setattr(module, "register_projection_tools", absent)
    original = module.create_runtime(security_settings=settings).server
    previous, current = await original.list_tools(), await extended.list_tools()
    assert len(previous) == 32 and len(current) == 36
    assert [item.name for item in current[:32]] == [item.name for item in previous]
    assert [
        fingerprint(item.model_dump(mode="json", by_alias=True, exclude_none=True))
        for item in current[:32]
    ] == [
        fingerprint(item.model_dump(mode="json", by_alias=True, exclude_none=True))
        for item in previous
    ]
    previous_resources, current_resources = (
        await original.list_resources(),
        await extended.list_resources(),
    )
    assert len(previous_resources) == 7 and len(current_resources) == 8
    for old, new in zip(previous_resources, current_resources[:7], strict=True):
        assert fingerprint(
            old.model_dump(mode="json", by_alias=True, exclude_none=True)
        ) == fingerprint(new.model_dump(mode="json", by_alias=True, exclude_none=True))
        old_contents, new_contents = (
            list(await original.read_resource(str(old.uri))),
            list(await extended.read_resource(str(new.uri))),
        )
        assert len(old_contents) == len(new_contents)
        for left, right in zip(old_contents, new_contents, strict=True):
            assert isinstance(left, ReadResourceContents) and isinstance(
                right, ReadResourceContents
            )
            assert str(left.content).encode() == str(right.content).encode()
