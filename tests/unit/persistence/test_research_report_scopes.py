"""Research copies require their capability at every private create/detail boundary."""

import pytest
from trading212_persistence.report_base import report_scopes
from trading212_security.principals import Scope


@pytest.mark.parametrize(("create", "detail"), ((True, False), (False, True), (True, True)))
def test_research_create_and_detail_scopes_preserve_the_required_capability(
    create: bool,
    detail: bool,
) -> None:
    actual = report_scopes(
        sections=("overview", "allocation", "quality", "research"), create=create, detail=detail
    )
    assert {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.RESEARCH_READ} <= actual
    assert (Scope.REPORTS_WRITE if create else Scope.REPORTS_READ) in actual
    assert Scope.ACTIVITY_READ not in actual and Scope.RESEARCH_WRITE not in actual
