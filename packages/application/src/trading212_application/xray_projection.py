"""Bound public provenance previews without changing retained financial results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from trading212_domain.errors import fail_validation
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode, Instant
from trading212_domain.xray import XrayMoneyMetric, XrayRatioMetric

PREVIEW_LIMIT = 64


def xray_public_primitive(value: Any) -> Any:
    """Serialize application views; metrics retain exact values and explicit omissions.

    Full provenance belongs to the canonical result. Path views separately carry
    their complete bounded proof; this preview only bounds repeated metric metadata.
    """
    if isinstance(value, (XrayMoneyMetric, XrayRatioMetric)):
        result = {
            item.name: xray_public_primitive(getattr(value, item.name))
            for item in fields(value)
            if item.name != "source_reference_ids"
        }
        refs = value.source_reference_ids
        result["source_reference_ids"] = [str(item) for item in refs[:PREVIEW_LIMIT]]
        result["source_count"] = len(refs)
        result["source_omitted_count"] = max(0, len(refs) - PREVIEW_LIMIT)
        return result
    if value is None or isinstance(
        value, (str, bool, int, float, Decimal, CurrencyCode, Instant, datetime, date, UUID, Enum)
    ):
        return to_primitive(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: xray_public_primitive(getattr(value, item.name))
            for item in fields(value)
            if item.metadata.get("serialize", True)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            fail_validation("Serialized X-ray mapping keys must be strings.")
        return {key: xray_public_primitive(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [xray_public_primitive(item) for item in value]
    fail_validation("Unsupported X-ray representation type.")
