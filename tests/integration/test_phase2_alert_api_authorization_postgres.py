"""Alert operations bind real rule, event and destination ownership before mutation."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import assert_never
from uuid import UUID, uuid4

import httpx
import pytest
from trading212_api_contracts import alerts as wire
from trading212_application import alerts as app
from trading212_application.alert_projection import alert_content
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import (
    ALERT_STATE,
    ORIGIN,
    Actor,
    AlertResources,
    HttpCase,
    OwnerGrid,
    build_alert,
    denied,
    draft_rule,
    retained_state,
    send,
    without_grant,
)
from tests.integration.phase2_authorization_cases import alert_resources as alert_resources
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


class AlertOperation(StrEnum):
    RULES = "list_alert_rules"
    CREATE = "create_alert_rule"
    RULE = "get_alert_rule"
    VERSION = "create_alert_rule_version"
    ACTIVATE = "activate_alert_rule"
    PAUSE = "pause_alert_rule"
    ARCHIVE = "archive_alert_rule"
    EVENTS = "list_alert_events"
    EVENT = "get_alert_event"
    ACKNOWLEDGE = "acknowledge_alert_event"
    RESOLVE = "resolve_alert_event"
    SUMMARY = "get_alert_summary"
    DESTINATIONS = "list_notification_destinations"


COLLECTIONS = frozenset(
    {
        AlertOperation.RULES,
        AlertOperation.EVENTS,
        AlertOperation.SUMMARY,
        AlertOperation.DESTINATIONS,
    }
)
WRITES = frozenset(
    {
        AlertOperation.CREATE,
        AlertOperation.VERSION,
        AlertOperation.ACTIVATE,
        AlertOperation.PAUSE,
        AlertOperation.ARCHIVE,
        AlertOperation.ACKNOWLEDGE,
        AlertOperation.RESOLVE,
    }
)
EVENT_OPERATIONS = frozenset(
    {AlertOperation.EVENT, AlertOperation.ACKNOWLEDGE, AlertOperation.RESOLVE}
)


async def target_for(
    grid: OwnerGrid,
    actor: Actor,
    base: AlertResources,
    operation: AlertOperation,
) -> AlertResources:
    if operation in {AlertOperation.ACKNOWLEDGE, AlertOperation.RESOLVE}:
        return await build_alert(grid, actor, base.pin)
    if operation in {
        AlertOperation.VERSION,
        AlertOperation.ACTIVATE,
        AlertOperation.PAUSE,
        AlertOperation.ARCHIVE,
    }:
        rule = await draft_rule(grid, actor, base.pin, base.destination)
        if operation in {AlertOperation.PAUSE, AlertOperation.ARCHIVE}:
            rule = await grid.alerts.activate_rule(
                actor.principal,
                rule.id,
                rule.latest_version.id,
                idempotency_key=uuid4().hex,
                expected_revision=rule.revision,
                correlation_id="p210-positive-lifecycle",
            )
        return replace(base, rule=rule)
    return base


async def request_for(
    grid: OwnerGrid,
    actor: Actor,
    operation: AlertOperation,
    resource: AlertResources,
) -> HttpCase:
    account = str(resource.pin.account_id)
    key = {"X-Idempotency-Key": uuid4().hex}
    definition = wire.AlertRuleDefinition.model_validate(
        alert_content(grid.definition(resource.destination))
    )
    if operation in {
        AlertOperation.VERSION,
        AlertOperation.ACTIVATE,
        AlertOperation.PAUSE,
        AlertOperation.ARCHIVE,
    }:
        current = await grid.alerts.get_rule(
            actor.principal, resource.rule.id, query=app.AlertRuleDetailQuery()
        )
        key["If-Match"] = current.etag
    if operation in {AlertOperation.ACKNOWLEDGE, AlertOperation.RESOLVE}:
        current_event = await grid.alerts.get_event(actor.principal, resource.event.id)
        key["If-Match"] = current_event.etag
    match operation:
        case AlertOperation.RULES:
            return HttpCase(
                operation,
                "GET",
                "/api/v1/alert-rules",
                200,
                {"account_id": account, "limit": "100"},
            )
        case AlertOperation.CREATE:
            body = wire.CreateAlertRuleRequest(account_id=account, definition=definition)
            return HttpCase(
                operation,
                "POST",
                "/api/v1/alert-rules",
                201,
                body=body.model_dump_json(),
                headers=key,
            )
        case AlertOperation.RULE:
            return HttpCase(operation, "GET", f"/api/v1/alert-rules/{resource.rule.id}", 200)
        case AlertOperation.VERSION:
            version = wire.AlertRuleVersionRequest(definition=definition)
            return HttpCase(
                operation,
                "POST",
                f"/api/v1/alert-rules/{resource.rule.id}/versions",
                201,
                body=version.model_dump_json(),
                headers=key,
            )
        case AlertOperation.ACTIVATE:
            activation = wire.ActivateAlertRuleRequest(
                version_id=str(resource.rule.latest_version.id)
            )
            return HttpCase(
                operation,
                "POST",
                f"/api/v1/alert-rules/{resource.rule.id}/activate",
                200,
                body=activation.model_dump_json(),
                headers=key,
            )
        case AlertOperation.PAUSE | AlertOperation.ARCHIVE:
            action = "pause" if operation is AlertOperation.PAUSE else "archive"
            return HttpCase(
                operation,
                "POST",
                f"/api/v1/alert-rules/{resource.rule.id}/{action}",
                200,
                body="{}",
                headers=key,
            )
        case AlertOperation.EVENTS:
            return HttpCase(
                operation,
                "GET",
                "/api/v1/alert-events",
                200,
                {"account_id": account, "limit": "100", "state": "all"},
            )
        case AlertOperation.EVENT:
            return HttpCase(operation, "GET", f"/api/v1/alert-events/{resource.event.id}", 200)
        case AlertOperation.ACKNOWLEDGE | AlertOperation.RESOLVE:
            action = "acknowledgments" if operation is AlertOperation.ACKNOWLEDGE else "resolve"
            note = wire.AlertEventNoteRequest(note="Owned acknowledgment or resolution")
            return HttpCase(
                operation,
                "POST",
                f"/api/v1/alert-events/{resource.event.id}/{action}",
                201 if operation is AlertOperation.ACKNOWLEDGE else 200,
                body=note.model_dump_json(),
                headers=key,
            )
        case AlertOperation.SUMMARY:
            return HttpCase(
                operation,
                "GET",
                f"/api/v1/accounts/{account}/alert-summary",
                200,
                {"state": "all", "top_n": "50"},
            )
        case AlertOperation.DESTINATIONS:
            return HttpCase(
                operation,
                "GET",
                "/api/v1/notification-destinations",
                200,
                {"account_id": account, "limit": "100"},
            )
        case _:
            assert_never(operation)


def assert_owned(
    response: httpx.Response, operation: AlertOperation, resource: AlertResources
) -> None:
    account = str(resource.pin.account_id)
    if operation is AlertOperation.RULES:
        rules = wire.AlertRulePage.model_validate_json(response.content)
        assert rules.total == len(rules.items) and rules.next_cursor is None
        assert str(resource.rule.id) in {item.id for item in rules.items}
        assert all(item.account_id == account for item in rules.items)
    elif operation is AlertOperation.EVENTS:
        events = wire.AlertEventPage.model_validate_json(response.content)
        assert events.total == len(events.items) and events.next_cursor is None
        assert str(resource.event.id) in {item.id for item in events.items}
        assert all(item.account_id == account for item in events.items)
    elif operation is AlertOperation.SUMMARY:
        summary = wire.AlertSummary.model_validate_json(response.content)
        assert summary.account_id == account
        assert str(resource.event.id) in {item.id for item in summary.items}
        assert all(item.account_id == account for item in summary.items)
        assert summary.counts.total_count == len(summary.items) and summary.omitted_count == 0
    elif operation is AlertOperation.DESTINATIONS:
        destinations = wire.NotificationDestinationPage.model_validate_json(response.content)
        assert destinations.total == len(destinations.items) and destinations.next_cursor is None
        assert str(resource.destination) in {item.id for item in destinations.items}
    elif operation is AlertOperation.VERSION:
        version = wire.AlertRuleVersionDetail.model_validate_json(response.content)
        assert (
            version.version.rule_id == str(resource.rule.id)
            and version.version.account_id == account
        )
    elif operation is AlertOperation.ACKNOWLEDGE:
        acknowledgment = wire.AlertAcknowledgment.model_validate_json(response.content)
        assert acknowledgment.event_id == str(resource.event.id)
    elif operation in {AlertOperation.EVENT, AlertOperation.RESOLVE}:
        event = wire.AlertEventDetail.model_validate_json(response.content)
        assert event.id == str(resource.event.id) and event.account_id == account
        if operation is AlertOperation.RESOLVE:
            assert event.episode_state == "resolved"
    else:
        rule = wire.AlertRuleDetail.model_validate_json(response.content)
        assert rule.account_id == account
        if operation is not AlertOperation.CREATE:
            assert rule.id == str(resource.rule.id)
        expected = {
            AlertOperation.CREATE: "draft",
            AlertOperation.ACTIVATE: "active",
            AlertOperation.PAUSE: "paused",
            AlertOperation.ARCHIVE: "archived",
        }.get(operation)
        if expected is not None:
            assert rule.lifecycle == expected


@pytest.mark.parametrize("operation", tuple(AlertOperation), ids=lambda operation: operation.value)
async def test_alert_operations_bind_real_owner_resources_and_current_grants(
    owner_grid: OwnerGrid,
    alert_resources: dict[UUID, AlertResources],
    operation: AlertOperation,
) -> None:
    grid = owner_grid
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(grid.api), base_url=ORIGIN
    ) as client:
        for index, actor in enumerate(grid.actors):
            other = grid.actors[1 - index]
            base = alert_resources[actor.accounts[0].account_id]
            own = await target_for(grid, actor, base, operation)
            second = alert_resources[actor.accounts[1].account_id]
            request = await request_for(grid, actor, operation, own)
            positive = await send(client, actor, request)
            assert positive.status_code == request.success
            assert_owned(positive, operation, own)
            if operation in WRITES:
                before = retained_state(grid, ALERT_STATE)
                replay = await send(client, actor, request)
                assert replay.status_code == request.success and replay.content == positive.content
                assert retained_state(grid, ALERT_STATE) == before
            # A valid second principal sees neither the object nor its ETag.
            protected = replace(
                request,
                headers={
                    **request.headers,
                    "If-None-Match": positive.headers.get("etag", "*"),
                },
            )
            before = retained_state(grid, ALERT_STATE)
            denied(
                await send(client, other, protected),
                "ACCESS_DENIED"
                if operation in COLLECTIONS or operation is AlertOperation.CREATE
                else "NOT_FOUND",
                own.private_values,
            )
            assert retained_state(grid, ALERT_STATE) == before

            if operation in COLLECTIONS:
                own_second = await request_for(grid, actor, operation, second)
                isolated = await send(client, actor, own_second)
                assert isolated.status_code == 200
                assert_owned(isolated, operation, second)
                assert all(
                    value not in isolated.text
                    for value in (
                        str(base.rule.id),
                        str(base.event.id),
                        str(base.destination),
                    )
                )
            elif operation is not AlertOperation.CREATE:
                # Existing IDs from a different resource kind must not cross the
                # closed rule/event tables. Detail routes do not accept account_id.
                incorrect_id = own.rule.id if operation in EVENT_OPERATIONS else own.event.id
                current_id = own.event.id if operation in EVENT_OPERATIONS else own.rule.id
                mismatch = replace(
                    request,
                    path=request.path.replace(str(current_id), str(incorrect_id)),
                    headers={
                        **request.headers,
                        "If-Match": f'"{incorrect_id}:1"',
                        "X-Idempotency-Key": uuid4().hex,
                    },
                )
                before = retained_state(grid, ALERT_STATE)
                denied(await send(client, actor, mismatch), "NOT_FOUND", own.private_values)
                assert retained_state(grid, ALERT_STATE) == before

            revoke = Scope.ALERTS_WRITE if operation in WRITES else Scope.ALERTS_READ
            with without_grant(grid, actor, revoke):
                before = retained_state(grid, ALERT_STATE)
                denied(await send(client, actor, protected), "ACCESS_DENIED", own.private_values)
                assert retained_state(grid, ALERT_STATE) == before


@pytest.mark.parametrize(
    "operation",
    (AlertOperation.CREATE, AlertOperation.VERSION, AlertOperation.ACTIVATE),
    ids=lambda operation: operation.value,
)
async def test_alert_parent_and_destination_references_bind_owner_and_account(
    owner_grid: OwnerGrid,
    alert_resources: dict[UUID, AlertResources],
    operation: AlertOperation,
) -> None:
    grid = owner_grid
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(grid.api), base_url=ORIGIN
    ) as client:
        for index, actor in enumerate(grid.actors):
            own = await target_for(
                grid, actor, alert_resources[actor.accounts[0].account_id], operation
            )
            for alien in (
                alert_resources[actor.accounts[1].account_id],
                alert_resources[grid.actors[1 - index].accounts[0].account_id],
            ):
                request = await request_for(grid, actor, operation, own)
                assert request.body is not None
                body: (
                    wire.ActivateAlertRuleRequest
                    | wire.CreateAlertRuleRequest
                    | wire.AlertRuleVersionRequest
                )
                if operation is AlertOperation.ACTIVATE:
                    body = wire.ActivateAlertRuleRequest(
                        version_id=str(alien.rule.latest_version.id)
                    )
                elif operation is AlertOperation.CREATE:
                    original = wire.CreateAlertRuleRequest.model_validate_json(request.body)
                    body = original.model_copy(
                        update={
                            "definition": original.definition.model_copy(
                                update={"destination_ids": [str(alien.destination)]}
                            ),
                        }
                    )
                else:
                    original_version = wire.AlertRuleVersionRequest.model_validate_json(
                        request.body
                    )
                    body = original_version.model_copy(
                        update={
                            "definition": original_version.definition.model_copy(
                                update={"destination_ids": [str(alien.destination)]}
                            ),
                        }
                    )
                wrong_parent = replace(request, body=body.model_dump_json())
                before = retained_state(grid, ALERT_STATE)
                denied(await send(client, actor, wrong_parent), "NOT_FOUND", alien.private_values)
                assert retained_state(grid, ALERT_STATE) == before
            # The identical local selection is valid after the negatives.
            valid = await request_for(grid, actor, operation, own)
            response = await send(client, actor, valid)
            assert response.status_code == valid.success
            assert_owned(response, operation, own)


async def test_event_rule_filter_cannot_mix_two_owned_accounts_or_a_foreign_rule(
    owner_grid: OwnerGrid,
    alert_resources: dict[UUID, AlertResources],
) -> None:
    grid = owner_grid
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(grid.api), base_url=ORIGIN
    ) as client:
        for index, actor in enumerate(grid.actors):
            own = alert_resources[actor.accounts[0].account_id]
            base = await request_for(grid, actor, AlertOperation.EVENTS, own)
            matching = replace(base, query={**base.query, "rule_id": str(own.rule.id)})
            positive = await send(client, actor, matching)
            assert positive.status_code == 200
            page = wire.AlertEventPage.model_validate_json(positive.content)
            assert {row.id for row in page.items} == {str(own.event.id)} and page.total == 1
            # An authorized empty filter may create a bounded collection snapshot;
            # it must not change any financial, rule, event or delivery record.
            for wrong in (
                alert_resources[actor.accounts[1].account_id].rule.id,
                alert_resources[grid.actors[1 - index].accounts[0].account_id].rule.id,
                uuid4(),
            ):
                request = replace(base, query={**base.query, "rule_id": str(wrong)})
                before = retained_state(grid, ALERT_STATE, include_collections=False)
                response = await send(client, actor, request)
                assert response.status_code == 200
                result = wire.AlertEventPage.model_validate_json(response.content)
                assert result.items == [] and result.total == 0 and result.next_cursor is None
                assert str(wrong) not in response.text
                assert retained_state(grid, ALERT_STATE, include_collections=False) == before
