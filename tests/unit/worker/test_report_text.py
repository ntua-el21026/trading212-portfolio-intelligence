"""Formula safety for text; CSV quoting is verified by the complete renderer tests."""

import pytest
from trading212_worker.report_renderers.text import csv_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("initiator", tuple("=+-@\uff1d\uff0b\uff0d\uff20"))
@pytest.mark.parametrize("prefix", ("", " ", "\ufeff", "\x01 ", "\u200b"))
def test_formula_initiators_are_neutralized_without_dropping_original_text(
    initiator: str, prefix: str
) -> None:
    value = prefix + initiator + 'SUM(1,2);"ordinary text"'
    assert csv_text(value) == "'" + value


@pytest.mark.parametrize("prefix", ("\t", "\r", "\n"))
def test_initial_spreadsheet_control_characters_are_neutralized(prefix: str) -> None:
    value = prefix + "ordinary text"
    assert csv_text(value) == "'" + value


@pytest.mark.parametrize("value", ("", "  ", "ordinary", "άλφα €", 'a,"b"\nc', "ABC-123"))
def test_safe_text_remains_unchanged(value: str) -> None:
    assert csv_text(value) == value
