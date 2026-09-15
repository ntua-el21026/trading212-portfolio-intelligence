"""Independent exact old-tool delta oracle and all eleven offline resources."""

from typing import Any

import pytest
from mcp.server.lowlevel.helper_types import ReadResourceContents
from trading212_mcp import server as module
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.contract


async def test_original36_preserved_except_two_exact_resource_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
    )
    extended = module.create_runtime(security_settings=settings).server

    def absent(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(module, "register_research_tools", absent)
    monkeypatch.setattr(module, "register_analysis_widgets", absent)
    original = module.create_runtime(security_settings=settings).server
    old, new = await original.list_tools(), await extended.list_tools()
    assert len(old) == 36 and len(new) == 38
    attachments = {"get_direct_allocation": "allocation", "get_drift_analysis": "drift"}
    for left, right in zip(old, new[:36], strict=True):
        expected = left.model_dump(mode="json", by_alias=True, exclude_none=True)
        if left.name in attachments:
            uri = f"ui://trading212-portfolio/{attachments[left.name]}-v1.html"
            expected["_meta"] = {
                **expected["_meta"],
                "ui": {"resourceUri": uri, "visibility": ["model", "app"]},
                "openai/outputTemplate": uri,
                "openai/widgetAccessible": True,
            }
        assert right.model_dump(mode="json", by_alias=True, exclude_none=True) == expected
    previous, current = await original.list_resources(), await extended.list_resources()
    assert len(previous) == 8 and len(current) == 11
    assert {str(x.uri) for x in current[8:]} == {
        f"ui://trading212-portfolio/{x}-v1.html" for x in ("research", "allocation", "drift")
    }
    for prior_resource, current_resource in zip(previous, current[:8], strict=True):
        assert prior_resource.model_dump(
            mode="json", by_alias=True, exclude_none=True
        ) == current_resource.model_dump(mode="json", by_alias=True, exclude_none=True)
        a, b = (
            list(await original.read_resource(str(prior_resource.uri))),
            list(await extended.read_resource(str(current_resource.uri))),
        )
        assert len(a) == len(b)
        for x, y in zip(a, b, strict=True):
            assert isinstance(x, ReadResourceContents) and isinstance(y, ReadResourceContents)
            assert str(x.content).encode() == str(y.content).encode()
    for resource in current[8:]:
        assert resource.mime_type == "text/html;profile=mcp-app" and resource.meta is not None
        assert resource.meta["ui"] == {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
        }
        assert resource.meta["openai/widgetCSP"] == {"connect_domains": [], "resource_domains": []}
