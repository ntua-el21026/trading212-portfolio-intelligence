"""Research creation uses the existing explicit premium report operation."""

from typing import Any
from uuid import UUID

import httpx
import pytest
from trading212_api_contracts import premium_reports_v3 as wire
from trading212_security.principals import Scope

from tests.unit.api.report_factories import BODY
from tests.unit.api.test_premium_report_profile_routes import PROFILE, application, body_v3
from tests.unit.api.test_report_routes import ORIGIN, SCOPES, _headers

pytestmark = pytest.mark.unit
ITEM = "00000000-0000-0000-0000-000000000101"


def research_body(pin: dict[str, object] | None = None) -> dict[str, Any]:
    return {
        **body_v3(),
        "premium_run": pin
        if pin is not None
        else {
            "family": "research",
            "item_id": ITEM,
            "note_revision_ids": [],
        },
        "sections": [*BODY["sections"], "research"],
    }


async def test_explicit_research_selector_uses_item_identity_without_a_fabricated_run() -> None:
    api, legacy, premium, profile3 = application(SCOPES | {Scope.RESEARCH_READ})
    payload = research_body()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=payload,
            headers=_headers(),
        )
    assert response.status_code == 202
    assert response.json()["profile_version"] == PROFILE
    profile3.generate_report.assert_awaited_once()
    command = profile3.generate_report.await_args.args[1]
    pin = command.selection.premium_run
    assert pin.family == "research"
    assert pin.item_id == UUID(ITEM)
    assert pin.note_revision_ids == ()
    assert pin.review_acknowledgment_id is None
    assert not hasattr(pin, "run_id")
    assert not legacy.mock_calls and not premium.mock_calls


async def test_exact_note_versions_and_review_are_canonical_and_preserved_in_the_command() -> None:
    api, _, _, reports = application(SCOPES | {Scope.RESEARCH_READ})
    notes = [str(UUID(int=103)), str(UUID(int=102))]
    review = str(UUID(int=104))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=research_body(
                {
                    "family": "research",
                    "item_id": ITEM,
                    "note_revision_ids": notes,
                    "review_acknowledgment_id": review,
                }
            ),
            headers=_headers(),
        )
    assert response.status_code == 202
    pin = reports.generate_report.await_args.args[1].selection.premium_run
    assert pin.note_revision_ids == (UUID(int=102), UUID(int=103))
    assert pin.review_acknowledgment_id == UUID(review)
    assert not hasattr(pin, "run_id")


@pytest.mark.parametrize(
    "change",
    [
        {"note_revision_ids": None},
        {"note_revision_ids": [str(UUID(int=102))] * 2},
        {"note_revision_ids": [str(UUID(int=index)) for index in range(1, 66)]},
        {"run_id": ITEM},
        {"review_acknowledgment_id": None},
        {"review_acknowledgment_id": "latest"},
        {"item_id": "latest"},
        {"private-field-canary": "private-value-canary"},
    ],
)
async def test_invalid_research_pins_fail_before_service_without_private_input_echo(
    change: dict[str, object],
) -> None:
    api, legacy, premium, reports = application(SCOPES | {Scope.RESEARCH_READ})
    pin = {"family": "research", "item_id": ITEM, "note_revision_ids": [], **change}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=research_body(pin),
            headers=_headers(),
        )
    assert response.status_code == 422
    assert (
        "private-field-canary" not in response.text and "private-value-canary" not in response.text
    )
    assert not reports.mock_calls and not legacy.mock_calls and not premium.mock_calls


async def test_note_selection_is_required_and_missing_research_scope_denies_valid_commands() -> (
    None
):
    api, _, _, reports = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        denied = await client.post(
            "/api/v2/report-jobs",
            params={"profile": PROFILE},
            json=research_body(),
            headers=_headers(),
        )
    assert denied.status_code == 403 and not reports.mock_calls
    with pytest.raises(ValueError):
        wire.GeneratePremiumReportRequestV3.model_validate(
            research_body({"family": "research", "item_id": ITEM})
        )


def test_exact_64_note_pins_are_supported_without_a_latest_selector() -> None:
    notes = [str(UUID(int=index)) for index in range(100, 164)]
    parsed = wire.GeneratePremiumReportRequestV3.model_validate(
        research_body(
            {
                "family": "research",
                "item_id": ITEM,
                "note_revision_ids": notes,
            }
        )
    )
    assert isinstance(parsed.premium_run, wire.PremiumReportResearchSelectionV3)
    assert parsed.premium_run.note_revision_ids == notes
    assert parsed.premium_run.review_acknowledgment_id is None
