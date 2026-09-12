"""P2-01 configuration projection, strict tools, and safe failure coverage."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_application import targets as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_application.views import Page
from trading212_domain import targets as domain
from trading212_domain.values import CurrencyCode
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import Principal
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
PORTFOLIO_ID = "3e5c5929-6852-4f2c-8e87-90ff86e8c8ce"
VERSION_ID = "c2d7c635-a194-4d55-b79c-8f6b7e4bcb9e"
NODE_ID = "b701f11a-b7b4-4417-8f62-8bce4a541514"
OTHER_ID = "cbfa99d4-120b-46d1-91b3-287399726dfb"


class ReadTargets:
    """Only the read methods needed by the gateway; calls record typed queries."""

    def __init__(self) -> None:
        self.portfolio = app.VirtualPortfolioView(
            PORTFOLIO_ID,
            None,
            "Private template",
            "",
            "EUR",
            3,
            app.VirtualPortfolioState.ACTIVE,
            NOW,
            NOW,
            VERSION_ID,
        )
        node = domain.TargetNode("cash", None, domain.TargetNodeKind.CASH, "Cash", 0, Decimal("1"))
        content = domain.TargetContent((node,))
        validation = domain.validate_target_content(
            content,
            reporting_currency=CurrencyCode("EUR"),
            effective_at=NOW,
            catalog=domain.TargetCatalog(),
        )
        self.version = app.TargetVersionView(
            VERSION_ID,
            PORTFOLIO_ID,
            1,
            2,
            "EUR",
            NOW,
            app.TargetVersionState.ACTIVE,
            content,
            NOW,
            NOW,
            published_at=NOW,
            content_digest=validation.result_digest,
            flattened_nodes=validation.flattened_nodes,
            effective_weight_rounding_residual=validation.effective_weight_rounding_residual,
        )
        self.failure: Exception | None = None
        self.calls: list[object] = []

    async def list_virtual_portfolios(
        self, principal: Principal, *, query: app.VirtualPortfolioQuery
    ) -> Page[app.VirtualPortfolioView]:
        self.calls.append(query)
        if self.failure:
            raise self.failure
        return Page((self.portfolio,), None, query.limit, 1)

    async def get_virtual_portfolio_targets(
        self,
        principal: Principal,
        portfolio_id: str,
        *,
        account_id: str | None,
        target_version_id: str | None,
        parent_node_id: str | None,
        query: app.TargetPageQuery,
    ) -> app.TargetPortfolioReadView:
        self.calls.append((portfolio_id, account_id, target_version_id, parent_node_id, query))
        if self.failure:
            raise self.failure
        if portfolio_id != self.portfolio.id or account_id != self.portfolio.account_id:
            raise app.TargetServiceError(app.TargetServiceErrorCode.NOT_FOUND, "Scope mismatch.")
        selected = target_version_id or self.portfolio.active_version_id
        if selected is None:
            if parent_node_id is not None or query.cursor is not None:
                raise app.TargetServiceError(app.TargetServiceErrorCode.NOT_FOUND, "No target.")
            return app.TargetPortfolioReadView(self.portfolio, None, Page((), None, query.limit, 0))
        if selected != self.version.id or self.version.portfolio_id != portfolio_id:
            raise app.TargetServiceError(app.TargetServiceErrorCode.NOT_FOUND, "Version mismatch.")
        return app.TargetPortfolioReadView(
            self.portfolio,
            self.version,
            Page(
                (app.TargetHierarchyNodeView(NODE_ID, self.version.content.nodes[0]),),
                "synthetic_cursor" if query.limit == 1 else None,
                query.limit,
                2 if query.limit == 1 else 1,
            ),
        )


def runtime(service: ReadTargets | None = None) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        ),
        target_service=cast(app.TargetService, service) if service else None,
        clock=lambda: NOW,
    ).server


async def call(server: MCPServer[Any], name: str, arguments: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    RESULT_MODELS[name].model_validate(result.structured_content)
    return result


async def test_target_list_uses_explicit_template_scope_and_typed_query() -> None:
    service = ReadTargets()
    result = await call(
        runtime(service),
        "list_virtual_pies",
        {
            "account_id": None,
            "state": "all",
            "search": "  PRIVATE  ",
            "limit": 1,
        },
    )
    assert not result.is_error
    assert result.structured_content["data"]["portfolios"][0]["id"] == PORTFOLIO_ID
    assert result.structured_content["data_quality"]["state"] == "configuration"
    assert result.structured_content["calculation"]["name"] == "target_configuration_read_v1"
    query = service.calls[0]
    assert isinstance(query, app.VirtualPortfolioQuery)
    assert query.account_id is None and query.search == "private" and query.limit == 1


async def test_target_get_delegates_parent_uuid_paging_and_retains_exact_values() -> None:
    service = ReadTargets()
    result = await call(
        runtime(service),
        "get_virtual_pie",
        {
            "account_id": None,
            "virtual_portfolio_id": PORTFOLIO_ID,
            "target_version_id": VERSION_ID,
            "parent_node_id": NODE_ID,
            "cursor": "synthetic_cursor",
            "limit": 1,
        },
    )
    assert not result.is_error
    payload = result.structured_content
    assert payload["pagination"] == {
        "next_cursor": "synthetic_cursor",
        "limit": 1,
        "total": 2,
        "truncated": True,
    }
    assert payload["data"]["nodes"][0]["hierarchy"]["node"]["weight"] == "1"
    assert payload["data"]["nodes"][0]["calculated"]["effective_weight"] == "1"
    assert service.calls == [
        (PORTFOLIO_ID, None, VERSION_ID, NODE_ID, app.TargetPageQuery("synthetic_cursor", 1))
    ]


async def test_atomic_target_projection_survives_a_later_draft_edit() -> None:
    class ChangedAfterRead(ReadTargets):
        async def get_virtual_portfolio_targets(
            self,
            principal: Principal,
            portfolio_id: str,
            *,
            account_id: str | None,
            target_version_id: str | None,
            parent_node_id: str | None,
            query: app.TargetPageQuery,
        ) -> app.TargetPortfolioReadView:
            snapshot = await super().get_virtual_portfolio_targets(
                principal,
                portfolio_id,
                account_id=account_id,
                target_version_id=target_version_id,
                parent_node_id=parent_node_id,
                query=query,
            )
            changed = replace(self.version.content.nodes[0], weight=Decimal("0.8"))
            self.version = replace(
                self.version,
                revision=3,
                content=replace(self.version.content, nodes=(changed,)),
            )
            return snapshot

    service = ChangedAfterRead()
    service.version = replace(
        service.version, state=app.TargetVersionState.DRAFT, published_at=None, content_digest=None
    )
    result = await call(
        runtime(service),
        "get_virtual_pie",
        {
            "account_id": None,
            "virtual_portfolio_id": PORTFOLIO_ID,
            "target_version_id": VERSION_ID,
        },
    )
    assert not result.is_error
    payload = result.structured_content["data"]
    assert service.version.revision == 3
    assert payload["target_version"]["revision"] == 2
    assert payload["nodes"][0]["hierarchy"]["node"]["weight"] == "1"
    assert payload["nodes"][0]["calculated"]["effective_weight"] == "1"
    assert len(service.calls) == 1


async def test_no_active_target_is_explicit_unavailable_configuration() -> None:
    service = ReadTargets()
    service.portfolio = replace(service.portfolio, active_version_id=None)
    result = await call(
        runtime(service),
        "get_virtual_pie",
        {
            "account_id": None,
            "virtual_portfolio_id": PORTFOLIO_ID,
        },
    )
    assert not result.is_error
    assert result.structured_content["data"]["target_reason"] == "NO_ACTIVE_TARGET"
    assert result.structured_content["data"]["nodes"] == []
    assert result.structured_content["pagination"]["total"] == 0


@pytest.mark.parametrize("account_id", [OTHER_ID])
async def test_null_template_scope_cannot_read_an_account_or_other_version(account_id: str) -> None:
    service = ReadTargets()
    result = await call(
        runtime(service),
        "get_virtual_pie",
        {
            "account_id": account_id,
            "virtual_portfolio_id": PORTFOLIO_ID,
        },
    )
    assert result.is_error
    assert result.structured_content["error"]["code"] == "NOT_FOUND"
    service.version = replace(service.version, portfolio_id=OTHER_ID)
    result = await call(
        runtime(service),
        "get_virtual_pie",
        {
            "account_id": None,
            "virtual_portfolio_id": PORTFOLIO_ID,
        },
    )
    assert result.structured_content["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("tool", ["list_virtual_pies", "get_virtual_pie"])
async def test_optional_legacy_composition_has_safe_typed_target_unavailability(tool: str) -> None:
    arguments: dict[str, Any] = {"account_id": None}
    if tool == "get_virtual_pie":
        arguments["virtual_portfolio_id"] = PORTFOLIO_ID
    result = await call(runtime(), tool, arguments)
    assert result.is_error
    assert result.structured_content["error"]["code"] == "TARGETS_UNAVAILABLE"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"account_id": None, "limit": True},
        {"account_id": None, "limit": "2"},
        {"account_id": None, "limit": 101},
        {"account_id": None, "limit": 0},
        {"account_id": "not-a-uuid"},
        {"account_id": "null"},
        {"account_id": '"null"'},
        {"account_id": None, "method": "POST"},
        {"account_id": None, "search": "x" * 81},
    ],
)
async def test_new_input_schemas_fail_before_dispatch(arguments: dict[str, Any]) -> None:
    service = ReadTargets()
    with pytest.raises(ToolError):
        await runtime(service).call_tool("list_virtual_pies", arguments)
    assert service.calls == []


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (CursorValidationError("private source detail"), "CURSOR_INVALID"),
        (CollectionSnapshotCapacityError(), "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED"),
        (RuntimeError("private source detail"), "INTERNAL_ERROR"),
    ],
)
async def test_errors_are_typed_and_never_echo_exception_details(
    failure: Exception,
    code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = ReadTargets()
    service.failure = failure
    with caplog.at_level(logging.INFO):
        result = await call(runtime(service), "list_virtual_pies", {"account_id": None})
    assert result.structured_content["error"]["code"] == code
    assert "private source detail" not in result.model_dump_json() + caplog.text


async def test_schema_validation_hides_canary_input_and_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "_".join(("TARGET", "CREDENTIAL", "CANARY"))
    with caplog.at_level(logging.DEBUG), pytest.raises(ToolError) as raised:
        await runtime(ReadTargets()).call_tool("list_virtual_pies", {"account_id": canary})
    assert canary not in str(raised.value) + caplog.text


@pytest.mark.parametrize("tool", ["list_virtual_pies", "get_virtual_pie"])
async def test_unknown_argument_names_and_values_are_never_reflected(
    tool: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key_canary = "_".join(("TARGET", "ARGUMENT", "NAME", "CANARY"))
    value_canary = "_".join(("TARGET", "ARGUMENT", "VALUE", "CANARY"))
    arguments: dict[str, Any] = {"account_id": None, key_canary: value_canary}
    if tool == "get_virtual_pie":
        arguments["virtual_portfolio_id"] = PORTFOLIO_ID
    service = ReadTargets()
    with caplog.at_level(logging.DEBUG), pytest.raises(ToolError) as raised:
        await runtime(service).call_tool(tool, arguments)
    rendered = str(raised.value) + caplog.text
    assert key_canary not in rendered
    assert value_canary not in rendered
    assert service.calls == []


async def test_optional_literal_strings_are_not_reinterpreted_as_json() -> None:
    service = ReadTargets()
    result = await call(
        runtime(service),
        "list_virtual_pies",
        {
            "account_id": None,
            "search": "null",
            "cursor": "null",
        },
    )
    assert not result.is_error
    query = service.calls[0]
    assert isinstance(query, app.VirtualPortfolioQuery)
    assert query.account_id is None
    assert query.search == "null"
    assert query.cursor == "null"


async def test_target_response_byte_bound_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trading212_mcp.target_gateway.MAX_TARGET_OUTPUT_BYTES", 100)
    result = await call(runtime(ReadTargets()), "list_virtual_pies", {"account_id": None})
    assert result.structured_content["error"]["code"] == "RESULT_TOO_LARGE"


async def test_target_input_byte_bound_precedes_service_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReadTargets()
    monkeypatch.setattr("trading212_mcp.target_gateway.MAX_TARGET_INPUT_BYTES", 10)
    result = await call(runtime(service), "list_virtual_pies", {"account_id": None})
    assert result.structured_content["error"]["code"] == "REQUEST_TOO_LARGE"
    assert service.calls == []


async def test_unresolved_mapping_quality_and_stale_draft_validation_are_explicit() -> None:
    service = ReadTargets()
    node = domain.TargetNode(
        "unresolved",
        None,
        domain.TargetNodeKind.HOLDING,
        "Unknown listing",
        0,
        Decimal("1"),
        domain.TargetHoldingMapping(
            domain.TargetMappingState.UNRESOLVED,
            requested_identifier=domain.TargetIdentifier(
                domain.TargetIdentifierKind.ISIN, "US0378331005"
            ),
            reason="No approved catalog match.",
        ),
    )
    content = domain.TargetContent((node,))
    validation = domain.validate_target_content(
        content,
        reporting_currency=CurrencyCode("EUR"),
        effective_at=NOW,
        catalog=domain.TargetCatalog(),
    )
    retained = app.TargetValidationView(
        OTHER_ID,
        VERSION_ID,
        2,
        2,
        validation.input_digest,
        validation.result_digest,
        True,
        False,
        False,
        validation.issues,
        validation.adjustments,
        NOW,
    )
    service.version = replace(
        service.version,
        content=content,
        state=app.TargetVersionState.DRAFT,
        published_at=None,
        content_digest=None,
        latest_validation=retained,
        flattened_nodes=validation.flattened_nodes,
    )
    arguments = {
        "account_id": None,
        "virtual_portfolio_id": PORTFOLIO_ID,
        "target_version_id": VERSION_ID,
    }
    current = await call(runtime(service), "get_virtual_pie", arguments)
    assert current.structured_content["data_quality"]["state"] == "partial"
    assert current.structured_content["data_quality"]["unresolved_mapping_count"] == 1
    assert service.version.has_current_validation
    service.version = replace(service.version, revision=3)
    stale = await call(runtime(service), "get_virtual_pie", arguments)
    assert stale.structured_content["data_quality"]["state"] == "unvalidated"
    assert stale.structured_content["data"]["validation"]["id"] == OTHER_ID
    assert not service.version.has_current_validation
    # Equal revision alone cannot authorize a validation of different content.
    service.version = replace(
        service.version, revision=2, latest_validation=replace(retained, result_digest="a" * 64)
    )
    assert not service.version.has_current_validation
    for state in (
        app.TargetVersionState.SCHEDULED,
        app.TargetVersionState.ACTIVE,
        app.TargetVersionState.SUPERSEDED,
        app.TargetVersionState.ARCHIVED,
    ):
        service.version = replace(
            service.version,
            state=state,
            revision=9,
            published_at=NOW,
            latest_validation=retained,
            content_digest=retained.result_digest,
        )
        assert service.version.has_current_validation


def test_normal_database_composition_contains_real_target_service() -> None:
    composed = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        ),
        database_url="postgresql+psycopg://portfolio:portfolio@localhost/portfolio",
    )
    assert isinstance(composed.target_service, PostgresTargetService)
    assert UUID(PORTFOLIO_ID)
