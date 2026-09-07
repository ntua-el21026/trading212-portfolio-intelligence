"""Adapter from strict provider DTOs to the application ingestion port."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from pydantic import BaseModel
from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionFailure,
    RateObservation,
    SourcePage,
    SourceRecord,
)

from .allowlist import CAPABILITIES
from .client import Trading212Client
from .errors import ProviderError, ProviderErrorKind
from .models import HistoricalExportDTO, PaginatedDTO, ProviderResponse, RateLimitObservation

_ERROR_CATEGORIES = {
    ProviderErrorKind.AUTHENTICATION: FailureCategory.AUTHENTICATION,
    ProviderErrorKind.AUTHORIZATION: FailureCategory.AUTHORIZATION,
    ProviderErrorKind.RATE_LIMITED: FailureCategory.RATE_LIMIT,
    ProviderErrorKind.TRANSIENT: FailureCategory.TRANSIENT,
    ProviderErrorKind.TIMEOUT: FailureCategory.TRANSIENT,
    ProviderErrorKind.CONTRACT: FailureCategory.CONTRACT,
    ProviderErrorKind.CONFIGURATION: FailureCategory.CONFIGURATION,
    ProviderErrorKind.NOT_FOUND: FailureCategory.CONTRACT,
    ProviderErrorKind.PERMANENT: FailureCategory.CONTRACT,
    ProviderErrorKind.PAGINATION: FailureCategory.PAGINATION,
}


class Trading212IngestionAdapter(BrokerAccountDataProvider):
    """Capability-only provider port; owner/account inputs never become URLs."""

    def __init__(self, client: Trading212Client) -> None:
        self._client = client

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, account_id
        try:
            if capability is IngestionCapability.INSTRUMENTS:
                instruments_response = await self._client.get_instruments(
                    correlation_id=correlation_id
                )
                return _single_page(instruments_response, capability, ("ticker",))
            if capability is IngestionCapability.EXCHANGES:
                exchanges_response = await self._client.get_exchanges(correlation_id=correlation_id)
                return _single_page(exchanges_response, capability, ("id",))
            if capability is IngestionCapability.ACCOUNT:
                account_response = await self._client.get_account_summary(
                    correlation_id=correlation_id
                )
                return _single_page(account_response, capability, ("id",))
            if capability is IngestionCapability.POSITIONS:
                positions_response = await self._client.get_positions(correlation_id=correlation_id)
                return _single_page(
                    positions_response,
                    capability,
                    ("instrument", "ticker"),
                )
            if capability is IngestionCapability.PENDING_ORDERS:
                orders_response = await self._client.get_pending_orders(
                    correlation_id=correlation_id
                )
                return _single_page(orders_response, capability, ("id",))
            if capability is IngestionCapability.EXPORT_METADATA:
                exports_response = await self._client.get_historical_exports(
                    correlation_id=correlation_id
                )
                return _single_page(exports_response, capability, ("reportId",))
            if capability is IngestionCapability.HISTORICAL_ORDERS:
                cursor = _integer_cursor(checkpoint)
                history_response = await self._client.get_historical_orders_page(
                    cursor=cursor,
                    limit=50,
                    correlation_id=correlation_id,
                )
                return self._paginated_page(
                    history_response,
                    capability,
                    ("order", "id"),
                    original_query={"limit": "50"},
                )
            if capability is IngestionCapability.TRANSACTIONS:
                overlap_started_at = (
                    checkpoint.overlap_started_at if checkpoint is not None else None
                )
                transactions_response = await self._client.get_transactions_page(
                    cursor=checkpoint.cursor if checkpoint else None,
                    time=overlap_started_at,
                    limit=50,
                    correlation_id=correlation_id,
                )
                original_query = {"limit": "50"}
                if overlap_started_at is not None:
                    original_query["time"] = overlap_started_at.isoformat()
                return self._paginated_page(
                    transactions_response,
                    capability,
                    ("reference",),
                    original_query=original_query,
                    overlap_started_at=overlap_started_at,
                )
            if capability is IngestionCapability.DIVIDENDS:
                cursor = _integer_cursor(checkpoint)
                dividends_response = await self._client.get_dividends_page(
                    cursor=cursor,
                    limit=50,
                    correlation_id=correlation_id,
                )
                return self._paginated_page(
                    dividends_response,
                    capability,
                    ("reference",),
                    original_query={"limit": "50"},
                )
            raise IngestionFailure(FailureCategory.CONFIGURATION, "unsupported typed capability")
        except ProviderError as exc:
            raise IngestionFailure(
                _ERROR_CATEGORIES[exc.kind],
                "provider read failed with a sanitized category",
                retryable=exc.retryable,
            ) from exc

    def _paginated_page[ItemT](
        self,
        response: ProviderResponse[PaginatedDTO[ItemT]],
        capability: IngestionCapability,
        id_path: tuple[str, ...],
        *,
        original_query: dict[str, str],
        overlap_started_at: datetime | None = None,
    ) -> SourcePage:
        page = response.data
        items = page.items
        next_page_path = page.next_page_path
        records = tuple(
            _source_record(item, response.observed_at, capability, id_path) for item in items
        )
        if next_page_path is None:
            next_checkpoint = None
        else:
            contract = CAPABILITIES[capability.value]
            query = self._client._reconstruct_next_query(  # internal sealed adapter path
                capability=contract,
                next_page_path=next_page_path,
                original_query=original_query,
            )
            cursor = query.get("cursor")
            if cursor is None:
                raise IngestionFailure(
                    FailureCategory.PAGINATION,
                    "provider next-page reference did not include a cursor",
                )
            source_timestamp = max(
                (record.source_timestamp for record in records),
                default=response.observed_at,
            )
            next_checkpoint = Checkpoint(
                cursor=cursor,
                source_timestamp=source_timestamp,
                page_fingerprint=response.source_sha256,
                overlap_started_at=overlap_started_at,
            )
        return SourcePage(
            records=records,
            next_checkpoint=next_checkpoint,
            complete=next_checkpoint is None,
            rate=_rate(response.rate_limit),
        )


def _single_page[ResponseT](
    response: ProviderResponse[ResponseT],
    capability: IngestionCapability,
    id_path: tuple[str, ...],
) -> SourcePage:
    value = response.data
    items = value if isinstance(value, tuple) else (value,)
    return SourcePage(
        records=tuple(
            _source_record(item, response.observed_at, capability, id_path) for item in items
        ),
        next_checkpoint=None,
        complete=True,
        rate=_rate(response.rate_limit),
    )


def _source_record(
    value: object,
    observed_at: datetime,
    capability: IngestionCapability,
    id_path: tuple[str, ...],
) -> SourceRecord:
    if not isinstance(value, BaseModel):
        raise IngestionFailure(FailureCategory.CONTRACT, "provider item was not a validated DTO")
    if capability is IngestionCapability.EXPORT_METADATA:
        if not isinstance(value, HistoricalExportDTO):
            raise IngestionFailure(FailureCategory.CONTRACT, "export item was not a validated DTO")
        payload = value.retained_metadata()
    else:
        payload = value.model_dump(mode="python", by_alias=True, exclude_none=False)
    provider_id_value: object = payload
    for part in id_path:
        if not isinstance(provider_id_value, dict) or part not in provider_id_value:
            raise IngestionFailure(
                FailureCategory.CONTRACT, "provider item lacks a stable identifier"
            )
        provider_id_value = provider_id_value[part]
    provider_id = str(provider_id_value)
    source_timestamp = _source_timestamp(payload, observed_at)
    return SourceRecord(
        provider_record_id=provider_id,
        source_timestamp=source_timestamp,
        observed_at=observed_at,
        payload=payload,
        schema_version=f"trading212-v0-20260831:{capability.value}",
    )


def _source_timestamp(payload: dict[str, object], observed_at: datetime) -> datetime:
    for key in ("dateTime", "timestamp", "createdAt", "addedOn", "timeTo"):
        value = payload.get(key)
        if isinstance(value, datetime):
            return value.astimezone(UTC)
    paid_on = payload.get("paidOn")
    if isinstance(paid_on, date):
        return datetime.combine(paid_on, time.min, tzinfo=UTC)
    return observed_at


def _integer_cursor(checkpoint: Checkpoint | None) -> int | None:
    if checkpoint is None or checkpoint.cursor is None:
        return None
    try:
        value = int(checkpoint.cursor)
    except ValueError as exc:
        raise IngestionFailure(
            FailureCategory.PAGINATION, "invalid persisted integer cursor"
        ) from exc
    if value < 0:
        raise IngestionFailure(FailureCategory.PAGINATION, "invalid persisted integer cursor")
    return value


def _rate(value: RateLimitObservation | None) -> RateObservation | None:
    if value is None:
        return None
    return RateObservation(
        limit=value.limit,
        period_seconds=value.period_seconds,
        remaining=value.remaining,
        reset_at=value.reset_at,
        used=value.used,
    )
