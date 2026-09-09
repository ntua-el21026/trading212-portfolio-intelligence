"""HTTP selectors resolve into the same immutable application request for every view."""

from trading212_api.xray_schemas import (
    constituent_holdings_query,
    constituent_snapshot_query,
    effective_exposure_query,
    etf_overlap_query,
)
from trading212_api_contracts import xray as wire
from trading212_application import xray as app
from trading212_domain.xray import XrayDimension

from tests.unit.analytics.source_factories import uid
from tests.unit.test_xray_wire_queries import request


def test_exposure_defaults_and_explicit_normalization_share_economic_request() -> None:
    plain = effective_exposure_query(wire.XrayEffectiveExposureQuery.model_validate(request()))
    normalized = effective_exposure_query(
        wire.XrayEffectiveExposureQuery.model_validate(
            {**request(), "dimension": "sector", "normalized_known_only": "true"}
        )
    )
    assert plain.request == normalized.request
    assert (
        isinstance(plain.options, app.Exposures)
        and plain.options.dimension is XrayDimension.COMPANY
    )
    assert plain.options.normalized_known_only is False
    assert isinstance(normalized.options, app.Exposures)
    assert normalized.options.dimension is XrayDimension.SECTOR
    assert normalized.options.normalized_known_only is True


def test_path_discovery_and_pair_views_preserve_snapshot_cutoff_currency_and_run_pin() -> None:
    values = {**request(), "run_id": uid(2), "cursor": "opaque", "limit": "3"}
    path = effective_exposure_query(
        wire.XrayEffectiveExposureQuery.model_validate(
            {**values, "view": "paths", "exposure_id": uid(3)}
        )
    )
    discovery = effective_exposure_query(
        wire.XrayEffectiveExposureQuery.model_validate({**values, "view": "held_funds"})
    )
    pairs = etf_overlap_query(
        wire.XrayEtfOverlapQuery.model_validate({**values, "fund_ids": [uid(6), uid(5)]})
    )
    common = etf_overlap_query(
        wire.XrayEtfOverlapQuery.model_validate(
            {
                **values,
                "fund_ids": [uid(6), uid(5)],
                "view": "common_entities",
                "left_fund_id": uid(6),
                "right_fund_id": uid(5),
            }
        )
    )
    assert path.request == discovery.request == pairs.request == common.request
    assert path.cursor == discovery.cursor == pairs.cursor == common.cursor == "opaque"
    assert path.limit == discovery.limit == pairs.limit == common.limit == 3
    assert isinstance(path.options, app.Paths) and path.options.exposure_id == uid(3)
    assert isinstance(discovery.options, app.HeldFunds)
    assert isinstance(pairs.options, app.Pairs) and pairs.options.fund_ids == (uid(5), uid(6))
    assert isinstance(common.options, app.CommonEntities) and common.options.left_fund_id == uid(5)


def test_source_diagnostics_do_not_invent_account_scope() -> None:
    direct = constituent_snapshot_query(wire.XrayConstituentSnapshotQuery())
    assert direct.account_id is None and direct.run_id is None
    scoped = constituent_holdings_query(
        wire.XrayConstituentHoldingsQuery(
            account_id=uid(1), run_id=uid(2), cursor="signed", limit=2
        )
    )
    assert (scoped.account_id, scoped.run_id, scoped.cursor, scoped.limit) == (
        uid(1),
        uid(2),
        "signed",
        2,
    )
