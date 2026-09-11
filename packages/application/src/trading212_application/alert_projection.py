"""Shared finite public alert projection; no private evaluation input is exposed."""

from __future__ import annotations

from dataclasses import fields

from trading212_domain import alerts as domain
from trading212_domain.serialization import to_primitive


def alert_content(value: object) -> object:
    """Project public records without leaking owner IDs or private predicate null fields."""
    if isinstance(value, domain.AlertRecord):
        result = {field.name: alert_content(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, domain.AlertRuleVersion):
            result.pop("owner_id")
        if isinstance(value, domain.AlertPredicate):
            result = {key: item for key, item in result.items() if item is not None}
            if value.minimum_net_amount is not None:
                result["minimum_net_amount"] = to_primitive(value.minimum_net_amount.amount)
                result["currency"] = to_primitive(value.minimum_net_amount.currency)
            if value.metric is domain.AlertMetric.REPORT_TERMINAL and value.report_type is None:
                result["report_type"] = "all"
        return result
    if isinstance(value, (list, tuple)):
        return [alert_content(item) for item in value]
    return to_primitive(value)
