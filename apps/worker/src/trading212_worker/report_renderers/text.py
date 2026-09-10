"""Presentation-only text handling; canonical values are never recalculated."""

from __future__ import annotations

import unicodedata

CSV_ESCAPING_VERSION = "report_csv_text_v1"
_FORMULA_START = frozenset("=+-@\uff1d\uff0b\uff0d\uff20")


def csv_text(value: str) -> str:
    """Neutralize text initiators while keeping the original value in canonical JSON.

    Only text passes here: validated numeric decimal cells use their canonical
    strings directly. Spreadsheet transformations after import can undo escaping.
    """
    if value.startswith(("\t", "\r", "\n")):
        return "'" + value
    leading = 0
    for character in value:
        if character.isspace() or unicodedata.category(character).startswith("C"):
            leading += 1
        else:
            break
    if value[leading : leading + 1] in _FORMULA_START:
        return "'" + value
    return value


def label(value: str) -> str:
    """Use readable fixed schema labels without changing any authoritative value."""
    return value.replace("_", " ").replace(".", " / ").capitalize()
