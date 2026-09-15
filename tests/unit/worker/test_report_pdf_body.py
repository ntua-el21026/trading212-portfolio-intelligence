"""Canonical PDF assertions survive actual page breaks without losing record scope."""

from dataclasses import replace
from io import BytesIO

import pytest
from pypdf import PdfReader
from trading212_application.reports import ReportRenderError
from trading212_domain.report_projection_schema import GOAL_REPORT_TABLES, PROJECTION_REPORT_TABLES
from trading212_domain.reports import ReportFailureCode, ReportSection
from trading212_worker.report_renderers.pdf import _analytical_order, _Layout

from tests.report_pdf import report_body_text
from tests.unit.worker.test_private_report_renderers import Guard
from tests.unit.worker.test_report_profile_decoder import manifests

pytestmark = pytest.mark.unit


def test_projection_pdf_orders_both_new_sections_and_rejects_cross_section_tables() -> None:
    descriptors = manifests()[3].document.tables
    for section, tables in (
        (ReportSection.PROJECTION, PROJECTION_REPORT_TABLES),
        (ReportSection.GOAL, GOAL_REPORT_TABLES),
    ):
        actual = sorted(
            (descriptor for descriptor in descriptors if descriptor.section is section),
            key=_analytical_order,
        )
        assert tuple(descriptor.table for descriptor in actual) == tables
        other = (
            ReportSection.GOAL if section is ReportSection.PROJECTION else ReportSection.PROJECTION
        )
        with pytest.raises(ReportRenderError) as caught:
            _analytical_order(replace(actual[0], section=other))
        assert caught.value.code is ReportFailureCode.INVALID_INPUT


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
