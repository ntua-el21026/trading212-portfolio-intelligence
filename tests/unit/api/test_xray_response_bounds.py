"""Bounded presentation envelopes; these synthetic shapes are not calculation evidence."""

from copy import deepcopy
from typing import Any
from uuid import UUID

from starlette.requests import Request
from trading212_api.target_routes import RESPONSE_BYTE_LIMIT
from trading212_api.xray_schemas import xray_response
from trading212_api_contracts import xray as wire
from trading212_application.xray_projection import xray_public_primitive

from tests.unit.api.xray_factories import NOW, exposures, money, ratio


def identifier(value: int) -> str:
    return str(UUID(int=value))


def maximal_proof_page() -> dict[str, Any]:
    """Use full proof bounds and conservative metadata bounds for a singleton page."""
    value: dict[str, Any] = xray_public_primitive(exposures())
    references = [identifier(index + 1) for index in range(256)]
    source = {
        "kind": "identity",
        "subject_id": identifier(999),
        "content_digest": "a" * 64,
        "source_at": NOW.isoformat(),
        "first_observed_at": NOW.isoformat(),
        "provider_id": "provider-" + "x" * 110,
        "provider_name": "𐍈" * 300,
        "license_version_id": identifier(998),
        "confidence": "0.999999999999999999",
        "quality": "stale",
    }
    sources = [{**source, "id": reference} for reference in references]
    residual = {
        "key": "r" * 512,
        "value": "0",
        "currency": "EUR",
        "kind": "parent_child",
        "consumer_key": "c" * 512,
        "child_count": 10000,
        "parent_separately_rounded": True,
    }
    value["context"].update(
        sources=sources[:64],
        source_count=256,
        source_omitted_count=192,
        warnings=[
            {
                "code": "stale_source",
                "reason": None,
                "source_reference_ids": references[:64],
                "source_count": 256,
                "source_omitted_count": 192,
                # Production warnings each identify at most one path.
                "path_keys": ["p" * 512],
                "path_count": 1,
                "path_omitted_count": 0,
            }
            for _ in range(64)
        ],
        warning_count=100000,
        warning_omitted_count=99936,
        residuals=[residual] * 64,
        residual_count=100000,
        residual_omitted_count=99936,
    )
    value["summary"]["top_concentrations"] = [
        {
            "count": count,
            "entity_ids": references[:count],
            "weight": xray_public_primitive(ratio("1")),
        }
        for count in range(1, 51)
    ]
    value["summary"]["thresholds"] = [
        {
            "metric": "m" * 120,
            "breached": None,
            "reason": "unconfigured",
            "bound": "lower_bound",
        }
        for _ in range(52)
    ]
    value["dimension_residuals"] = [residual] * 8
    root = identifier(1001)
    path = {
        "id": identifier(1000),
        "key": "p" * 512,
        "root_key": f"position:{root}",
        "root": {
            "position_id": root,
            "instrument_id": identifier(1002),
            "listing_id": identifier(1003),
        },
        "instrument_id": identifier(1004),
        "entity_id": identifier(1005),
        "name": "𐍈" * 300,
        "explicit_cash": False,
        "unresolved_reason": None,
        "fund_edges": [
            {
                "origin": "holding",
                "fund_instrument_id": identifier(1010 + offset),
                "mapping_id": identifier(1020 + offset),
                "candidate_id": identifier(1030 + offset),
                "holding_id": identifier(1040 + offset),
                "weight": "0.999999999999999999",
            }
            for offset in range(4)
        ],
        "reporting_value": xray_public_primitive(money("1")),
        "absolute_weight": xray_public_primitive(ratio("0.01")),
        "relative_weight": xray_public_primitive(ratio("1")),
        "normalized_known_weight": xray_public_primitive(ratio("0.01")),
        "classification": {
            "dimension": "company",
            "bucket_key": "b" * 512,
            "decision_key": "d" * 512,
            "reason": None,
            "confidence": None,
        },
        "identity_decision_ids": references,
        "source_reference_ids": references,
        "sources": sources,
        "residuals": [residual] * 16,
        "quality": "stale",
        "confidence": None,
    }
    value.pop("exposures")
    value.update(
        view="paths",
        paths={"items": [path], "next_cursor": "retained-next", "limit": 1, "total": 100},
    )

    def fill_metric_previews(item: Any) -> None:
        if isinstance(item, dict):
            if "availability" in item:
                item.update(
                    source_reference_ids=references[:64],
                    source_count=100000,
                    source_omitted_count=99936,
                )
            for child in item.values():
                fill_metric_previews(child)
        elif isinstance(item, list):
            for child in item:
                fill_metric_previews(child)

    fill_metric_previews(value)
    return value


def test_complete_maximum_singleton_proof_fits_without_truncating_path_evidence() -> None:
    payload = maximal_proof_page()
    validated = wire.XrayPathsResponse.model_validate(payload)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = xray_response(request, payload, wire.XrayPathsResponse)
    assert response.status_code == 200
    assert len(response.body) <= RESPONSE_BYTE_LIMIT
    assert len(validated.paths.items[0].sources) == 256
    assert len(validated.paths.items[0].identity_decision_ids) == 256


def test_oversized_proof_page_is_rejected_and_its_smaller_page_remains_reachable() -> None:
    payload = maximal_proof_page()
    path = payload["paths"]["items"][0]
    payload["paths"].update(
        items=[{**deepcopy(path), "id": identifier(2000 + index)} for index in range(100)],
        limit=100,
        next_cursor=None,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = xray_response(request, payload, wire.XrayPathsResponse)
    assert response.status_code == 422
    assert b"RESULT_TOO_LARGE" in response.body
    payload["paths"].update(items=[path], limit=1, next_cursor="retained-next")
    assert xray_response(request, payload, wire.XrayPathsResponse).status_code == 200
