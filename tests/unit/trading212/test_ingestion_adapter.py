from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from trading212_application.ingestion import (
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionFailure,
    SourceRecord,
)
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.credentials import StaticCredentialProvider, Trading212Credentials
from trading212_provider.ingestion_adapter import Trading212IngestionAdapter
from trading212_worker.synthetic import SyntheticIngestionProvider

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/trading212"


def _adapter(
    handler: httpx.AsyncBaseTransport,
) -> tuple[Trading212IngestionAdapter, Trading212Client]:
    client = Trading212Client(
        settings=Trading212Settings(),
        credential_provider=StaticCredentialProvider(
            Trading212Credentials("synthetic-key", "synthetic-secret", BrokerEnvironment.DEMO)
        ),
        credential_reference="secret://synthetic/demo",
        transport=handler,
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
    )
    return Trading212IngestionAdapter(client), client


@pytest.mark.asyncio
async def test_account_dto_becomes_a_provenanced_source_record() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=(FIXTURES / "account_summary.json").read_bytes())

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        page = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.ACCOUNT,
            checkpoint=None,
            correlation_id="contract-test",
        )
    finally:
        await client.aclose()
    assert page.complete is True
    assert page.records[0].provider_record_id == "2120001"
    assert page.records[0].payload_sha256
    assert page.records[0].schema_version.endswith(":account_summary")


@pytest.mark.asyncio
async def test_safe_cursor_is_the_only_pagination_state_crossing_the_port() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        fixture = "transactions_page_1.json" if len(requests) == 1 else "transactions_page_2.json"
        return httpx.Response(200, content=(FIXTURES / fixture).read_bytes())

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        first = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.TRANSACTIONS,
            checkpoint=None,
            correlation_id="page-test",
        )
        assert first.next_checkpoint is not None
        second = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.TRANSACTIONS,
            checkpoint=first.next_checkpoint,
            correlation_id="page-test",
        )
    finally:
        await client.aclose()
    assert first.next_checkpoint == Checkpoint(
        cursor="opaque-2",
        source_timestamp=datetime(2026, 1, 3, 10, 15, 30, tzinfo=UTC),
        page_fingerprint=first.next_checkpoint.page_fingerprint,
    )
    assert requests[1].url.params["cursor"] == "opaque-2"
    assert second.complete is True


@pytest.mark.asyncio
async def test_incremental_transaction_overlap_is_stable_across_cursor_pages() -> None:
    requests: list[httpx.Request] = []
    overlap_started_at = datetime(2025, 12, 25, 10, 15, 30, tzinfo=UTC)
    encoded_time = "2025-12-25T10%3A15%3A30%2B00%3A00"

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            payload = json.loads((FIXTURES / "transactions_page_1.json").read_text())
            payload["nextPagePath"] = (
                "/api/v0/equity/history/transactions"
                f"?cursor=incremental-2&time={encoded_time}&limit=50"
            )
            return httpx.Response(200, json=payload)
        return httpx.Response(200, content=(FIXTURES / "transactions_page_2.json").read_bytes())

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        first = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.TRANSACTIONS,
            checkpoint=Checkpoint(
                source_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                overlap_started_at=overlap_started_at,
            ),
            correlation_id="incremental-page-test",
        )
        assert first.next_checkpoint is not None
        second = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.TRANSACTIONS,
            checkpoint=first.next_checkpoint,
            correlation_id="incremental-page-test",
        )
    finally:
        await client.aclose()

    assert requests[0].url.params.get("cursor") is None
    assert requests[0].url.params["time"] == overlap_started_at.isoformat()
    assert requests[1].url.params["cursor"] == "incremental-2"
    assert requests[1].url.params["time"] == overlap_started_at.isoformat()
    assert first.next_checkpoint.overlap_started_at == overlap_started_at
    assert second.complete is True


@pytest.mark.asyncio
async def test_incremental_next_page_must_preserve_the_overlap_filter() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=(FIXTURES / "transactions_page_1.json").read_bytes())

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(IngestionFailure) as captured:
            await adapter.read_page(
                owner_id="owner-1",
                account_id="account-1",
                capability=IngestionCapability.TRANSACTIONS,
                checkpoint=Checkpoint(
                    source_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    overlap_started_at=datetime(2025, 12, 25, tzinfo=UTC),
                ),
                correlation_id="incremental-filter-drift",
            )
    finally:
        await client.aclose()

    assert captured.value.category is FailureCategory.PAGINATION
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_provider_contract_failure_maps_to_sanitized_ingestion_category() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"currency": "EUR"})

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(IngestionFailure) as captured:
            await adapter.read_page(
                owner_id="owner-1",
                account_id="account-1",
                capability=IngestionCapability.ACCOUNT,
                checkpoint=None,
                correlation_id="error-test",
            )
    finally:
        await client.aclose()
    assert captured.value.category is FailureCategory.CONTRACT
    assert "currency" not in str(captured.value)


@pytest.mark.asyncio
async def test_instrument_ticker_is_the_stable_provider_identifier() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "addedOn": "2026-01-15T12:00:00Z",
                    "currencyCode": "EUR",
                    "extendedHours": False,
                    "isin": "XS0000000001",
                    "maxOpenQuantity": 1000,
                    "name": "Synthetic Global Equity",
                    "shortName": "Synthetic Equity",
                    "ticker": "SYNEQ",
                    "type": "equity",
                    "workingScheduleId": 1,
                }
            ],
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        page = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.INSTRUMENTS,
            checkpoint=None,
            correlation_id="instrument-id-test",
        )
    finally:
        await client.aclose()

    assert page.records[0].provider_record_id == "SYNEQ"
    assert page.records[0].payload["isin"] == "XS0000000001"


@pytest.mark.asyncio
async def test_dividend_date_remains_typed_at_the_application_boundary() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "amount": 17.5,
                        "amountInEuro": 17.5,
                        "currency": "EUR",
                        "grossAmountPerShare": 1.75,
                        "instrument": {
                            "currency": "EUR",
                            "isin": "XS0000000001",
                            "name": "Synthetic Global Equity",
                            "ticker": "SYNEQ",
                        },
                        "paidOn": "2026-06-30",
                        "quantity": 10,
                        "reference": "dividend-date-1",
                        "ticker": "SYNEQ",
                        "tickerCurrency": "EUR",
                        "type": "ORDINARY",
                    }
                ],
                "nextPagePath": None,
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        page = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.DIVIDENDS,
            checkpoint=None,
            correlation_id="dividend-date-test",
        )
    finally:
        await client.aclose()

    record = page.records[0]
    assert record.provider_record_id == "dividend-date-1"
    assert record.payload["paidOn"] == date(2026, 6, 30)
    assert record.source_timestamp == datetime(2026, 6, 30, tzinfo=UTC)


def _export_canary() -> tuple[str, tuple[str, ...]]:
    token = "_".join(("EXPORT", "URL", "CANARY"))
    host = ".".join(("signed", "example", "invalid"))
    path = "/" + "report" + ".csv"
    signature = "-".join(("private", "export", "signature"))
    fragment = "-".join(("private", "export", "fragment"))
    url = f"https://{host}{path}?token={token}&signature={signature}#" + fragment
    return url, (url, token, host, path, signature, fragment)


def _export_payload(url: object) -> dict[str, object]:
    return {
        "reportId": 17,
        "status": "Finished",
        "timeFrom": "2026-01-01T00:00:00Z",
        "timeTo": "2026-08-31T00:00:00Z",
        "dataIncluded": {"includeDividends": True, "includeTransactions": True},
        "downloadLink": url,
    }


@pytest.mark.asyncio
async def test_export_metadata_is_selected_before_every_fingerprint_and_url_is_never_followed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    url, forbidden = _export_canary()
    requests: list[tuple[str, str]] = []
    current_url = url

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        payload = _export_payload(current_url)
        payload["download_link"] = current_url
        payload["futureProviderField"] = {"url": current_url}
        payload["dataIncluded"] = {
            "includeDividends": True,
            "includeTransactions": True,
            "futureLink": current_url,
        }
        return httpx.Response(200, json=[payload])

    caplog.set_level(logging.DEBUG)
    adapter, client = _adapter(httpx.MockTransport(handler))
    pages = []
    hashes = []
    try:
        for rotation in ("original", "rotated"):
            current_url = url + "-" + rotation
            response = await client.get_historical_exports(correlation_id="export-hash-test")
            for component in forbidden:
                assert component not in repr(response)
                assert component not in repr(response.model_dump())
            hashes.append(response.source_sha256)
            pages.append(
                await adapter.read_page(
                    owner_id="owner-1",
                    account_id="account-1",
                    capability=IngestionCapability.EXPORT_METADATA,
                    checkpoint=None,
                    correlation_id="export-minimization-test",
                )
            )
    finally:
        await client.aclose()

    record = pages[0].records[0]
    expected = {
        "reportId": 17,
        "status": "Finished",
        "timeFrom": datetime(2026, 1, 1, tzinfo=UTC),
        "timeTo": datetime(2026, 8, 31, tzinfo=UTC),
        "dataIncluded": {"includeDividends": True, "includeTransactions": True},
        "downloadAvailable": True,
    }
    assert record.payload == expected
    assert record.source_timestamp == expected["timeTo"]
    assert (
        record.payload_sha256
        == SourceRecord(
            provider_record_id="17",
            source_timestamp=record.source_timestamp,
            observed_at=record.observed_at,
            schema_version=record.schema_version,
            payload=expected,
        ).payload_sha256
    )
    assert hashes[0] == hashes[1]
    assert record.payload_sha256 == pages[1].records[0].payload_sha256
    assert pages[0].fingerprint == pages[1].fingerprint
    retained = repr(pages) + repr(hashes) + caplog.text
    for component in forbidden:
        assert component not in retained
    assert requests == [("GET", "https://demo.trading212.com/api/v0/equity/history/exports")] * 4


@pytest.mark.asyncio
@pytest.mark.parametrize("download_link", [None, ""])
async def test_export_without_download_retains_only_false_availability(
    download_link: str | None,
) -> None:
    adapter, client = _adapter(
        httpx.MockTransport(lambda _: httpx.Response(200, json=[_export_payload(download_link)]))
    )
    try:
        page = await adapter.read_page(
            owner_id="owner-1",
            account_id="account-1",
            capability=IngestionCapability.EXPORT_METADATA,
            checkpoint=None,
            correlation_id="export-unavailable-test",
        )
    finally:
        await client.aclose()
    assert page.records[0].payload["downloadAvailable"] is False
    assert "downloadLink" not in page.records[0].payload
    assert "download_link" not in page.records[0].payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_field", ["downloadLink", "status", "dataIncluded", "timeTo", "reportId", "json"]
)
async def test_invalid_export_dto_remains_sanitized_in_exceptions_traces_and_logs(
    invalid_field: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url, forbidden = _export_canary()
    payload = _export_payload(url)
    payload[invalid_field] = {"includeDividends": url} if invalid_field == "dataIncluded" else url
    if invalid_field == "downloadLink":
        payload[invalid_field] = {"value": url}
    content = ("{" + url).encode() if invalid_field == "json" else json.dumps([payload]).encode()
    adapter, client = _adapter(httpx.MockTransport(lambda _: httpx.Response(200, content=content)))
    caplog.set_level(logging.DEBUG)
    try:
        with pytest.raises(IngestionFailure) as captured:
            await adapter.read_page(
                owner_id="owner-1",
                account_id="account-1",
                capability=IngestionCapability.EXPORT_METADATA,
                checkpoint=None,
                correlation_id="export-validation-test",
            )
    finally:
        await client.aclose()
    assert captured.value.category is FailureCategory.CONTRACT
    rendered = "".join(traceback.format_exception(captured.value)) + caplog.text
    for component in forbidden:
        assert component not in rendered
    provider_error = captured.value.__cause__
    assert provider_error is not None
    assert provider_error.__cause__ is None
    assert provider_error.__context__ is None


@pytest.mark.asyncio
async def test_synthetic_export_metadata_matches_minimized_provider_representation() -> None:
    page = await SyntheticIngestionProvider().read_page(
        owner_id="owner-1",
        account_id="account-1",
        capability=IngestionCapability.EXPORT_METADATA,
        checkpoint=None,
        correlation_id="synthetic-export-test",
    )
    assert set(page.records[0].payload) == {
        "reportId",
        "status",
        "timeFrom",
        "timeTo",
        "dataIncluded",
        "downloadAvailable",
    }
    assert page.records[0].payload["downloadAvailable"] is False
