"""Frozen pre-optimization base report validator from 8fa5db7.

Only independent function names/signature typing are adapted; all field type,
recursive tuple, UTC normalization, bounds and failure-order behavior is retained.
"""

from __future__ import annotations

import types
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import cast, get_args, get_origin, get_type_hints

from trading212_domain.errors import fail_validation
from trading212_domain.reports import (
    MAX_REPORT_DATASET_ROWS,
    MAX_REPORT_DOCUMENT_BYTES,
    MAX_REPORT_TEXT_CHARS,
    ReportRecord,
    report_digest,
    report_limit,
)
from trading212_domain.values import require_utc


@lru_cache(maxsize=128)
def legacy_record_hints(kind: type[ReportRecord]) -> dict[str, object]:
    return get_type_hints(kind)


def legacy_typed(value: object, annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is types.UnionType:
        return any(legacy_typed(value, part) for part in get_args(annotation))
    if origin is tuple:
        args = get_args(annotation)
        return type(value) is tuple and all(legacy_typed(item, args[0]) for item in value)
    if annotation is type(None):
        return value is None
    return isinstance(annotation, type) and type(value) is annotation


def legacy_post_init(self: ReportRecord) -> None:
    hints = legacy_record_hints(cast("type", type(self)))
    for item in fields(self):
        value = getattr(self, item.name)
        if not legacy_typed(value, hints[item.name]):
            fail_validation("A typed report field is required.", field=item.name)
        if type(value) is str:
            report_limit(len(value) <= MAX_REPORT_TEXT_CHARS, item.name)
            if item.name.endswith("digest"):
                report_digest(value, item.name)
        elif type(value) is datetime:
            object.__setattr__(self, item.name, require_utc(value))
        elif type(value) is tuple:
            report_limit(len(value) <= MAX_REPORT_DATASET_ROWS, item.name)
        elif type(value) is bytes:
            report_limit(len(value) <= MAX_REPORT_DOCUMENT_BYTES, item.name)
        elif type(value) is Decimal and not value.is_finite():
            fail_validation("Report decimals must be finite.", field=item.name)
