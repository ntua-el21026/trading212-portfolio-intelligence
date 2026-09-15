"""Real research storage behind REST: saved evidence, exact revisions and current rights."""

from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from trading212_api.main import create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


class ResearchBearer:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, token: str) -> Principal:
        if token == "owned-research-fixture":
            return self.principal
        assert token == "foreign-research-fixture"
        return replace(
            self.principal,
            principal_id="foreign-research-fixture",
            owner_id=str(uuid4()),
            issuer="foreign-research-fixture",
            subject="foreign-research-fixture",
        )


async def test_real_research_rest_revision_replay_profile_facts_and_source_revocation(
    research_case: ResearchCase,
) -> None:
    case = research_case
    saved = case.publish(
        case.incoming(
            "research-rest-event", summary="<script>inert retained source</script> 999999 EUR"
        )
    )
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, allowed_hosts=("testserver",)
        ),
        service=SyntheticPortfolioService(clock=lambda: case.xray.now[0]),
        research_service=case.service,
        bearer_authenticator=ResearchBearer(case.xray.principal),
        clock=lambda: case.xray.now[0],
    )
    # Portfolio service is not used by these routes; all actual research reads use
    # the supplied durable service and its explicit fixture capability authority.
    headers = {"Authorization": "Bearer owned-research-fixture"}
    path = f"/api/v1/accounts/{case.account_id}/research"
    query = {
        "xray_run_id": str(case.run_id),
        "source_cutoff_at": case.query().source_cutoff_at.isoformat(),
        "limit": "1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url="https://testserver"
    ) as client:
        summary = await client.get(path, params=query, headers=headers)
        assert summary.status_code == 200, summary.text
        selected = summary.json()["items"][0]
        expected = await case.service.get_research_item(
            case.xray.principal, UUID(selected["item_id"])
        )
        assert selected["portfolio"]["effective_exposure"] == to_primitive(
            expected.portfolio.effective_exposure
        )
        assert (
            selected["portfolio"]["canonical_facts_digest"]
            == expected.portfolio.canonical_facts_digest
        )
        assert selected["source"]["content_digest"] == saved.content_digest
        assert selected["synthesis"]["availability"] == "unavailable"
        item_path = f"/api/v1/research/items/{selected['item_id']}"
        source = await client.get(item_path, headers=headers)
        assert source.status_code == 200
        assert (
            await client.get(
                item_path, headers={**headers, "If-None-Match": source.headers["etag"]}
            )
        ).status_code == 304
        assert (
            await client.get(
                item_path, headers={"Authorization": "Bearer foreign-research-fixture"}
            )
        ).status_code == 404
        content = {
            "title": "Owner premise",
            "thesis": "Owner-authored text; never issuer facts.",
            "citations": [],
        }
        note_path = f"/api/v1/accounts/{case.account_id}/research/notes"
        command_headers = {**headers, "X-Idempotency-Key": uuid4().hex}
        created = await client.post(
            note_path,
            json={"entity_id": str(case.entity_id), "content": content},
            headers=command_headers,
        )
        assert created.status_code == 201, created.text
        assert (
            await client.post(
                note_path,
                json={"entity_id": str(case.entity_id), "content": content},
                headers=command_headers,
            )
        ).json() == created.json()
        assert (
            await client.post(
                note_path,
                json={
                    "entity_id": str(case.entity_id),
                    "content": {**content, "thesis": "Different"},
                },
                headers=command_headers,
            )
        ).status_code == 409
        note_id = created.json()["note_id"]
        versions_path = f"/api/v1/research/notes/{note_id}/versions"
        version_headers = {
            **headers,
            "X-Idempotency-Key": uuid4().hex,
            "If-Match": created.headers["etag"],
        }
        version = await client.post(
            versions_path,
            json={"content": {**content, "risks": "New owner risk"}},
            headers=version_headers,
        )
        assert version.status_code == 201 and version.json()["revision"] == 2
        assert version.json()["previous_revision_id"] == created.json()["revision_id"]
        stale = await client.post(
            versions_path,
            json={"content": content},
            headers={**version_headers, "X-Idempotency-Key": uuid4().hex},
        )
        assert stale.status_code == 412
        versions = await client.get(versions_path, headers=headers)
        assert versions.status_code == 200 and [
            entry["revision"] for entry in versions.json()["items"]
        ] == [2, 1]
        review = await client.post(
            f"/api/v1/research/events/{saved.event_id}/review",
            json={"revision_id": str(saved.revision_id), "revision_digest": saved.content_digest},
            headers={**headers, "X-Idempotency-Key": uuid4().hex},
        )
        assert (
            review.status_code == 200 and review.json()["revision_digest"] == saved.content_digest
        )
        case.authority.revoked = True
        denied = await client.get(item_path, headers={**headers, "If-None-Match": "*"})
        assert denied.status_code == 503 and denied.json()["error"]["code"] == "SOURCE_UNAVAILABLE"
        assert "inert retained source" not in denied.text
        own_note = await client.get(f"/api/v1/research/notes/{note_id}", headers=headers)
        assert (
            own_note.status_code == 200 and own_note.json()["content"]["risks"] == "New owner risk"
        )
