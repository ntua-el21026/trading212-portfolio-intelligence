"""The served widget CSP authorizes only its actual static script and style bytes."""

import base64
import hashlib
from html.parser import HTMLParser

from trading212_mcp.projection_widget import PROJECTION_WIDGET_HTML


class WidgetDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp = ""
        self.inline: dict[str, list[str]] = {"script": [], "style": []}
        self.active: str | None = None
        self.external: list[tuple[str, str]] = []
        self.forbidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        if tag == "meta" and fields.get("http-equiv") == "Content-Security-Policy":
            self.csp = fields.get("content") or ""
        if tag in self.inline:
            self.active = tag
            self.inline[tag].append("")
        if tag in {"form", "iframe", "object", "embed", "img", "link"}:
            self.forbidden.append(tag)
        for key, value in attrs:
            if key in {"src", "href"} and value is not None:
                self.external.append((key, value))
            if key.startswith("on"):
                self.forbidden.append(key)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.active:
            self.active = None

    def handle_data(self, data: str) -> None:
        if self.active is not None:
            self.inline[self.active][-1] += data


def test_static_document_hashes_match_restrictive_csp_and_no_remote_resources() -> None:
    document = WidgetDocument()
    document.feed(PROJECTION_WIDGET_HTML)
    assert document.external == []
    assert document.forbidden == []
    directives = {
        parts[0]: parts[1:] for item in document.csp.split(";") if (parts := item.split())
    }
    for name in (
        "default-src",
        "connect-src",
        "img-src",
        "font-src",
        "frame-src",
        "object-src",
        "base-uri",
        "form-action",
    ):
        assert directives[name] == ["'none'"]
    for name in ("script", "style"):
        assert len(document.inline[name]) == 1
        digest = base64.b64encode(
            hashlib.sha256(document.inline[name][0].encode()).digest()
        ).decode()
        assert directives[name + "-src"] == [f"'sha256-{digest}'"]
