"""Canonical PDF assertions survive actual page breaks without losing record scope."""

from io import BytesIO

import pytest
from pypdf import PdfReader
from trading212_worker.report_renderers.pdf import _Layout

from tests.report_pdf import report_body_text
from tests.unit.worker.test_private_report_renderers import Guard

pytestmark = pytest.mark.unit


class PdfSink(BytesIO):
    @property
    def byte_length(self) -> int:
        return len(self.getvalue())


@pytest.mark.parametrize("split", ["record_key", "wrapped_key", "wrapped_value"])
def test_actual_page_break_preserves_record_identity_and_exact_metric(split: str) -> None:
    sink = PdfSink()
    layout = _Layout(sink, Guard())
    key = "canonical." + "p" * 160 if split == "wrapped_key" else "canonical.path"
    amount = "1234567890" * 12 + ".000000000000000001"
    value = amount if split == "wrapped_value" else "12.34"
    if split == "record_key":
        layout.y = 70
    layout.text("Record: xray.path.2", bold=True)
    if split == "wrapped_key":
        layout.y = 70
    layout.text(f"Key: {key}", indent=10)
    if split == "wrapped_value":
        layout.y = 70
    layout.text(f"Reporting value: {value} EUR [bound: xray.bound.exact.false]", indent=10)
    layout.finish()
    pages = [page.extract_text() for page in PdfReader(BytesIO(sink.getvalue())).pages]
    assert len(pages) == 2
    expected = f"Record:xray.path.2Key:{key}Reportingvalue:{value}EUR[bound:xray.bound.exact.false]"
    assert expected not in "".join("\n".join(pages).split())
    body = "".join(report_body_text(pages).split())
    assert body.count("Record:xray.path.2Key:") == 1
    assert body == expected


def test_page_framing_removal_preserves_identical_body_text() -> None:
    header = "PORTFOLIO INTELLIGENCE"
    footer = "Private financial information | Canonical values, no execution"
    body = f"Record: fixture\n{header}\n{footer}\n1\nRecord: fixture"
    assert report_body_text([f"{header}\n{body}\n{footer}\n1\n"]) == body


@pytest.mark.parametrize(
    "pages",
    [
        [],
        ["PORTFOLIO INTELLIGENCE\n1\n"],
        ["Unexpected header\nPrivate financial information | Canonical values, no execution\n1\n"],
        ["PORTFOLIO INTELLIGENCE\nUnexpected footer\n1\n"],
        [
            "PORTFOLIO INTELLIGENCE\n"
            "Private financial information | Canonical values, no execution\n2\n"
        ],
    ],
)
def test_missing_or_changed_page_framing_rejects(pages: list[str]) -> None:
    with pytest.raises(AssertionError):
        report_body_text(pages)
