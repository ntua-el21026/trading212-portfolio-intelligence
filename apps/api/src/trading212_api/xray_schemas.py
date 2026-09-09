"""Closed X-ray selectors and authorized representation ETags; no financial arithmetic."""

from __future__ import annotations

import hashlib

from fastapi import Request, Response
from trading212_api_contracts import xray as wire
from trading212_application import xray as app
from trading212_application.xray_projection import xray_public_primitive
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode
from trading212_domain.xray import XrayDimension

from .target_routes import RESPONSE_BYTE_LIMIT, _error


def xray_request(value: wire.XrayRunQuery) -> app.XrayRunRequest:
    return app.XrayRunRequest(
        snapshot_id=value.snapshot_id,
        source_cutoff_at=value.source_cutoff_at,
        currency=app.ExplicitCurrency(reporting_currency=CurrencyCode(value.reporting_currency)),
        run_id=value.run_id,
    )


def effective_exposure_query(value: wire.XrayEffectiveExposureQuery) -> app.EffectiveExposureQuery:
    options: app.Exposures | app.Paths | app.HeldFunds
    if value.view == "held_funds":
        options = app.HeldFunds()
    elif value.view == "paths":
        options = app.Paths(
            dimension=XrayDimension(value.dimension or "company"),
            normalized_known_only=value.normalized_known_only or False,
            exposure_id=value.exposure_id,
        )
    else:
        options = app.Exposures(
            dimension=XrayDimension(value.dimension or "company"),
            normalized_known_only=value.normalized_known_only or False,
        )
    return app.EffectiveExposureQuery(
        request=xray_request(value), options=options, cursor=value.cursor, limit=value.limit
    )


def etf_overlap_query(value: wire.XrayEtfOverlapQuery) -> app.EtfOverlapQuery:
    options: app.Pairs | app.CommonEntities
    if value.view == "common_entities":
        assert value.left_fund_id is not None and value.right_fund_id is not None
        options = app.CommonEntities(
            fund_ids=tuple(value.fund_ids),
            left_fund_id=value.left_fund_id,
            right_fund_id=value.right_fund_id,
        )
    else:
        options = app.Pairs(fund_ids=tuple(value.fund_ids))
    return app.EtfOverlapQuery(
        request=xray_request(value), options=options, cursor=value.cursor, limit=value.limit
    )


def constituent_snapshot_query(
    value: wire.XrayConstituentSnapshotQuery,
) -> app.ConstituentSnapshotQuery:
    return app.ConstituentSnapshotQuery(account_id=value.account_id, run_id=value.run_id)


def constituent_holdings_query(
    value: wire.XrayConstituentHoldingsQuery,
) -> app.ConstituentHoldingsQuery:
    return app.ConstituentHoldingsQuery(
        account_id=value.account_id, run_id=value.run_id, cursor=value.cursor, limit=value.limit
    )


def xray_response[T: wire.XraySchema](request: Request, value: object, schema: type[T]) -> Response:
    try:
        payload = (
            schema.model_validate(xray_public_primitive(value)).model_dump_json().encode("utf-8")
        )
    except (KeyError, TypeError, ValueError, DomainError):
        return _error(request, 500, "INTERNAL_ERROR", "The X-ray operation could not complete.")
    if len(payload) > RESPONSE_BYTE_LIMIT:
        return _error(request, 422, "RESULT_TOO_LARGE", "The requested result is too large.")
    # The service reauthorizes the complete dependency set before returning this value.
    etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
    headers = {"Cache-Control": "private, no-store", "ETag": etag}
    tags = {
        part.strip().removeprefix("W/")
        for part in request.headers.get("if-none-match", "").split(",")
    }
    if etag in tags or "*" in tags:
        return Response(status_code=304, headers=headers)
    return Response(payload, media_type="application/json", headers=headers)
