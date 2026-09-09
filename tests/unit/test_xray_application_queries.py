"""Application selectors preserve run, pair, currency and diagnostic scope boundaries."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from trading212_application import xray as app
from trading212_domain import CurrencyCode, DomainError
from trading212_domain.xray import XrayDimension

from tests.unit.analytics.source_factories import uid

pytestmark = pytest.mark.unit


def request() -> app.XrayRunRequest:
    return app.XrayRunRequest(
        snapshot_id=uid(1),
        source_cutoff_at=datetime(2026, 9, 1, tzinfo=UTC),
        currency=app.ExplicitCurrency(reporting_currency=CurrencyCode("EUR")),
    )


def test_complete_request_preserves_explicit_and_authorized_snapshot_currency_modes() -> None:
    explicit = request()
    assert isinstance(explicit.currency, app.ExplicitCurrency)
    derived = replace(explicit, currency=app.SnapshotCurrency())
    assert isinstance(derived.currency, app.SnapshotCurrency)
    assert derived.snapshot_id == explicit.snapshot_id
    with pytest.raises(DomainError):
        replace(explicit, currency=cast(Any, "EUR"))
    with pytest.raises(DomainError):
        replace(explicit, source_cutoff_at=datetime(2026, 9, 1))


def test_path_initial_request_requires_pin_but_continuation_can_supply_it() -> None:
    with pytest.raises(DomainError, match="retained run pin"):
        app.EffectiveExposureQuery(request=request(), options=app.Paths())
    first = app.EffectiveExposureQuery(
        request=replace(request(), run_id=uid(2)), options=app.Paths()
    )
    continued = app.EffectiveExposureQuery(request=request(), options=app.Paths(), cursor="signed")
    assert first.request.run_id == uid(2) and continued.cursor == "signed"


def test_public_dimension_requires_enum_and_normalization_is_never_integer() -> None:
    with pytest.raises(DomainError):
        app.Exposures(dimension=cast(Any, "company"))
    with pytest.raises(DomainError):
        app.Paths(normalized_known_only=cast(Any, 1))
    assert app.Exposures().dimension is XrayDimension.COMPANY


def test_pair_set_and_orientation_have_stable_canonical_order() -> None:
    ids = (uid(3), uid(1), uid(2))
    pair = app.CommonEntities(fund_ids=ids, left_fund_id=uid(3), right_fund_id=uid(1))
    assert pair.fund_ids == tuple(sorted(ids))
    assert (pair.left_fund_id, pair.right_fund_id) == (uid(1), uid(3))
    with pytest.raises(DomainError, match="retained run pin"):
        app.EtfOverlapQuery(request=request(), options=pair)
    assert (
        app.EtfOverlapQuery(request=replace(request(), run_id=uid(4)), options=pair).options == pair
    )


@pytest.mark.parametrize("ids", [(uid(1),), (uid(1), uid(1)), tuple(uid(i) for i in range(33))])
def test_pairs_reject_invalid_cardinality_or_duplicates(ids: tuple[str, ...]) -> None:
    with pytest.raises(DomainError):
        app.Pairs(fund_ids=ids)


def test_mcp_top_retains_pair_identity_and_has_no_page_cursor() -> None:
    pair = app.McpTopPair(left_fund_id=uid(3), right_fund_id=uid(2), top_n=50)
    assert pair.left_fund_id == uid(2)
    with pytest.raises(DomainError):
        app.EtfOverlapQuery(request=request(), options=pair, cursor="signed")
    with pytest.raises(DomainError):
        app.EtfOverlapQuery(request=request(), options=pair, limit=50)
    with pytest.raises(DomainError):
        app.McpTopPair(left_fund_id=uid(2), right_fund_id=uid(2))


@pytest.mark.parametrize("selectors", [{"account_id": uid(1)}, {"run_id": uid(2)}])
def test_partial_dependent_source_scope_fails_for_header_and_holdings(
    selectors: dict[str, str],
) -> None:
    with pytest.raises(DomainError):
        app.ConstituentSnapshotQuery(
            account_id=selectors.get("account_id"), run_id=selectors.get("run_id")
        )
    with pytest.raises(DomainError):
        app.ConstituentHoldingsQuery(
            account_id=selectors.get("account_id"), run_id=selectors.get("run_id")
        )
    assert app.ConstituentSnapshotQuery().account_id is None
    assert app.ConstituentHoldingsQuery(account_id=uid(1), run_id=uid(2)).run_id == uid(2)
