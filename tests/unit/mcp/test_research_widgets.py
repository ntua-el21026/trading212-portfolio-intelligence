"""Actual static bytes authorize only the three packaged offline widgets."""

import base64
import hashlib

import pytest
from trading212_mcp.allocation_widget import ALLOCATION_WIDGET_HTML
from trading212_mcp.drift_widget import DRIFT_WIDGET_HTML
from trading212_mcp.research_widget import RESEARCH_WIDGET_HTML

from tests.unit.mcp.test_projection_widget import WidgetDocument


@pytest.mark.parametrize("html", [ALLOCATION_WIDGET_HTML, DRIFT_WIDGET_HTML, RESEARCH_WIDGET_HTML])
def test_no_remote_code_or_content_html_and_exact_csp_hashes(html: str) -> None:
    document = WidgetDocument()
    document.feed(html)
    assert document.external == []
    assert document.forbidden == []
    directives = {
        parts[0]: parts[1:] for item in document.csp.split(";") if (parts := item.split())
    }
    for key in (
        "default-src",
        "connect-src",
        "img-src",
        "font-src",
        "frame-src",
        "object-src",
        "base-uri",
        "form-action",
    ):
        assert directives[key] == ["'none'"]
    for key in ("script", "style"):
        assert len(document.inline[key]) == 1
        digest = base64.b64encode(
            hashlib.sha256(document.inline[key][0].encode()).digest()
        ).decode()
        assert directives[key + "-src"] == [f"'sha256-{digest}'"]
    for unsafe in (
        "innerHTML",
        "eval(",
        "localStorage",
        "sessionStorage",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert unsafe not in html
    assert "event.source!==window.parent" in html and "ui/notifications/tool-input-partial" in html
    assert "ui/resource-teardown" in html and "tools/call" in html and "15000" in html
